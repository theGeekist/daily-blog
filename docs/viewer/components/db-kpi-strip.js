/**
 * KPI Strip Component
 *
 * Displays key metrics in a horizontal strip format.
 * Used for card summaries where space is limited.
 *
 * Usage:
 *   <db-kpi-strip>
 *     <db-kpi-item label="Run" value="20250219T104212Z"></db-kpi-item>
 *     <db-kpi-item label="Status" value="ok" variant="ok"></db-kpi-item>
 *     <db-kpi-item label="Claims" value="45"></db-kpi-item>
 *   </db-kpi-strip>
 *
 * Or as a card summary:
 *   <db-card summary="">
 *     <db-kpi-strip slot="summary" strip-mode>
 *       <db-kpi-item label="Run" value="20250219T104212Z"></db-kpi-item>
 *       ...
 *     </db-kpi-strip>
 *   </db-card>
 */

import { BaseComponent } from './lib/base-component.js';
import { tokens, kpiStyles } from './lib/styles.js';

class DbKpiStrip extends BaseComponent {
  constructor() {
    super();
    this.state = {
      stripMode: false,
      separator: '|',
    };
  }

  static get observedAttributes() {
    return ['strip-mode', 'separator'];
  }

  connectedCallback() {
    super.connectedCallback();
    this.state.stripMode = this.hasAttribute('strip-mode');
    this.state.separator = this.getAttribute('separator') || '|';
  }

  render() {
    const separatorHtml = this.state.stripMode
      ? `<span class="db-kpi-separator">${this.state.separator}</span>`
      : '';

    this.shadowRoot.innerHTML = `
      <style>
        ${tokens}
        ${kpiStyles}

        :host {
          display: contents;
        }

        .db-kpi-strip {
          display: flex;
          align-items: center;
          gap: var(--db-space-3);
          flex-wrap: wrap;
          font-size: var(--db-text-sm);
          color: var(--db-muted);
        }

        .db-kpi-item {
          display: flex;
          align-items: center;
          gap: var(--db-space-1);
        }

        .db-kpi-item:last-child .db-kpi-separator {
          display: none;
        }

        .db-kpi-label {
          color: var(--db-muted);
        }

        .db-kpi-value {
          color: var(--db-text);
          font-weight: 600;
        }

        .db-kpi-value--ok { color: var(--db-ok); }
        .db-kpi-value--warn { color: var(--db-warn); }
        .db-kpi-value--bad { color: var(--db-bad); }

        .db-kpi-separator {
          color: var(--db-line);
          margin-left: var(--db-space-2);
        }

        ::slotted(db-kpi-item) {
          display: flex;
          align-items: center;
          gap: var(--db-space-1);
        }
      </style>

      <div class="db-kpi-strip" part="strip">
        <slot></slot>
      </div>
    `;
  }

  onAttributeChange(name, oldValue, newValue) {
    if (name === 'separator') {
      this.state.separator = newValue || '|';
      this.render();
    }
  }
}

/**
 * KPI Item Component
 * Individual metric within a KPI strip
 */
class DbKpiItem extends BaseComponent {
  static get observedAttributes() {
    return ['label', 'value', 'variant'];
  }

  constructor() {
    super();
    this.state = {
      label: '',
      value: '',
      variant: '', // 'ok', 'warn', 'bad', or ''
    };
  }

  connectedCallback() {
    super.connectedCallback();
    this.#syncAttributes();
  }

  #syncAttributes() {
    this.state.label = this.getAttribute('label') || '';
    this.state.value = this.getAttribute('value') || '';
    this.state.variant = this.getAttribute('variant') || '';
  }

  render() {
    this.shadowRoot.innerHTML = `
      <style>
        ${tokens}
        ${kpiStyles}

        :host {
          display: inline-flex;
          align-items: center;
          gap: var(--db-space-1);
        }

        .db-kpi-item {
          display: flex;
          align-items: center;
          gap: var(--db-space-1);
        }

        .db-kpi-label {
          color: var(--db-muted);
        }

        .db-kpi-value {
          color: var(--db-text);
          font-weight: 600;
        }

        .db-kpi-value--ok { color: var(--db-ok); }
        .db-kpi-value--warn { color: var(--db-warn); }
        .db-kpi-value--bad { color: var(--db-bad); }
      </style>

      <div class="db-kpi-item" part="item">
        <span class="db-kpi-label" part="label"></span>
        <span class="db-kpi-value" part="value"></span>
      </div>
    `;

    this.#syncAttributes();
  }

  bindEvents() {
    // Watch for attribute changes on light DOM
    const observer = new MutationObserver(() => {
      this.#syncAttributes();
      this.#updateDisplay();
    });

    observer.observe(this, {
      attributes: true,
      attributeFilter: ['label', 'value', 'variant']
    });
  }

  #updateDisplay() {
    const labelEl = this.shadowRoot?.querySelector('.db-kpi-label');
    const valueEl = this.shadowRoot?.querySelector('.db-kpi-value');

    if (labelEl) {
      labelEl.textContent = this.state.label ? `${this.state.label}:` : '';
    }
    if (valueEl) {
      valueEl.textContent = this.state.value;
      valueEl.className = `db-kpi-value db-kpi-value--${this.state.variant || ''}`.trim();
    }
  }

  onAttributeChange(name) {
    this.#syncAttributes();
    this.#updateDisplay();
  }

  /**
   * Public API: Update the value
   */
  setValue(value) {
    this.state.value = String(value ?? '');
    this.setAttribute('value', this.state.value);
    this.#updateDisplay();
  }

  /**
   * Public API: Update the variant
   */
  setVariant(variant) {
    this.state.variant = String(variant || '');
    if (this.state.variant) {
      this.setAttribute('variant', this.state.variant);
    } else {
      this.removeAttribute('variant');
    }
    this.#updateDisplay();
  }
}

customElements.define('db-kpi-strip', DbKpiStrip);
customElements.define('db-kpi-item', DbKpiItem);

export { DbKpiStrip, DbKpiItem };
