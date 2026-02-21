/**
 * Detail Pane Component
 *
 * A collapsible pane for the 4-pane detail view.
 * Shows a one-line summary strip when collapsed, full content when expanded.
 *
 * Usage within db-tabs:
 *   <db-tab-panel name="narrative" label="Narrative">
 *     <db-detail-pane label="Narrative" expanded>
 *       <db-kpi-item label="Who Cares" value="Tech policy makers"></db-kpi-item>
 *       <db-kpi-item label="Problem" value="Regulation pressure"></db-kpi-item>
 *       <div slot="full">
 *         <p>Full narrative content here...</p>
 *       </div>
 *     </db-detail-pane>
 *   </db-tab-panel>
 *
 * Attributes:
 *   - label: Pane label (required)
 *   - expanded: Set to show full content, remove to show summary only
 *   - summary: Optional custom summary text (auto-generated from kpi-items if not provided)
 *
 * Slots:
 *   - default: KPI items and summary content
 *   - full: Full content shown when expanded
 */

import { BaseComponent, CollapsibleMixin } from './lib/base-component.js';
import { tokens, kpiStyles } from './lib/styles.js';
import { chevronIcon } from './lib/styles.js';

class DbDetailPane extends CollapsibleMixin(BaseComponent) {
  static get observedAttributes() {
    return ['label', 'summary', 'expanded'];
  }

  constructor() {
    super();
    this.state = {
      label: '',
      summary: '',
      autoSummary: '',
    };
  }

  connectedCallback() {
    super.connectedCallback();
    this.#syncAttributes();
    this.#generateAutoSummary();
  }

  #syncAttributes() {
    this.state.label = this.getAttribute('label') || 'Pane';
    this.state.summary = this.getAttribute('summary') || '';
  }

  /**
   * Auto-generate summary from kpi-item children
   */
  #generateAutoSummary() {
    const kpiItems = Array.from(this.querySelectorAll(':scope > db-kpi-item'));
    const summaries = kpiItems.map(item => {
      const label = item.getAttribute('label') || '';
      const value = item.getAttribute('value') || '';
      return value ? `${label}: ${value}` : label;
    }).filter(Boolean);

    this.state.autoSummary = summaries.join(' | ');
  }

  render() {
    this.shadowRoot.innerHTML = `
      <style>
        ${tokens}
        ${kpiStyles}

        :host {
          display: block;
        }

        .db-detail-pane {
          border: 1px solid var(--db-line);
          border-radius: var(--db-radius-sm);
          overflow: hidden;
          transition: border-color var(--db-transition-fast);
        }

        .db-detail-pane:hover {
          border-color: #c7d8f5;
        }

        .db-detail-pane--expanded {
          border-color: var(--db-accent);
        }

        /* Summary strip (always visible) */
        .db-detail-pane__summary {
          display: grid;
          grid-template-columns: 1fr auto;
          align-items: start;
          gap: var(--db-space-3);
          padding: var(--db-space-3) var(--db-space-4);
          min-height: 48px;
          cursor: pointer;
          user-select: none;
          transition: background var(--db-transition-fast);
        }

        .db-detail-pane__summary:hover {
          background: #f7fbff;
        }

        .db-detail-pane__summary-content {
          display: flex;
          flex-direction: column;
          gap: var(--db-space-1);
        }

        .db-detail-pane__label {
          font-size: var(--db-text-sm);
          font-weight: 600;
          color: var(--db-text);
        }

        .db-detail-pane__summary-text {
          font-size: var(--db-text-sm);
          color: var(--db-muted);
        }

        .db-detail-pane__toggle {
          display: flex;
          align-items: center;
          justify-content: center;
          width: 24px;
          height: 24px;
          color: var(--db-muted);
          transition: transform var(--db-transition-base);
        }

        .db-detail-pane__toggle svg {
          width: 16px;
          height: 16px;
        }

        /* Expanded state */
        :host([expanded]) .db-detail-pane__toggle {
          transform: rotate(180deg);
        }

        :host([expanded]) .db-detail-pane {
          border-color: var(--db-accent);
        }

        /* Full content (hidden when collapsed) */
        .db-detail-pane__full {
          display: grid;
          grid-template-rows: 0fr;
          transition: grid-template-rows var(--db-transition-base);
        }

        :host([expanded]) .db-detail-pane__full {
          grid-template-rows: 1fr;
        }

        .db-detail-pane__full-inner {
          overflow: hidden;
        }

        .db-detail-pane__content {
          padding: var(--db-space-4);
          background: var(--db-panel);
        }

        /* KPI items in summary */
        .db-detail-pane__kpis {
          display: flex;
          gap: var(--db-space-3);
          flex-wrap: wrap;
          font-size: var(--db-text-sm);
          color: var(--db-muted);
        }

        .db-detail-pane__kpi {
          display: flex;
          gap: var(--db-space-1);
        }

        .db-detail-pane__kpi-label {
          color: var(--db-muted);
        }

        .db-detail-pane__kpi-value {
          color: var(--db-text);
          font-weight: 500;
        }

        /* Slot for light DOM content */
        ::slotted(db-kpi-item) {
          display: inline-flex;
          align-items: center;
          gap: var(--db-space-1);
        }
      </style>

      <div class="db-detail-pane" part="pane">
        <div class="db-detail-pane__summary" part="summary" tabindex="0" role="button" aria-expanded="false">
          <div class="db-detail-pane__summary-content">
            <span class="db-detail-pane__label" part="label"></span>
            <div class="db-detail-pane__kpis" part="kpis">
              <slot></slot>
            </div>
          </div>
          <div class="db-detail-pane__toggle" part="toggle" aria-hidden="true">
            ${chevronIcon}
          </div>
        </div>
        <div class="db-detail-pane__full" part="full-container">
          <div class="db-detail-pane__full-inner">
            <div class="db-detail-pane__content">
              <slot name="full"></slot>
            </div>
          </div>
        </div>
      </div>
    `;

    this.#syncAttributes();
    this.#updateDisplay();
    this.#updateAriaExpanded();
  }

  bindEvents() {
    const summary = this.shadowRoot?.querySelector('.db-detail-pane__summary');
    if (!summary) return;

    // Click to toggle
    summary.addEventListener('click', () => this.toggle());

    // Keyboard support
    summary.addEventListener('keydown', (e) => {
      if (e.key === 'Enter' || e.key === ' ') {
        e.preventDefault();
        this.toggle();
      }
    });

    // Watch for changes to kpi-item children
    const observer = new MutationObserver(() => {
      this.#generateAutoSummary();
      this.#updateDisplay();
    });

    observer.observe(this, {
      childList: true,
      subtree: false,
      characterData: true,
    });
  }

  #updateDisplay() {
    const labelEl = this.shadowRoot?.querySelector('.db-detail-pane__label');
    if (labelEl) {
      labelEl.textContent = this.state.label;
    }
  }

  #updateAriaExpanded() {
    const summary = this.shadowRoot?.querySelector('.db-detail-pane__summary');
    if (summary) {
      summary.setAttribute('aria-expanded', String(this.expanded));
    }
  }

  onExpandedChange(expanded) {
    this.#updateAriaExpanded();

    const pane = this.shadowRoot?.querySelector('.db-detail-pane');
    pane?.classList.toggle('db-detail-pane--expanded', expanded);

    this.emit('db-detail-pane-toggle', {
      expanded,
      pane: this,
      label: this.state.label,
    });
  }

  onAttributeChange(name, oldValue, newValue) {
    switch (name) {
      case 'label':
        this.state.label = newValue || 'Pane';
        this.#updateDisplay();
        break;
      case 'summary':
        this.state.summary = newValue || '';
        break;
    }
  }

  /**
   * Public API: Get the summary text
   */
  getSummary() {
    return this.state.summary || this.state.autoSummary;
  }

  /**
   * Public API: Set the label
   */
  setLabel(text) {
    this.state.label = String(text || 'Pane');
    this.setAttribute('label', this.state.label);
    this.#updateDisplay();
  }

  /**
   * Public API: Check if pane has full content
   */
  hasContent() {
    return this.querySelector('[slot="full"]') !== null;
  }
}

customElements.define('db-detail-pane', DbDetailPane);

export { DbDetailPane };
