class SettingsGroup extends HTMLElement {
  connectedCallback() {
    if (this.shadowRoot) {
      this._sync();
      return;
    }

    const root = this.attachShadow({ mode: "open" });
    root.innerHTML = `
      <style>
        :host {
          display: block;
          background: var(--settings-surface, #fff);
          border: 1px solid var(--settings-line, #d7dce5);
          border-radius: 6px;
          overflow: hidden;
        }
        .head {
          padding: 12px;
          border-bottom: 1px solid var(--settings-line, #d7dce5);
          display: grid;
          gap: 6px;
        }
        .title-row {
          display: flex;
          align-items: center;
          justify-content: space-between;
          gap: 8px;
        }
        h2 {
          margin: 0;
          font-size: 13px;
          line-height: 1.4;
          color: var(--settings-text, #1f2937);
        }
        p {
          margin: 0;
          font-size: 12px;
          line-height: 1.45;
          color: var(--settings-muted, #6b7280);
        }
        button {
          border: 1px solid var(--settings-line, #d7dce5);
          border-radius: 4px;
          background: #fff;
          color: var(--settings-text, #1f2937);
          font-size: 11px;
          padding: 4px 8px;
          cursor: pointer;
        }
        .body {
          padding: 12px;
          display: grid;
          gap: 10px;
          grid-template-columns: repeat(2, minmax(0, 1fr));
        }
        :host([collapsed]) .body {
          display: none;
        }
        @media (max-width: 1100px) {
          .body {
            grid-template-columns: 1fr;
          }
        }
      </style>
      <section>
        <header class="head">
          <div class="title-row">
            <h2 id="title"></h2>
            <button id="toggle" type="button" hidden>Collapse</button>
          </div>
          <p id="desc"></p>
        </header>
        <div class="body"><slot></slot></div>
      </section>
    `;

    root.getElementById("toggle")?.addEventListener("click", () => {
      if (this.hasAttribute("collapsed")) {
        this.removeAttribute("collapsed");
      } else {
        this.setAttribute("collapsed", "1");
      }
      this._sync();
    });

    this._sync();
  }

  _sync() {
    if (!this.shadowRoot) return;
    const title = this.getAttribute("title") || "Settings Group";
    const description = this.getAttribute("description") || "";
    const collapsible = this.getAttribute("collapsible") === "1";
    const collapsed = this.hasAttribute("collapsed");

    this.shadowRoot.getElementById("title").textContent = title;
    const descEl = this.shadowRoot.getElementById("desc");
    descEl.textContent = description;
    descEl.hidden = !description;

    const toggle = this.shadowRoot.getElementById("toggle");
    toggle.hidden = !collapsible;
    toggle.textContent = collapsed ? "Expand" : "Collapse";
  }
}

class SettingsModelCard extends HTMLElement {
  constructor() {
    super();
    this._card = null;
  }

  connectedCallback() {
    if (this.shadowRoot) {
      this.render();
      return;
    }
    const root = this.attachShadow({ mode: "open" });
    root.innerHTML = `
      <style>
        :host {
          display: block;
          border: 1px solid var(--settings-line, #d7dce5);
          border-radius: 6px;
          background: #fff;
          padding: 10px;
        }
        .stage {
          font-weight: 700;
          font-size: 12px;
          color: var(--settings-text, #1f2937);
          margin-bottom: 6px;
        }
        .line {
          font-size: 11px;
          color: var(--settings-muted, #6b7280);
          line-height: 1.45;
          margin: 3px 0;
        }
        .line b {
          color: var(--settings-text, #1f2937);
        }
      </style>
      <div class="stage" id="stage"></div>
      <div class="line"><b>Purpose:</b> <span id="purpose"></span></div>
      <div class="line"><b>Workload:</b> <span id="workload"></span></div>
      <div class="line"><b>Reliability:</b> <span id="reliability"></span></div>
      <div class="line"><b>Guidance:</b> <span id="guidance"></span></div>
    `;

    this.render();
  }

  setCard(card) {
    this._card = card && typeof card === "object" ? card : null;
    this.render();
  }

  render() {
    if (!this.shadowRoot) return;
    const card = this._card || {};
    this.shadowRoot.getElementById("stage").textContent = String(card.stage || "stage");
    this.shadowRoot.getElementById("purpose").textContent = String(card.purpose || "");
    this.shadowRoot.getElementById("workload").textContent = String(card.workload || "");
    this.shadowRoot.getElementById("reliability").textContent = String(card.reliability || "");
    this.shadowRoot.getElementById("guidance").textContent = String(card.guidance || "");
  }
}

class SettingsPromptEditor extends HTMLElement {
  constructor() {
    super();
    this._value = { prefix: "", suffix: "", template: "" };
    this._spec = null;
  }

  connectedCallback() {
    if (this.shadowRoot) {
      this.render();
      return;
    }
    const root = this.attachShadow({ mode: "open" });
    root.innerHTML = `
      <style>
        :host {
          display: block;
          border: 1px solid var(--settings-line, #d7dce5);
          border-radius: 6px;
          background: var(--settings-field-bg, #fbfcfe);
          padding: 10px;
        }
        .top {
          display: grid;
          gap: 4px;
        }
        .label {
          font-size: 12px;
          font-weight: 700;
          color: var(--settings-text, #1f2937);
        }
        .hint {
          font-size: 11px;
          color: var(--settings-muted, #6b7280);
          line-height: 1.45;
        }
        .meta {
          font-size: 11px;
          color: var(--settings-muted, #6b7280);
          line-height: 1.45;
          border-top: 1px dashed var(--settings-line, #d7dce5);
          padding-top: 8px;
          margin-top: 8px;
          display: grid;
          gap: 6px;
        }
        textarea {
          width: 100%;
          border: 1px solid var(--settings-line, #d7dce5);
          border-radius: 6px;
          padding: 7px;
          font-size: 12px;
          color: var(--settings-text, #1f2937);
          background: #fff;
          min-height: 90px;
          resize: vertical;
          font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace;
        }
        .row {
          display: grid;
          gap: 4px;
        }
        .row label {
          font-size: 11px;
          color: var(--settings-text, #1f2937);
          font-weight: 700;
        }
        .warn {
          font-size: 11px;
          color: #b15f00;
        }
        .err {
          font-size: 11px;
          color: var(--settings-error, #b42318);
          display: none;
        }
        :host([invalid]) .err {
          display: block;
        }
        code {
          background: #fff;
          border: 1px solid var(--settings-line, #d7dce5);
          border-radius: 4px;
          padding: 1px 4px;
        }
        pre {
          margin: 0;
          white-space: pre-wrap;
          font-size: 11px;
          color: #334155;
          background: #fff;
          border: 1px solid var(--settings-line, #d7dce5);
          border-radius: 6px;
          padding: 8px;
          max-height: 170px;
          overflow: auto;
        }
      </style>
      <article>
        <div class="top">
          <div id="label" class="label"></div>
          <div id="hint" class="hint"></div>
        </div>

        <div class="row">
          <label for="prefix">Prefix</label>
          <textarea id="prefix"></textarea>
        </div>
        <div class="row">
          <label for="suffix">Suffix</label>
          <textarea id="suffix"></textarea>
        </div>
        <div class="row">
          <label for="template">Template (must include <code>{prompt}</code>)</label>
          <textarea id="template"></textarea>
        </div>
        <div id="warnings" class="warn"></div>
        <div id="error" class="err"></div>

        <div class="meta">
          <div><b>Script:</b> <span id="script"></span></div>
          <div><b>Purpose:</b> <span id="purpose"></span></div>
          <div><b>Variables:</b> <span id="vars"></span></div>
          <div><b>Output Contract:</b><pre id="contract"></pre></div>
          <div><b>Default Prompt:</b><pre id="default"></pre></div>
          <div><b>Effective Prompt Preview:</b><pre id="effective"></pre></div>
        </div>
      </article>
    `;

    this.render();
  }

  setPrompt(field, value, spec) {
    this._field = field;
    this._value = value && typeof value === "object" ? value : { prefix: "", suffix: "", template: "" };
    this._spec = spec && typeof spec === "object" ? spec : null;
    this.render();
  }

  render() {
    if (!this.shadowRoot) return;
    const field = this._field || {};
    const value = this._value || { prefix: "", suffix: "", template: "" };
    const spec = this._spec || {};

    this.shadowRoot.getElementById("label").textContent = String(field.label || field.path || "Prompt Override");
    this.shadowRoot.getElementById("hint").textContent = String(field.help || "");
    this.shadowRoot.getElementById("prefix").value = String(value.prefix || "");
    this.shadowRoot.getElementById("suffix").value = String(value.suffix || "");
    this.shadowRoot.getElementById("template").value = String(value.template || "");

    this.shadowRoot.getElementById("script").textContent = String(spec.script || "");
    this.shadowRoot.getElementById("purpose").textContent = String(spec.purpose || "");
    this.shadowRoot.getElementById("vars").textContent = Array.isArray(spec.variables)
      ? spec.variables.map((v) => String(v.name || "")).filter(Boolean).join(", ")
      : "";
    this.shadowRoot.getElementById("contract").textContent = JSON.stringify(spec.output_contract || {}, null, 2);
    this.shadowRoot.getElementById("default").textContent = String(spec.default_template || "");
    this.shadowRoot.getElementById("effective").textContent = String(spec.effective_template || "");

    const warnings = Array.isArray(spec.warnings) ? spec.warnings : [];
    this.shadowRoot.getElementById("warnings").textContent = warnings.length
      ? `Warnings: ${warnings.join(" | ")}`
      : "";
  }

  getValue() {
    if (!this.shadowRoot) return { prefix: "", suffix: "", template: "" };
    return {
      prefix: String(this.shadowRoot.getElementById("prefix").value || ""),
      suffix: String(this.shadowRoot.getElementById("suffix").value || ""),
      template: String(this.shadowRoot.getElementById("template").value || ""),
    };
  }

  setError(message) {
    if (!this.shadowRoot) return;
    const text = message ? String(message) : "";
    if (!text) {
      this.removeAttribute("invalid");
      this.shadowRoot.getElementById("error").textContent = "";
      return;
    }
    this.setAttribute("invalid", "1");
    this.shadowRoot.getElementById("error").textContent = text;
  }
}

class SettingsField extends HTMLElement {
  constructor() {
    super();
    this._field = null;
    this._value = null;
    this._defaultValue = null;
  }

  connectedCallback() {
    if (this.shadowRoot) return;
    const root = this.attachShadow({ mode: "open" });
    root.innerHTML = `
      <style>
        :host {
          display: block;
          border: 1px solid var(--settings-line, #d7dce5);
          border-radius: 6px;
          padding: 10px;
          background: var(--settings-field-bg, #fbfcfe);
        }
        .field { display: grid; gap: 7px; }
        .label { font-size: 12px; color: var(--settings-text, #1f2937); font-weight: 700; }
        .hint, .meta { font-size: 11px; color: var(--settings-muted, #6b7280); line-height: 1.45; }
        .error { font-size: 11px; color: var(--settings-error, #b42318); display: none; }
        input, textarea {
          width: 100%;
          border: 1px solid var(--settings-line, #d7dce5);
          border-radius: 6px;
          padding: 7px;
          font-size: 12px;
          color: var(--settings-text, #1f2937);
          background: #fff;
          font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace;
        }
        textarea { min-height: 92px; resize: vertical; }
        .switch-row { display: flex; align-items: center; gap: 8px; }
        .switch-row input { width: auto; padding: 0; }
        .rows { display: grid; gap: 6px; }
        .row { display: flex; gap: 6px; align-items: center; }
        .row input { flex: 1; }
        .add, .remove {
          border: 1px solid var(--settings-line, #d7dce5);
          border-radius: 4px;
          padding: 4px 8px;
          background: #fff;
          font-size: 11px;
          cursor: pointer;
        }
        :host([invalid]) { border-color: var(--settings-error, #b42318); }
        :host([invalid]) .error { display: block; }
      </style>
      <article class="field">
        <div class="label" id="label"></div>
        <div class="hint" id="hint"></div>
        <div id="control"></div>
        <div class="meta" id="meta"></div>
        <div class="error" id="error" role="alert" aria-live="polite"></div>
      </article>
    `;

    if (this._field) this.render();
  }

  setField(field, value, defaultValue = null) {
    this._field = field;
    this._value = value;
    this._defaultValue = defaultValue;
    this.render();
  }

  _setControl(node) {
    this.shadowRoot.getElementById("control").replaceChildren(node);
  }

  render() {
    if (!this.shadowRoot || !this._field) return;
    const field = this._field;
    const type = field.type || "string";

    this.shadowRoot.getElementById("label").textContent = field.label || field.path || "Setting";
    this.shadowRoot.getElementById("hint").textContent = field.help || "";

    const bits = [`Type: ${type}`];
    if (typeof field.min === "number") bits.push(`min ${field.min}`);
    if (typeof field.max === "number") bits.push(`max ${field.max}`);
    if (typeof field.step === "number") bits.push(`step ${field.step}`);
    if (this._defaultValue !== null && this._defaultValue !== undefined) {
      bits.push(`default ${JSON.stringify(this._defaultValue)}`);
    }
    this.shadowRoot.getElementById("meta").textContent = bits.join(" | ");

    const value = this._value;

    if (type === "list") {
      const wrap = document.createElement("div");
      wrap.className = "rows";
      const items = Array.isArray(value) ? value : [];
      const addRow = (v = "") => {
        const row = document.createElement("div");
        row.className = "row";
        const input = document.createElement("input");
        input.className = "list-item";
        input.type = "text";
        input.value = String(v);
        const remove = document.createElement("button");
        remove.type = "button";
        remove.className = "remove";
        remove.textContent = "Remove";
        remove.addEventListener("click", () => row.remove());
        row.append(input, remove);
        wrap.appendChild(row);
      };
      items.forEach((item) => addRow(item));
      const add = document.createElement("button");
      add.type = "button";
      add.className = "add";
      add.textContent = "+ Add Item";
      add.addEventListener("click", () => addRow(""));
      const outer = document.createElement("div");
      outer.className = "rows";
      outer.append(wrap, add);
      this._setControl(outer);
      return;
    }

    if (type === "map_integer") {
      const wrap = document.createElement("div");
      wrap.className = "rows";
      const entries = value && typeof value === "object" ? Object.entries(value) : [];
      const addRow = (k = "", v = "") => {
        const row = document.createElement("div");
        row.className = "row";
        const key = document.createElement("input");
        key.className = "map-key";
        key.placeholder = "stage";
        key.value = String(k);
        const val = document.createElement("input");
        val.className = "map-val";
        val.type = "number";
        val.placeholder = "seconds";
        val.value = String(v);
        const remove = document.createElement("button");
        remove.type = "button";
        remove.className = "remove";
        remove.textContent = "Remove";
        remove.addEventListener("click", () => row.remove());
        row.append(key, val, remove);
        wrap.appendChild(row);
      };
      entries.forEach(([k, v]) => addRow(k, v));
      const add = document.createElement("button");
      add.type = "button";
      add.className = "add";
      add.textContent = "+ Add Stage Timeout";
      add.addEventListener("click", () => addRow("", ""));
      const outer = document.createElement("div");
      outer.className = "rows";
      outer.append(wrap, add);
      this._setControl(outer);
      return;
    }

    if (type === "map_list") {
      const wrap = document.createElement("div");
      wrap.className = "rows";
      const entries = value && typeof value === "object" ? Object.entries(value) : [];
      const addRow = (k = "", v = []) => {
        const row = document.createElement("div");
        row.className = "row";
        const key = document.createElement("input");
        key.className = "map-key";
        key.placeholder = "topic slug";
        key.value = String(k);
        const val = document.createElement("input");
        val.className = "map-list";
        val.placeholder = "keyword1, keyword2";
        val.value = Array.isArray(v) ? v.join(", ") : String(v || "");
        const remove = document.createElement("button");
        remove.type = "button";
        remove.className = "remove";
        remove.textContent = "Remove";
        remove.addEventListener("click", () => row.remove());
        row.append(key, val, remove);
        wrap.appendChild(row);
      };
      entries.forEach(([k, v]) => addRow(k, v));
      const add = document.createElement("button");
      add.type = "button";
      add.className = "add";
      add.textContent = "+ Add Topic";
      add.addEventListener("click", () => addRow("", []));
      const outer = document.createElement("div");
      outer.className = "rows";
      outer.append(wrap, add);
      this._setControl(outer);
      return;
    }

    if (type === "boolean") {
      const wrap = document.createElement("label");
      wrap.className = "switch-row";
      const input = document.createElement("input");
      input.id = "input";
      input.type = "checkbox";
      input.checked = Boolean(value);
      const text = document.createElement("span");
      text.textContent = "Enabled";
      text.className = "hint";
      wrap.append(input, text);
      this._setControl(wrap);
      return;
    }

    if (type === "integer" || type === "number") {
      const input = document.createElement("input");
      input.id = "input";
      input.type = "number";
      input.value = value == null ? "" : String(value);
      input.step = field.step != null ? String(field.step) : type === "integer" ? "1" : "0.01";
      if (typeof field.min === "number") input.min = String(field.min);
      if (typeof field.max === "number") input.max = String(field.max);
      this._setControl(input);
      return;
    }

    if (type === "object" || field.multiline) {
      const textarea = document.createElement("textarea");
      textarea.id = "input";
      textarea.value = value == null ? "{}" : typeof value === "string" ? value : JSON.stringify(value, null, 2);
      this._setControl(textarea);
      return;
    }

    const input = document.createElement("input");
    input.id = "input";
    input.type = "text";
    input.value = value == null ? "" : String(value);
    this._setControl(input);
  }

  getValue() {
    if (!this.shadowRoot || !this._field) return null;
    const type = this._field.type || "string";

    if (type === "list") {
      return Array.from(this.shadowRoot.querySelectorAll(".list-item"))
        .map((el) => String(el.value || "").trim())
        .filter(Boolean);
    }

    if (type === "map_integer") {
      const out = {};
      const keys = Array.from(this.shadowRoot.querySelectorAll(".map-key"));
      keys.forEach((kEl) => {
        const row = kEl.parentElement;
        const vEl = row.querySelector(".map-val");
        const key = String(kEl.value || "").trim();
        if (!key) return;
        out[key] = Number.parseInt(String(vEl.value || "0"), 10);
      });
      return out;
    }

    if (type === "map_list") {
      const out = {};
      const keys = Array.from(this.shadowRoot.querySelectorAll(".map-key"));
      keys.forEach((kEl) => {
        const row = kEl.parentElement;
        const vEl = row.querySelector(".map-list");
        const key = String(kEl.value || "").trim();
        if (!key) return;
        out[key] = String(vEl.value || "")
          .split(",")
          .map((v) => v.trim())
          .filter(Boolean);
      });
      return out;
    }

    const input = this.shadowRoot.getElementById("input");
    if (!input) return null;
    if (type === "boolean") return Boolean(input.checked);
    if (type === "integer") {
      const raw = String(input.value || "").trim();
      return raw === "" ? "" : Number.parseInt(raw, 10);
    }
    if (type === "number") {
      const raw = String(input.value || "").trim();
      return raw === "" ? "" : Number.parseFloat(raw);
    }
    if (type === "object") return String(input.value || "");
    return String(input.value || "");
  }

  setError(message) {
    if (!this.shadowRoot) return;
    const errorEl = this.shadowRoot.getElementById("error");
    const text = message ? String(message) : "";
    if (!text) {
      this.removeAttribute("invalid");
      errorEl.textContent = "";
      return;
    }
    this.setAttribute("invalid", "1");
    errorEl.textContent = text;
  }
}

customElements.define("settings-group", SettingsGroup);
customElements.define("settings-field", SettingsField);
customElements.define("settings-model-card", SettingsModelCard);
customElements.define("settings-prompt-editor", SettingsPromptEditor);
