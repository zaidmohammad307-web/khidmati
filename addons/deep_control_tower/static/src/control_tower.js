/** @odoo-module **/
import {
  Component,
  onWillStart,
  onMounted,
  onWillUnmount,
  useState,
} from "@odoo/owl";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";

export class ActivityTable extends Component {
  static template = "deep.TowerActivityTable";
  static props = { rows: Array, columns: Array, model: String, open: Function };
  value(row, key) {
    const value = row[key];
    return typeof value === "boolean" ? (value ? "Yes" : "No") : value;
  }
}

export class ControlTower extends Component {
  static template = "deep.ControlTower";
  static components = { ActivityTable };
  static props = ["*"];
  setup() {
    this.orm = useService("orm");
    this.action = useService("action");
    this.state = useState({
      data: null,
      error: "",
      busy: false,
      tab: "overview",
      auto: false,
    });
    this.open = this.open.bind(this);
    this.tabs = [
      ["overview", "Overview"],
      ["kits", "Material racks"],
      ["dispatch", "Dispatch"],
      ["shifts", "Shift actuals"],
      ["maintenance", "Maintenance"],
      ["quality", "Quality actions"],
      ["contracts", "Deliveries"],
    ];
    this.tables = {
      kits: {
        model: "deep.material.kit",
        columns: [
          ["name", "Kit"],
          ["mo", "MO"],
          ["department", "Department"],
          ["rack", "Staging rack"],
          ["capacity", "Release capacity"],
          ["missing", "Unstaged items"],
          ["state", "State"],
        ],
      },
      dispatch: {
        model: "mrp.production",
        columns: [
          ["name", "MO"],
          ["product", "Product"],
          ["quantity", "Quantity"],
          ["priority", "Priority"],
          ["promise", "Promise date"],
          ["progress", "Stations done %"],
          ["state", "State"],
        ],
      },
      shifts: {
        model: "deep.shift.report",
        columns: [
          ["name", "Shift"],
          ["department", "Department"],
          ["mo", "MO"],
          ["good", "Reported good"],
          ["rework", "Rework"],
          ["scrap", "Scrap"],
          ["downtime", "Downtime min"],
          ["state", "State"],
        ],
      },
      maintenance: {
        model: "deep.downtime.event",
        columns: [
          ["name", "Breakdown"],
          ["center", "Center"],
          ["reason", "Reason"],
          ["hours", "Hours"],
          ["technician", "Technician"],
          ["expected", "Expected restart"],
          ["state", "State"],
        ],
      },
      quality: {
        model: "deep.nonconformance",
        columns: [
          ["name", "Case"],
          ["unit", "Unit"],
          ["severity", "Severity"],
          ["blocking", "Blocks release"],
          ["owner", "Owner"],
          ["due", "Due"],
          ["state", "State"],
        ],
      },
      contracts: {
        model: "deep.contract.milestone",
        columns: [
          ["contract", "Contract"],
          ["name", "Milestone"],
          ["customer", "Customer"],
          ["product", "Product"],
          ["quantity", "Required"],
          ["delivered", "Delivered"],
          ["remaining", "Remaining"],
          ["due", "Due"],
          ["state", "State"],
        ],
      },
    };
    onWillStart(() => this.refresh());
    onMounted(() => {
      this.timer = setInterval(() => {
        if (this.state.auto && !document.hidden) this.refresh();
      }, 30000);
    });
    onWillUnmount(() => {
      clearInterval(this.timer);
    });
  }
  async refresh() {
    if (this.state.busy) return;
    this.state.busy = true;
    try {
      this.state.data = await this.orm.call(
        "deep.control.tower",
        "metrics",
        [],
      );
      this.state.error = "";
    } catch (error) {
      this.state.error = error.data?.message || error.message;
    } finally {
      this.state.busy = false;
    }
  }
  async open(model, id = false) {
    await this.action.doAction({
      type: "ir.actions.act_window",
      res_model: model,
      res_id: id,
      views: id
        ? [[false, "form"]]
        : [
            [false, "list"],
            [false, "form"],
          ],
    });
  }
  async route(id) {
    await this.action.doAction(id);
  }
  async exportActions() {
    const action = await this.orm.call(
      "deep.control.tower",
      "action_export",
      [],
    );
    await this.action.doAction(action);
  }
  get currentTable() {
    return this.tables[this.state.tab];
  }
}
registry.category("actions").add("deep.control.tower", ControlTower);
