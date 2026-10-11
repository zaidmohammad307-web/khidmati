/** @odoo-module **/
import { Component, useState } from "@odoo/owl";
export class QualityTest extends Component {
  static template = "deep.QualityTest";
  static props = { session: Object, onSubmit: Function, busy: Boolean };
  setup() {
    this.state = useState({ answers: {}, notes: "", hold: false });
  }
  answer(p, e) {
    const value = e.target.value;
    if (value === "") {
      delete this.state.answers[p.id];
      return;
    }
    this.state.answers[p.id] =
      p.kind === "numeric"
        ? Number(value)
        : ["boolean", "pass_fail"].includes(p.kind)
          ? value === "true"
          : value;
  }
  submit() {
    this.props.onSubmit(
      Object.entries(this.state.answers).map(([id, value]) => ({
        point_id: Number(id),
        value,
      })),
      this.state.notes,
      this.state.hold,
    );
  }
}
