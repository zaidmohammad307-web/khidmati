/** @odoo-module **/
import { Component, useState, useRef, onMounted } from "@odoo/owl";
export class Scanner extends Component {
  static template = "deep.Scanner";
  static props = { onScan: Function, busy: Boolean };
  setup() {
    this.state = useState({ value: "" });
    this.input = useRef("scan");
    onMounted(() => this.input.el?.focus());
  }
  submit() {
    if (!this.props.busy && this.state.value.trim())
      this.props.onScan(this.state.value.trim());
  }
}
