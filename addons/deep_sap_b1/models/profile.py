import re
from datetime import timedelta
from odoo import api, fields, models
from odoo.exceptions import AccessError, UserError
from odoo.addons.deep_core.security import internal, require_internal, require_role, lock
from ..services.client import ServiceLayerClient, SAPError, base_url


class Managed(models.AbstractModel):
    _name = "deep.sap.managed"
    _description = "Server-managed SAP Synchronization Record"
    company_id = fields.Many2one(
        "res.company", required=True, default=lambda self: self.env.company, index=True
    )

    @api.model_create_multi
    def create(self, values):
        require_internal(self.env)
        return super().create(values)

    def write(self, values):
        require_internal(self.env)
        return super().write(values)

    def unlink(self):
        raise AccessError("SAP synchronization history cannot be deleted.")


class Profile(models.Model):
    _name = "deep.sap.profile"
    _description = "SAP Business One VPN Connection"
    _inherit = ["mail.thread", "mail.activity.mixin"]
    _check_company_auto = True
    name = fields.Char(required=True)
    company_id = fields.Many2one(
        "res.company", required=True, default=lambda self: self.env.company
    )
    base_url = fields.Char(
        help="HTTPS address visible from the Odoo host; leave empty to use SAP_B1_BASE_URL from its environment."
    )
    environment_prefix = fields.Char(default="SAP_B1", required=True)
    active = fields.Boolean(default=True)
    automatic_sync = fields.Boolean(default=False)
    interval_minutes = fields.Integer(default=15, required=True)
    max_age_minutes = fields.Integer(default=60, required=True)
    max_records = fields.Integer(default=10000, required=True)
    sync_partners = fields.Boolean(default=True)
    sync_purchase = fields.Boolean(default=True)
    sync_sales = fields.Boolean(default=True)
    sync_boms = fields.Boolean(default=False)
    last_success = fields.Datetime(readonly=True)
    last_check = fields.Datetime(readonly=True)
    next_sync = fields.Datetime(default=fields.Datetime.now, readonly=True)
    connection_state = fields.Selection(
        [("unknown", "Not tested"), ("ready", "Connected"), ("error", "Attention needed")],
        default="unknown",
        readonly=True,
    )
    status_message = fields.Text(readonly=True)
    sap_version = fields.Char(readonly=True)
    warehouse_ids = fields.One2many("deep.sap.warehouse.map", "profile_id")
    uom_ids = fields.One2many("deep.sap.uom.map", "profile_id")
    job_ids = fields.One2many("deep.sap.job", "profile_id", readonly=True)
    _limits = models.Constraint(
        "CHECK(interval_minutes>=1 AND max_age_minutes>=1 AND max_records>=1 AND max_records<=100000)",
        "Invalid SAP sync limits.",
    )
    _results = {
        "last_success",
        "last_check",
        "next_sync",
        "connection_state",
        "status_message",
        "sap_version",
    }

    @api.constrains("base_url", "environment_prefix")
    def _validate(self):
        for profile in self:
            if not re.fullmatch(r"[A-Z][A-Z0-9_]{0,40}", profile.environment_prefix):
                raise UserError("Use an uppercase environment variable prefix.")
            if profile.base_url:
                try:
                    base_url(profile.base_url)
                except SAPError as error:
                    raise UserError(str(error)) from None

    @api.model_create_multi
    def create(self, values):
        if any(any(value.get(key) for key in self._results) for value in values):
            require_internal(self.env)
        return super().create(values)

    def write(self, values):
        if set(values) & self._results:
            require_internal(self.env)
        if set(values) - self._results:
            require_role(self.env, "manager")
            lock(self)
            if (
                self.env["deep.sap.job"]
                .sudo()
                .search_count(
                    [
                        ("profile_id", "in", self.ids),
                        ("state", "in", ["queued", "running", "retry"]),
                    ]
                )
            ):
                raise UserError(
                    "Finish or cancel the pending SAP job before changing its mappings or connection."
                )
        return super().write(values)

    def action_test_connection(self):
        require_role(self.env, "manager", "procurement")
        self.ensure_one()
        lock(self)
        try:
            with ServiceLayerClient.from_profile(self) as client:
                version = client.login_info
                client.collection("Items", {"$select": "ItemCode", "$top": 1})
            internal(self).write(
                {
                    "connection_state": "ready",
                    "last_check": fields.Datetime.now(),
                    "status_message": "Service Layer login and authorized Items read succeeded.",
                    "sap_version": version["version"],
                }
            )
            severity = "success"
        except SAPError as error:
            internal(self).write(
                {
                    "connection_state": "error",
                    "last_check": fields.Datetime.now(),
                    "status_message": error.code + ": " + str(error),
                }
            )
            severity = "danger"
        self.env["deep.audit.event"]._record(
            self, "sap_connection_check", reason=self.status_message
        )
        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "title": "SAP Business One",
                "message": self.status_message,
                "type": severity,
                "sticky": severity == "danger",
            },
        }

    def action_queue_sync(self):
        require_role(self.env, "manager", "procurement", "planner")
        self.ensure_one()
        lock(self)
        if not self.active or not self.warehouse_ids:
            raise UserError("Activate the profile and map at least one SAP warehouse first.")
        job = (
            self.env["deep.sap.job"]
            .sudo()
            .search(
                [("profile_id", "=", self.id), ("state", "in", ["queued", "running", "retry"])],
                limit=1,
            )
        )
        if not job:
            job = internal(self.env["deep.sap.job"].sudo()).create(
                {
                    "profile_id": self.id,
                    "company_id": self.company_id.id,
                    "requested_by": self.env.uid,
                }
            )
            self.env["deep.audit.event"]._record(self, "sap_sync_queued", reason=str(job.id))
        return {
            "type": "ir.actions.act_window",
            "res_model": "deep.sap.job",
            "res_id": job.id,
            "view_mode": "form",
        }

    def _cron_queue(self):
        now = fields.Datetime.now()
        for profile in self.search(
            [("active", "=", True), ("automatic_sync", "=", True), ("next_sync", "<=", now)],
            limit=20,
        ):
            profile.with_company(profile.company_id).action_queue_sync()
            internal(profile).write(
                {"next_sync": now + timedelta(minutes=profile.interval_minutes)}
            )

    def _check_fresh(self):
        self.ensure_one()
        if (
            not self.active
            or not self.last_success
            or self.last_success < fields.Datetime.now() - timedelta(minutes=self.max_age_minutes)
        ):
            raise UserError(
                "SAP data is missing or stale. Complete a successful refresh before calculating this plan or reconciling stock."
            )


class Job(models.Model):
    _name = "deep.sap.job"
    _description = "SAP Synchronization Job / Retry History"
    _inherit = "deep.sap.managed"
    _check_company_auto = True
    _order = "id desc"
    profile_id = fields.Many2one("deep.sap.profile", required=True, check_company=True)
    requested_by = fields.Many2one("res.users", required=True)
    state = fields.Selection(
        [(key, key.title()) for key in ["queued", "running", "retry", "done", "failed", "cancel"]],
        default="queued",
        required=True,
    )
    attempts = fields.Integer()
    queued_at = fields.Datetime(default=fields.Datetime.now)
    started_at = fields.Datetime()
    finished_at = fields.Datetime()
    next_attempt = fields.Datetime(default=fields.Datetime.now)
    counts_json = fields.Json()
    error_code = fields.Char()
    message = fields.Text()

    def action_run(self):
        require_role(self.env, "manager", "procurement", "planner")
        self.ensure_one()
        lock(self.profile_id)
        lock(self)
        if self.state not in ("queued", "retry"):
            raise UserError("Run a queued or retryable job.")
        internal(self).write(
            {"state": "running", "attempts": self.attempts + 1, "started_at": fields.Datetime.now()}
        )
        try:
            from ..services.synchronization import SynchronizationService

            with self.env.cr.savepoint():
                with ServiceLayerClient.from_profile(self.profile_id) as client:
                    payload = SynchronizationService(self.env, self.profile_id).fetch(client)
                    counts = SynchronizationService(self.env, self.profile_id).apply(payload)
                internal(self.profile_id).write(
                    {
                        "last_success": fields.Datetime.now(),
                        "connection_state": "ready",
                        "status_message": "All selected datasets refreshed atomically.",
                        "next_sync": fields.Datetime.now()
                        + timedelta(minutes=self.profile_id.interval_minutes),
                    }
                )
            internal(self).write(
                {
                    "state": "done",
                    "finished_at": fields.Datetime.now(),
                    "counts_json": counts,
                    "message": "Successful refresh; native stock and approved BOMs were not overwritten.",
                    "error_code": False,
                }
            )
        except (SAPError, UserError, ValueError) as error:
            retryable = isinstance(error, SAPError) and error.retryable and self.attempts < 3
            code = error.code if isinstance(error, SAPError) else "DATA_CONFLICT"
            message = (
                str(error)
                if isinstance(error, (SAPError, UserError))
                else "SAP data validation failed. Check mappings and Service Layer metadata."
            )
            internal(self).write(
                {
                    "state": "retry" if retryable else "failed",
                    "next_attempt": fields.Datetime.now() + timedelta(minutes=2**self.attempts),
                    "finished_at": fields.Datetime.now(),
                    "error_code": code,
                    "message": message,
                }
            )
            internal(self.profile_id).write(
                {"connection_state": "error", "status_message": code + ": " + message}
            )
        self.env["deep.audit.event"]._record(self, "sap_sync_" + self.state, reason=self.message)
        return True

    def action_cancel(self):
        require_role(self.env, "manager")
        lock(self)
        if any(job.state not in ("queued", "retry") for job in self):
            raise UserError("Cancel only a pending SAP job.")
        internal(self).write({"state": "cancel", "finished_at": fields.Datetime.now()})
        self.env["deep.audit.event"]._record(self[:1], "sap_sync_cancelled")
        return True

    def _cron_run(self):
        job = self.search(
            [("state", "in", ["queued", "retry"]), ("next_attempt", "<=", fields.Datetime.now())],
            order="id",
            limit=1,
        )
        if job:
            job.with_company(job.company_id).action_run()
