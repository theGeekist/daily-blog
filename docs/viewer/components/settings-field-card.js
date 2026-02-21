/**
 * Settings Field Card Component
 *
 * A collapsible card for individual settings fields.
 * Shows label + current value summary when collapsed, full editor when expanded.
 *
 * Usage:
 *   <settings-field-card
 *     label="Novelty Score Weight"
 *     path="scoring.novelty_score"
 *     type="number"
 *     value="0.3"
 *     default="0.25"
 *     min="0"
 *     max="1"
 *     step="0.05"
 *     help="Controls novelty-based topic filtering">
 *   </settings-field-card>
 *
 * Attributes:
 *   - label: Field label (required)
 *   - path: Field path for API (required)
 *   - type: Field type (string, number, integer, boolean, list, map_integer, map_list, object)
 *   - value: Current value
 *   - default: Default value
 *   - min, max, step: Number field constraints
 *   - help: Help text
 *   - multiline: For string/object types, show textarea
 *
 * Events:
 *   - settings-field-change: Fired when value changes
 *   - settings-field-reset: Fired when reset to default is clicked
 */

import { BaseComponent, CollapsibleMixin } from './lib/base-component.js';
import { tokens, formStyles, cardStyles } from './lib/styles.js';
import { chevronIcon } from './lib/styles.js';

class SettingsFieldCard extends CollapsibleMixin(BaseComponent) {
  static get observedAttributes() {
    return ['label', 'path', 'type', 'value', 'default', 'min', 'max', 'step', 'help', 'multiline', 'error'];
  }

  constructor() {
    super();
    this.state = {
      label: '',
      path: '',
      type: 'string',
      value: null,
      defaultValue: null,
      min: null,
      max: null,
      step: null,
      help: '',
      multiline: false,
      error: '',
    };
  }

  connectedCallback() {
    super.connectedCallback();
    this.#syncAttributes();
  }

  #syncAttributes() {
    this.state.label = this.getAttribute('label') || '';
    this.state.path = this.getAttribute('path') || '';
    this.state.type = this.getAttribute('type') || 'string';
    this.state.value = this.#parseValue(this.getAttribute('value'));
    this.state.defaultValue = this.#parseValue(this.getAttribute('default'));
    this.state.min = this.#parseNumber(this.getAttribute('min'));
    this.state.max = this.#parseNumber(this.getAttribute('max'));
    this.state.step = this.#parseNumber(this.getAttribute('step'));
    this.state.help = this.getAttribute('help') || '';
    this.state.multiline = this.hasAttribute('multiline');
    this.state.error = this.getAttribute('error') || '';
  }

  #parseValue(attr) {
    if (attr == null) return null;
    switch (this.state.type) {
      case 'boolean':
        return attr !== 'false' && attr !== '';
      case 'number':
      case 'integer':
        return Number(attr);
      case 'list':
        return attr ? attr.split(',').map(s => s.trim()).filter(Boolean) : [];
      default:
        return attr;
    }
  }

  #parseNumber(attr) {
    return attr != null ? Number(attr) : null;
  }

  render() {
    this.shadowRoot.innerHTML = `
      <style>
        ${tokens}
        ${cardStyles}
        ${formStyles}

        .db-card-header {
          cursor: pointer;
        }

        .settings-field-card__summary {
          display: flex;
          align-items: center;
          gap: var(--db-space-3);
          font-size: var(--db-text-sm);
          color: var(--db-muted);
        }

        .settings-field-card__summary-label {
          color: var(--db-muted);
        }

        .settings-field-card__summary-value {
          color: var(--db-text);
          font-weight: 600;
        }

        .settings-field-card__summary-value--changed {
          color: var(--db-accent);
        }

        .settings-field-card__meta {
          font-size: var(--db-text-xs);
          color: var(--db-muted);
          margin-top: var(--db-space-2);
        }

        .settings-field-card__editor {
          display: flex;
          flex-direction: column;
          gap: var(--db-space-3);
        }

        .settings-field-card__actions {
          display: flex;
          gap: var(--db-space-2);
          margin-top: var(--db-space-3);
        }

        .settings-field-card__error {
          font-size: var(--db-text-xs);
          color: var(--db-bad);
          margin-top: var(--db-space-2);
          display: none;
        }

        :host([error]) .settings-field-card__error {
          display: block;
        }

        :host([error]) .db-card {
          border-color: var(--db-bad);
        }
      </style>

      <div class="db-card">
        <div class="db-card-header">
          <div class="db-card-title">
            <span class="db-card-title-text"></span>
            <div class="settings-field-card__summary"></div>
          </div>
          <div class="db-card-toggle">${chevronIcon}</div>
        </div>
        <div class="db-card-body">
          <div class="db-card-content">
            <div class="db-card-content-inner">
              <div class="settings-field-card__editor">
                <div class="settings-field-card__input-container"></div>
                <div class="settings-field-card__meta"></div>
                <div class="settings-field-card__error" role="alert"></div>
                <div class="settings-field-card__actions">
                  <button type="button" class="db-button db-button--sm" data-action="reset">Reset to Default</button>
                  <button type="button" class="db-button db-button--primary db-button--sm" data-action="apply">Apply</button>
                </div>
              </div>
            </div>
          </div>
        </div>
      </div>
    `;

    this.#syncAttributes();
    this.#renderSummary();
    this.#renderEditor();
    this.#renderMeta();
  }

  #renderSummary() {
    const titleEl = this.shadowRoot?.querySelector('.db-card-title-text');
    const summaryEl = this.shadowRoot?.querySelector('.settings-field-card__summary');
    if (!titleEl || !summaryEl) return;

    titleEl.textContent = this.state.label;

    // Generate summary based on type
    const summary = this.#generateSummary();
    summaryEl.innerHTML = summary;
  }

  #generateSummary() {
    const value = this.state.value;
    const isChanged = !this.#valuesEqual(value, this.state.defaultValue);

    switch (this.state.type) {
      case 'boolean':
        const boolDisplay = value ? '✓ Enabled' : '✗ Disabled';
        return `<span class="settings-field-card__summary-value${isChanged ? ' settings-field-card__summary-value--changed' : ''}">${boolDisplay}</span>`;

      case 'number':
      case 'integer':
        const rangeStr = (this.state.min != null || this.state.max != null)
          ? ` (range: ${this.state.min ?? '∞'} - ${this.state.max ?? '∞'})`
          : '';
        return `<span class="settings-field-card__summary-label">Current:</span> <span class="settings-field-card__summary-value${isChanged ? ' settings-field-card__summary-value--changed' : ''}">${value ?? '-'}</span>${rangeStr}`;

      case 'list':
        const count = Array.isArray(value) ? value.length : 0;
        return `<span class="settings-field-card__summary-label">Items:</span> <span class="settings-field-card__summary-value${isChanged ? ' settings-field-card__summary-value--changed' : ''}">${count}</span>`;

      case 'map_integer':
      case 'map_list':
        const mapCount = value && typeof value === 'object' ? Object.keys(value).length : 0;
        return `<span class="settings-field-card__summary-label">Entries:</span> <span class="settings-field-card__summary-value${isChanged ? ' settings-field-card__summary-value--changed' : ''}">${mapCount}</span>`;

      default:
        const preview = String(value ?? '');
        const truncated = preview.length > 40 ? preview.slice(0, 37) + '...' : preview;
        return `<span class="settings-field-card__summary-label">Value:</span> <span class="settings-field-card__summary-value${isChanged ? ' settings-field-card__summary-value--changed' : ''}">${truncated || '(empty)'}</span>`;
    }
  }

  #renderEditor() {
    const container = this.shadowRoot?.querySelector('.settings-field-card__input-container');
    if (!container) return;

    const input = this.#createInput();
    container.innerHTML = '';
    container.appendChild(input);
  }

  #createInput() {
    const type = this.state.type;
    const value = this.state.value;

    switch (type) {
      case 'boolean':
        return this.#createCheckboxInput();
      case 'number':
        return this.#createNumberInput();
      case 'integer':
        return this.#createNumberInput({ step: 1 });
      case 'list':
        return this.#createListInput();
      case 'map_integer':
        return this.#createMapIntegerInput();
      case 'map_list':
        return this.#createMapListInput();
      case 'object':
        return this.#createTextareaInput(true);
      default:
        return this.state.multiline
          ? this.#createTextareaInput(false)
          : this.#createTextInput();
    }
  }

  #createTextInput() {
    const input = document.createElement('input');
    input.type = 'text';
    input.className = 'db-input';
    input.value = String(this.state.value ?? '');
    input.addEventListener('input', () => this.#onInputChange(input.value));
    return input;
  }

  #createTextareaInput(isObject) {
    const textarea = document.createElement('textarea');
    textarea.className = 'db-input';
    textarea.rows = 4;
    if (isObject && this.state.value && typeof this.state.value === 'object') {
      textarea.value = JSON.stringify(this.state.value, null, 2);
    } else {
      textarea.value = String(this.state.value ?? '{}');
    }
    textarea.addEventListener('input', () => this.#onInputChange(textarea.value));
    return textarea;
  }

  #createNumberInput(options = {}) {
    const input = document.createElement('input');
    input.type = 'number';
    input.className = 'db-input';
    input.value = this.state.value ?? '';
    input.step = options.step ?? this.state.step ?? (this.state.type === 'integer' ? 1 : 0.01);
    if (this.state.min != null) input.min = String(this.state.min);
    if (this.state.max != null) input.max = String(this.state.max);
    input.addEventListener('input', () => this.#onInputChange(input.value));
    return input;
  }

  #createCheckboxInput() {
    const wrapper = document.createElement('label');
    wrapper.style.display = 'flex';
    wrapper.style.alignItems = 'center';
    wrapper.style.gap = 'var(--db-space-2)';

    const input = document.createElement('input');
    input.type = 'checkbox';
    input.checked = Boolean(this.state.value);
    input.addEventListener('change', () => this.#onInputChange(input.checked));

    const label = document.createElement('span');
    label.textContent = 'Enabled';
    label.style.fontSize = 'var(--db-text-sm)';

    wrapper.appendChild(input);
    wrapper.appendChild(label);
    return wrapper;
  }

  #createListInput() {
    const wrapper = document.createElement('div');
    wrapper.className = 'settings-field-card__list-input';

    const items = Array.isArray(this.state.value) ? [...this.state.value] : [];

    const render = () => {
      wrapper.innerHTML = '';
      items.forEach((item, index) => {
        const row = document.createElement('div');
        row.style.display = 'flex';
        row.style.gap = 'var(--db-space-2)';
        row.style.marginBottom = 'var(--db-space-2)';

        const input = document.createElement('input');
        input.type = 'text';
        input.className = 'db-input';
        input.value = String(item);
        input.addEventListener('input', () => {
          items[index] = input.value;
        });

        const remove = document.createElement('button');
        remove.type = 'button';
        remove.className = 'db-button db-button--sm';
        remove.textContent = '×';
        remove.addEventListener('click', () => {
          items.splice(index, 1);
          this.#onInputChange(items);
          render();
        });

        row.appendChild(input);
        row.appendChild(remove);
        wrapper.appendChild(row);
      });

      const add = document.createElement('button');
      add.type = 'button';
      add.className = 'db-button db-button--sm';
      add.textContent = '+ Add Item';
      add.addEventListener('click', () => {
        items.push('');
        render();
      });

      wrapper.appendChild(add);
    };

    render();
    return wrapper;
  }

  #createMapIntegerInput() {
    const wrapper = document.createElement('div');
    const entries = this.state.value && typeof this.state.value === 'object'
      ? Object.entries(this.state.value)
      : [];

    const render = () => {
      wrapper.innerHTML = '';
      entries.forEach(([key, val], index) => {
        const row = document.createElement('div');
        row.style.display = 'flex';
        row.style.gap = 'var(--db-space-2)';
        row.style.marginBottom = 'var(--db-space-2)';

        const keyInput = document.createElement('input');
        keyInput.type = 'text';
        keyInput.className = 'db-input';
        keyInput.placeholder = 'Key';
        keyInput.value = key;
        keyInput.style.flex = '2';

        const valInput = document.createElement('input');
        valInput.type = 'number';
        valInput.className = 'db-input';
        valInput.placeholder = 'Value';
        valInput.value = val;
        valInput.style.flex = '1';

        const remove = document.createElement('button');
        remove.type = 'button';
        remove.className = 'db-button db-button--sm';
        remove.textContent = '×';
        remove.addEventListener('click', () => {
          entries.splice(index, 1);
          render();
        });

        row.appendChild(keyInput);
        row.appendChild(valInput);
        row.appendChild(remove);
        wrapper.appendChild(row);
      });

      const add = document.createElement('button');
      add.type = 'button';
      add.className = 'db-button db-button--sm';
      add.textContent = '+ Add Entry';
      add.addEventListener('click', () => {
        entries.push(['', 0]);
        render();
      });

      wrapper.appendChild(add);
    };

    render();
    return wrapper;
  }

  #createMapListInput() {
    const wrapper = document.createElement('div');
    const entries = this.state.value && typeof this.state.value === 'object'
      ? Object.entries(this.state.value)
      : [];

    const render = () => {
      wrapper.innerHTML = '';
      entries.forEach(([key, val], index) => {
        const row = document.createElement('div');
        row.style.display = 'flex';
        row.style.gap = 'var(--db-space-2)';
        row.style.marginBottom = 'var(--db-space-2)';

        const keyInput = document.createElement('input');
        keyInput.type = 'text';
        keyInput.className = 'db-input';
        keyInput.placeholder = 'Key';
        keyInput.value = key;
        keyInput.style.flex = '1';

        const valInput = document.createElement('input');
        valInput.type = 'text';
        valInput.className = 'db-input';
        valInput.placeholder = 'Value (comma-separated)';
        valInput.value = Array.isArray(val) ? val.join(', ') : '';
        valInput.style.flex = '2';

        const remove = document.createElement('button');
        remove.type = 'button';
        remove.className = 'db-button db-button--sm';
        remove.textContent = '×';
        remove.addEventListener('click', () => {
          entries.splice(index, 1);
          render();
        });

        row.appendChild(keyInput);
        row.appendChild(valInput);
        row.appendChild(remove);
        wrapper.appendChild(row);
      });

      const add = document.createElement('button');
      add.type = 'button';
      add.className = 'db-button db-button--sm';
      add.textContent = '+ Add Entry';
      add.addEventListener('click', () => {
        entries.push(['', []]);
        render();
      });

      wrapper.appendChild(add);
    };

    render();
    return wrapper;
  }

  #renderMeta() {
    const metaEl = this.shadowRoot?.querySelector('.settings-field-card__meta');
    if (!metaEl) return;

    const parts = [`Type: ${this.state.type}`];
    if (this.state.min != null) parts.push(`min: ${this.state.min}`);
    if (this.state.max != null) parts.push(`max: ${this.state.max}`);
    if (this.state.step != null) parts.push(`step: ${this.state.step}`);
    if (this.state.defaultValue !== null) {
      const defaultStr = this.state.type === 'boolean'
        ? (this.state.defaultValue ? 'true' : 'false')
        : String(this.state.defaultValue);
      parts.push(`default: ${defaultStr}`);
    }

    metaEl.textContent = parts.join(' | ');
  }

  bindEvents() {
    const header = this.shadowRoot?.querySelector('.db-card-header');
    const resetBtn = this.shadowRoot?.querySelector('[data-action="reset"]');
    const applyBtn = this.shadowRoot?.querySelector('[data-action="apply"]');

    header?.addEventListener('click', () => this.toggle());

    resetBtn?.addEventListener('click', () => {
      this.state.value = this.#cloneValue(this.state.defaultValue);
      this.#renderEditor();
      this.#renderSummary();
      this.emit('settings-field-reset', {
        path: this.state.path,
        value: this.state.value,
      });
    });

    applyBtn?.addEventListener('click', () => {
      this.#renderSummary();
      this.emit('settings-field-change', {
        path: this.state.path,
        value: this.state.value,
      });
    });
  }

  #onInputChange(newValue) {
    this.state.value = newValue;
    this.emit('settings-field-input', {
      path: this.state.path,
      value: newValue,
    });
  }

  #valuesEqual(a, b) {
    if (a === b) return true;
    if (a == null || b == null) return false;
    if (typeof a !== typeof b) return false;
    if (typeof a === 'object') {
      return JSON.stringify(a) === JSON.stringify(b);
    }
    return String(a) === String(b);
  }

  #cloneValue(val) {
    if (val == null) return null;
    if (Array.isArray(val)) return [...val];
    if (typeof val === 'object') return { ...val };
    return val;
  }

  onAttributeChange(name, oldValue, newValue) {
    this.#syncAttributes();
    this.#renderSummary();
    this.#renderMeta();
  }

  /**
   * Public API: Get the current value
   */
  getValue() {
    return this.state.value;
  }

  /**
   * Public API: Set the value programmatically
   */
  setValue(value) {
    this.state.value = value;
    this.setAttribute('value', String(value ?? ''));
    this.#renderSummary();
    this.#renderEditor();
  }

  /**
   * Public API: Set an error message
   */
  setError(message) {
    if (message) {
      this.setAttribute('error', message);
      const errorEl = this.shadowRoot?.querySelector('.settings-field-card__error');
      if (errorEl) errorEl.textContent = message;
    } else {
      this.removeAttribute('error');
    }
  }
}

customElements.define('settings-field-card', SettingsFieldCard);

export { SettingsFieldCard };
