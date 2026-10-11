/** @odoo-module **/
import { Component, onWillStart, useState } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
export class Dashboard extends Component {
  static template = "deep.Cockpit";
  static props = ["*"];
  setup() {
    this.orm = useService("orm");
    this.action = useService("action");
    this.state = useState({
      data: null,
      busy: false,
      error: "",
      tab: "overview",
    });
    onWillStart(() => this.refresh());
  }
  async refresh() {
    this.state.busy = true;
    try {
      this.state.data = await this.orm.call(
        "deep.manufacturing.dashboard",
        "metrics",
        [],
      );
      this.state.error = "";
    } catch (e) {
      this.state.error = e.data?.message || e.message;
    } finally {
      this.state.busy = false;
    }
  }
  async navigate(model, id = false, domain = []) {
    await this.action.doAction({
      type: "ir.actions.act_window",
      res_model: model,
      res_id: id,
      domain,
      views: id
        ? [[false, "form"]]
        : [
            [false, "list"],
            [false, "form"],
          ],
    });
  }
  async floor() {
    await this.action.doAction("deep_shopfloor.action_shopfloor");
  }
  get range() {
    const rows = this.state.data?.schedule || [];
    const dates = rows.flatMap((r) => [
      Date.parse(r.start.replace(" ", "T") + "Z"),
      Date.parse(r.end.replace(" ", "T") + "Z"),
    ]);
    const lo = Math.min(...dates),
      hi = Math.max(...dates);
    return { lo, span: Math.max(3600000, hi - lo) };
  }
  position(w) {
    const { lo, span } = this.range;
    const start = Date.parse(w.start.replace(" ", "T") + "Z"),
      end = Date.parse(w.end.replace(" ", "T") + "Z");
    return `left:${((start - lo) / span) * 100}%;width:${Math.max(0.3, ((end - start) / span) * 100)}%`;
  }
  load(c) {
    return `width:${Math.min(100, c.available ? (c.required / c.available) * 100 : 100)}%;background:${c.required > c.available ? "#b65c44" : "#237b68"}`;
  }
  async reschedule(w) {
    await this.action.doAction({
      type: "ir.actions.act_window",
      res_model: "deep.schedule.change",
      views: [[false, "form"]],
      target: "new",
      context: { default_workorder_id: w.id, default_start: w.start },
    });
    await this.refresh();
  }
}
registry.category("actions").add("deep.cockpit", Dashboard);
