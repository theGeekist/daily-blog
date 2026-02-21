/**
 * Unified Card Component
 *
 * A collapsible card component used throughout dashboard and settings.
 * Consistent visual language: title bar + summary strip + expandable content.
 *
 * Usage:
 *   <db-card
 *     title="Run Snapshot"
 *     summary="Run: 20250219T104212Z | Status: ok | Claims: 45"
 *     expanded>
 *     <div slot="content">Full content here</div>
 *   </db-card>
 *
 * Non-expandable (static) variant:
 *   <db-card title="Static Card" non-expandable>
 *     <div slot="content">Always visible content</div>
 *   </db-card>
 *
 * Attributes:
 *   - title: Card title (required)
 *   - summary: One-line summary text (optional)
 *   - expanded: Set to show content, remove to collapse
 *   - non-expandable: Set to disable expand/collapse
 *   - collapsible-group: Group name for single-active accordion behavior
 *
 * Events:
 *   - db-card-expand: Fired when card expands
 *   - db-card-collapse: Fired when card collapses
 *   - db-card-toggle: Fired on any toggle (expand or collapse)
 */

import { BaseComponent, CollapsibleMixin } from './lib/base-component.js';
import { tokens, cardStyles, chevronIcon } from './lib/styles.js';

class DbCard extends CollapsibleMixin(BaseComponent) {
  static get observedAttributes() {
    return ['title', 'summary', 'expanded', 'non-expandable', 'collapsible-group'];
  }

  constructor() {
    super();
    this.state = {
      title: '',
      summary: '',
      nonExpandable: false,
      groupName: null,
    };
  }

  connectedCallback() {
    super.connectedCallback();
    this.#syncAttributes();
  }

  /**
   * Sync HTML attributes to state and DOM
   */
  #syncAttributes() {
    this.state.title = this.getAttribute('title') || 'Untitled';
    this.state.summary = this.getAttribute('summary') || '';
    this.state.nonExpandable = this.hasAttribute('non-expandable');
    this.state.groupName = this.getAttribute('collapsible-group') || null;

    this.#renderTitle();
    this.#renderSummary();
    this.#updateNonExpandable();
  }

  /**
   * Render the component
   */
  render() {
    this.shadowRoot.innerHTML = `
      <style>
        ${tokens}
        ${cardStyles}
      </style>

      <div class="db-card" part="card">
        <div class="db-card-header" part="header" tabindex="${this.state.nonExpandable ? '-1' : '0'}" role="button" aria-expanded="false">
          <div class="db-card-title">
            <span class="db-card-title-text" part="title-text"></span>
            ${this.state.summary ? `<span class="db-card-summary" part="summary"></span>` : ''}
          </div>
          <div class="db-card-toggle" part="toggle" aria-hidden="true">
            ${chevronIcon}
          </div>
        </div>
        <div class="db-card-body" part="body">
          <div class="db-card-content">
            <div class="db-card-content-inner">
              <slot name="content"></slot>
            </div>
          </div>
        </div>
      </div>
    `;

    this.#syncAttributes();
    this.#updateAriaExpanded();
  }

  /**
   * Update the title element
   */
  #renderTitle() {
    const titleEl = this.shadowRoot?.querySelector('.db-card-title-text');
    if (titleEl) {
      titleEl.textContent = this.state.title;
    }
  }

  /**
   * Update the summary element
   */
  #renderSummary() {
    const summaryEl = this.shadowRoot?.querySelector('.db-card-summary');
    if (summaryEl) {
      summaryEl.textContent = this.state.summary;
      summaryEl.hidden = !this.state.summary;
    }
  }

  /**
   * Update non-expandable state
   */
  #updateNonExpandable() {
    const header = this.shadowRoot?.querySelector('.db-card-header');
    const toggle = this.shadowRoot?.querySelector('.db-card-toggle');

    if (this.state.nonExpandable) {
      header?.removeAttribute('role');
      header?.removeAttribute('tabindex');
      header?.classList.add('db-card-header--static');
      toggle?.classList.add('db-card-toggle--hidden');
    } else {
      header?.setAttribute('role', 'button');
      header?.setAttribute('tabindex', '0');
      header?.classList.remove('db-card-header--static');
      toggle?.classList.remove('db-card-toggle--hidden');
    }
  }

  /**
   * Update aria-expanded attribute for accessibility
   */
  #updateAriaExpanded() {
    const header = this.shadowRoot?.querySelector('.db-card-header');
    if (header) {
      header.setAttribute('aria-expanded', String(this.expanded));
    }
  }

  bindEvents() {
    const header = this.shadowRoot?.querySelector('.db-card-header');
    if (!header || this.state.nonExpandable) return;

    // Click to toggle
    header.addEventListener('click', () => this.toggle());

    // Keyboard support
    header.addEventListener('keydown', (e) => {
      if (e.key === 'Enter' || e.key === ' ') {
        e.preventDefault();
        this.toggle();
      }
    });
  }

  /**
   * Handle expanded state change
   */
  onExpandedChange(expanded) {
    this.#updateAriaExpanded();

    // Handle accordion behavior (single-active in group)
    if (expanded && this.state.groupName) {
      this.#collapseSiblings();
    }

    // Emit events
    this.emit('db-card-toggle', { expanded, card: this });
    if (expanded) {
      this.emit('db-card-expand', { card: this });
    } else {
      this.emit('db-card-collapse', { card: this });
    }
  }

  /**
   * Collapse other cards in the same group
   */
  #collapseSiblings() {
    if (!this.state.groupName) return;

    const groupSelector = `db-card[collapsible-group="${this.state.groupName}"]`;
    const siblings = Array.from(document.querySelectorAll(groupSelector));

    siblings.forEach(sibling => {
      if (sibling !== this && sibling.expanded) {
        sibling.expanded = false;
      }
    });
  }

  /**
   * Attribute changed callback
   */
  onAttributeChange(name, oldValue, newValue) {
    switch (name) {
      case 'title':
        this.state.title = newValue || '';
        this.#renderTitle();
        break;
      case 'summary':
        this.state.summary = newValue || '';
        this.#renderSummary();
        break;
      case 'non-expandable':
        this.state.nonExpandable = this.hasAttribute('non-expandable');
        this.#updateNonExpandable();
        break;
      case 'collapsible-group':
        this.state.groupName = newValue || null;
        break;
    }
  }

  /**
   * Public API: Programmatically set summary
   */
  setSummary(text) {
    this.state.summary = String(text || '');
    this.setAttribute('summary', this.state.summary);
    this.#renderSummary();
  }

  /**
   * Public API: Programmatically set title
   */
  setTitle(text) {
    this.state.title = String(text || 'Untitled');
    this.setAttribute('title', this.state.title);
    this.#renderTitle();
  }

  /**
   * Public API: Get the content slot element
   */
  getContentElement() {
    return this.shadowRoot?.querySelector('.db-card-content-inner');
  }
}

// Define the custom element
customElements.define('db-card', DbCard);

// Export for module usage
export { DbCard };
