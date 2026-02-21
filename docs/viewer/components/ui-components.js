class DbSplitLayout extends HTMLElement {
  connectedCallback() {
    if (this.shadowRoot) return;
    const root = this.attachShadow({ mode: "open" });
    root.innerHTML = `
      <style>
        :host {
          display: block;
          height: var(--layout-height, calc(100vh - 170px));
          min-height: 520px;
        }
        .grid {
          display: grid;
          grid-template-columns: 1.1fr 1.4fr;
          gap: 10px;
          height: 100%;
          padding: 10px;
          min-height: 0;
        }
        .col {
          min-height: 0;
        }
        ::slotted([slot="left"]),
        ::slotted([slot="right"]) {
          display: grid;
          gap: 10px;
          align-content: start;
          min-height: 0;
        }
        @media (max-width: 1100px) {
          :host {
            height: auto;
            min-height: 0;
          }
          .grid {
            grid-template-columns: 1fr;
            height: auto;
          }
          ::slotted([slot="left"]),
          ::slotted([slot="right"]) {
            min-height: 0;
          }
        }
      </style>
      <div class="grid">
        <div class="col"><slot name="left"></slot></div>
        <div class="col"><slot name="right"></slot></div>
      </div>
    `;
  }
}

class DbPanel extends HTMLElement {
  connectedCallback() {
    if (this.shadowRoot) return;
    const heading = this.getAttribute("heading") || "";
    const minHeight = this.getAttribute("min-height") || "320";
    const root = this.attachShadow({ mode: "open" });
    root.innerHTML = `
      <style>
        :host {
          display: block;
          min-height: ${Number(minHeight)}px;
          height: var(--panel-height, auto);
          background: #fff;
          border: 1px solid #d7dce5;
          border-radius: 4px;
          overflow: hidden;
          contain: layout paint;
        }
        .panel {
          display: grid;
          grid-template-rows: auto 1fr;
          height: 100%;
          min-height: 0;
        }
        .head {
          padding: 10px;
          border-bottom: 1px solid #d7dce5;
          font-size: 13px;
          font-weight: 700;
          color: #1f2937;
          background: #fff;
        }
        .body {
          min-height: 0;
          overflow: auto;
          padding: 10px;
        }
      </style>
      <section class="panel">
        ${heading ? `<header class="head">${heading}</header>` : ""}
        <div class="body"><slot></slot></div>
      </section>
    `;
  }
}

customElements.define("db-split-layout", DbSplitLayout);
customElements.define("db-panel", DbPanel);
