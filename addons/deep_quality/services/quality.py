import re

from odoo import fields
from odoo.addons.deep_core.security import internal, lock, require_role
from odoo.exceptions import UserError

from .evaluation import evaluate


class QualityService:
    def __init__(self, env):
        self.env = env

    def scan(self, serial, workorder_id, key):
        require_role(self.env, "qa", "manager")
        if not isinstance(key, str) or not re.fullmatch(r"[A-Za-z0-9_-]{8,100}", key):
            raise UserError("Valid scan request key required.")
        unit = self.env["deep.production.unit"].search(
            [("name", "=", str(serial).strip()), ("company_id", "=", self.env.company.id)], limit=1
        )
        if not unit:
            raise UserError("Unknown serial in the current company.")
        lock(unit)
        existing = self.env["deep.quality.session"].search(
            [
                ("scan_id.request_key", "=", key),
                ("tester_id", "=", self.env.uid),
                ("company_id", "=", unit.company_id.id),
            ],
            limit=1,
        )
        if existing:
            if existing.unit_id != unit or existing.workorder_id.id != workorder_id:
                raise UserError("Request key belongs to a different serial/station.")
            return existing
        work = self.env["mrp.workorder"].browse(workorder_id).exists()
        work.check_access("write")
        if not work or work.production_id != unit.production_id or work.deep_checkpoint != "test":
            raise UserError("Scan at this serial’s configured S12 station.")
        if work.state not in ("ready", "progress") or any(
            p.state != "done" for p in work.blocked_by_workorder_ids
        ):
            raise UserError("Previous operations must be complete.")
        if unit.state == "testing":
            draft = self.env["deep.quality.session"].search(
                [
                    ("unit_id", "=", unit.id),
                    ("workorder_id", "=", work.id),
                    ("state", "=", "draft"),
                    ("tester_id", "=", self.env.uid),
                ],
                limit=1,
            )
            if draft:
                self.env["deep.audit.event"]._record(
                    unit, "quality_scan_resume", reason=work.name, unit=unit
                )
                return draft
        if unit.state not in ("serialized", "retest"):
            raise UserError("Serial is passed, held, under repair, or already being tested.")
        template = unit.product_id.deep_quality_template_id
        if not template or not template.active or not template.point_ids:
            raise UserError("Configure an active quality template with test points.")
        scan = internal(self.env["deep.scan.event"].sudo()).create(
            {
                "company_id": unit.company_id.id,
                "unit_id": unit.id,
                "workorder_id": work.id,
                "operator_id": self.env.uid,
                "request_key": key,
            }
        )
        session = internal(self.env["deep.quality.session"].sudo()).create(
            {
                "company_id": unit.company_id.id,
                "unit_id": unit.id,
                "workorder_id": work.id,
                "scan_id": scan.id,
                "template_id": template.id,
                "version": template.version,
                "tester_id": self.env.uid,
            }
        )
        session._on_started()
        unit._set_state("testing")
        self.env["deep.audit.event"]._record(unit, "quality_scan", reason=work.name, unit=unit)
        return session.with_env(self.env)

    def submit(self, session, answers, notes, hold=False):
        require_role(self.env, "qa", "manager")
        lock(session.unit_id)
        lock(session)
        if session.state != "draft" or session.unit_id.state != "testing":
            raise UserError("This session is already locked or no longer active.")
        if session.tester_id != self.env.user:
            raise UserError("Only the tester who started this session may submit it.")
        if not isinstance(hold, bool):
            raise UserError("Invalid hold selection.")
        if hold and not notes:
            raise UserError("Record a reason for the quality hold.")
        if not isinstance(answers, list):
            raise UserError("Submit a list of typed test answers.")
        indexed = {}
        for answer in answers:
            if not isinstance(answer, dict) or answer.get("point_id") in indexed:
                raise UserError("Duplicate or malformed test answers.")
            indexed[answer.get("point_id")] = answer.get("value")
        points = session.template_id.point_ids
        if set(indexed) - set(points.ids):
            raise UserError("An answer is not in this test version.")
        rows = []
        for p in points:
            if p.id not in indexed:
                if p.mandatory and not hold:
                    raise UserError("Complete mandatory point: " + p.name)
                continue
            value = indexed[p.id]
            try:
                passed = evaluate(
                    p.kind,
                    value,
                    p.minimum,
                    p.maximum,
                    p.expected_boolean,
                    (p.options or "").splitlines(),
                    p.expected_text or "",
                )
            except (ValueError, TypeError) as e:
                raise UserError(p.name + ": " + str(e)) from e
            row = {
                "session_id": session.id,
                "point_id": p.id,
                "passed": passed,
                "failure_code": p.failure_code if not passed else False,
            }
            row[
                "numeric_value"
                if p.kind == "numeric"
                else "boolean_value"
                if p.kind in ("boolean", "pass_fail")
                else "text_value"
            ] = value
            rows.append(row)
        if not rows and not hold:
            raise UserError("At least one test result is required.")
        internal(self.env["deep.quality.result"].sudo()).create(rows)
        outcome = "hold" if hold else "pass" if all(r["passed"] for r in rows) else "fail"
        internal(session).write(
            {"outcome": outcome, "state": "done", "ended_at": fields.Datetime.now(), "notes": notes}
        )
        session.unit_id._set_state(
            "passed" if outcome == "pass" else "hold",
            "line" if outcome == "pass" else "hold",
            notes,
        )
        if outcome == "pass":
            session._on_pass()
        else:
            session._on_failure()
        return {"outcome": outcome, "serial": session.unit_id.name}
