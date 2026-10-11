/** @odoo-module **/
import { Component, onWillStart, useState } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { Scanner } from "../components/scanner";
import { QualityTest } from "../components/quality";
export class Board extends Component {
  static template = "deep.Shopfloor";
  static components = { Scanner, QualityTest };
  static props = ["*"];
  setup() {
    this.orm = useService("orm");
    this.action = useService("action");
    this.notification = useService("notification");
    this.state = useState({
      orders: [],
      selected: 0,
      offset: 0,
      busy: false,
      error: "",
      session: null,
      quantity: 1,
      checked: {},
    });
    this.scan = this.scan.bind(this);
    this.submit = this.submit.bind(this);
    onWillStart(() => this.refresh());
  }
  get order() {
    return this.state.orders.find((p) => p.id === Number(this.state.selected));
  }
  async run(fn) {
    if (this.state.busy) return;
    this.state.busy = true;
    this.state.error = "";
    try {
      await fn();
    } catch (e) {
      this.state.error = e.data?.message || e.message || "Request failed";
    } finally {
      this.state.busy = false;
    }
  }
  async refresh() {
    this.state.orders = await this.orm.call("deep.shopfloor", "board", [
      this.state.offset,
    ]);
    if (!this.order) this.state.selected = this.state.orders[0]?.id || 0;
  }
  async executeAction(action, options = {}) {
    if (action.type === "ir.actions.act_window" && !action.views) {
      action = {
        ...action,
        views: (action.view_mode || "form")
          .split(",")
          .map((mode) => [false, mode]),
      };
    }
    return this.action.doAction(action, options);
  }
  async acknowledge(work) {
    const action = await this.orm.call(
      "mrp.workorder",
      "action_deep_acknowledge",
      [[work.id]],
    );
    await this.executeAction(action, { onClose: () => this.refresh() });
  }
  async page(direction) {
    await this.run(async () => {
      this.state.offset = Math.max(0, this.state.offset + direction * 50);
      await this.refresh();
    });
  }
  async station(w, action) {
    await this.run(async () => {
      if (action === "serialize") this.serialKey ||= crypto.randomUUID();
      const result = await this.orm.call("deep.shopfloor", "station_action", [
        w.id,
        action,
        Number(this.state.quantity),
        this.serialKey || "",
      ]);
      if (action === "serialize") this.serialKey = null;
      if (result?.type) await this.executeAction(result);
      this.notification.add(
        action === "serialize"
          ? `${result.length} serials created`
          : "Station updated",
        { type: "success" },
      );
      await this.refresh();
    });
  }
  async scan(serial) {
    await this.run(async () => {
      const work = this.order?.stations.find(
        (w) => w.checkpoint === "test" && w.state !== "done",
      );
      if (!work)
        throw new Error("Select an order with an active S12 testing station.");
      this.scanKey ||= crypto.randomUUID();
      this.state.session = await this.orm.call(
        "deep.quality.session",
        "action_scan",
        [serial, work.id, this.scanKey],
      );
      this.scanKey = null;
      await this.refresh();
    });
  }
  async submit(answers, notes, hold) {
    await this.run(async () => {
      const result = await this.orm.call(
        "deep.quality.session",
        "action_submit",
        [[this.state.session.id], answers, notes, hold],
      );
      this.notification.add(
        `${result.serial}: ${result.outcome.toUpperCase()}`,
        { type: result.outcome === "pass" ? "success" : "warning" },
      );
      this.state.session = null;
      await this.refresh();
    });
  }
  get selectedIds() {
    return Object.entries(this.state.checked)
      .filter(([, value]) => value)
      .map(([id]) => Number(id));
  }
  async release() {
    await this.run(async () => {
      if (!this.selectedIds.length)
        throw new Error("Select passing units for release.");
      const result = await this.orm.call("deep.shopfloor", "release", [
        this.selectedIds,
      ]);
      if (result?.type) await this.executeAction(result);
      this.state.checked = {};
      await this.refresh();
    });
  }
  async print() {
    await this.run(async () => {
      if (!this.selectedIds.length) throw new Error("Select serials to print.");
      await this.executeAction(
        await this.orm.call("deep.shopfloor", "print_labels", [
          this.selectedIds,
        ]),
      );
    });
  }
  async open(model, id) {
    await this.executeAction({
      type: "ir.actions.act_window",
      res_model: model,
      res_id: id,
      views: [[false, "form"]],
      target: "current",
    });
  }
}
registry.category("actions").add("deep.shopfloor", Board);
