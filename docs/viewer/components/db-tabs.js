/**
 * Tabs Component
 *
 * Accessible tabbed interface for the 4-pane detail view.
 * Only one pane visible at a time to reduce visual clutter.
 *
 * Usage:
 *   <db-tabs active-tab="narrative">
 *     <db-tab-panel name="narrative" label="Narrative">
 *       <db-kpi-item label="Who Cares" value="Tech policy makers"></db-kpi-item>
 *       <db-kpi-item label="Problem" value="Regulation pressure"></db-kpi-item>
 *     </db-tab-panel>
 *     <db-tab-panel name="claims" label="Claims">
 *       Claims content here
 *     </db-tab-panel>
 *   </db-tabs>
 *
 * Features:
 * - Keyboard navigation (arrow keys, Home/End)
 * - ARIA attributes for accessibility
 * - Programmatic tab switching
 * - Events for tab changes
 */

import { BaseComponent } from './lib/base-component.js';
import { tokens, buttonStyles } from './lib/styles.js';

class DbTabs extends BaseComponent {
  static get observedAttributes() {
    return ['active-tab'];
  }

  constructor() {
    super();
    this.state = {
      activeTab: '',
      tabs: [],
      panels: new Map(),
    };
  }

  async connectedCallback() {
    super.connectedCallback();
    this.state.activeTab = this.getAttribute('active-tab') || '';
    // Wait for tab panels to be defined before discovering them
    await customElements.whenDefined('db-tab-panel');
    // Small delay to ensure panels are upgraded
    await new Promise(resolve => setTimeout(resolve, 0));
    this.#discoverTabs();
  }

  /**
   * Find all tab panels and register them
   */
  #discoverTabs() {
    const panels = Array.from(this.querySelectorAll(':scope > db-tab-panel'));
    this.state.tabs = panels.map(panel => ({
      name: panel.getAttribute('name') || '',
      label: panel.getAttribute('label') || panel.getAttribute('name') || '',
      panel,
    }));

    // Store panel references
    this.state.panels.clear();
    panels.forEach(panel => {
      const name = panel.getAttribute('name');
      if (name) {
        this.state.panels.set(name, panel);
      }
    });

    // Set first tab as active if none specified
    if (!this.state.activeTab && this.state.tabs.length > 0) {
      this.state.activeTab = this.state.tabs[0].name;
    }

    this.#renderTabs();
    this.#updateVisibility();
  }

  render() {
    this.shadowRoot.innerHTML = `
      <style>
        ${tokens}
        ${buttonStyles}

        :host {
          display: block;
          /* Grid was causing alignment issues */
        }

        .db-tabs__list {
          display: flex;
          gap: var(--db-space-2);
          border-bottom: 1px solid var(--db-line);
          overflow-x: auto;
          -webkit-overflow-scrolling: touch;
          /* Fixed height to prevent expansion */
          height: 48px;
          /* Align tabs to top */
          align-items: start;
        }

        .db-tabs__list::-webkit-scrollbar {
          height: 4px;
        }

        .db-tabs__list::-webkit-scrollbar-thumb {
          background: var(--db-line);
          border-radius: var(--db-radius-full);
        }

        .db-tabs__tab {
          flex: 1;
          min-width: max-content;
          padding: var(--db-space-2) var(--db-space-3);
          border: 1px solid transparent;
          border-bottom: 1px solid var(--db-line);
          border-radius: var(--db-radius-sm) var(--db-radius-sm) 0 0;
          background: transparent;
          color: var(--db-muted);
          font-size: var(--db-text-sm);
          font-weight: 500;
          cursor: pointer;
          transition: all var(--db-transition-fast);
          text-align: center;
          /* Ensure consistent height */
          height: 100%;
          /* Center content vertically */
          display: flex;
          align-items: center;
          justify-content: center;
          position: relative;
          z-index: 1;
        }

        .db-tabs__tab:hover {
          color: var(--db-text);
          background: var(--db-bg);
        }

        .db-tabs__tab[aria-selected="true"] {
          color: var(--db-accent);
          background: var(--db-panel);
          border-color: var(--db-line);
          border-bottom-color: var(--db-panel);
          z-index: 2;
        }

        .db-tabs__tab:focus-visible {
          outline: 2px solid var(--db-accent);
          outline-offset: -2px;
        }

        .db-tabs__panel-container {
          position: relative;
          background: var(--db-panel);
          border: 1px solid var(--db-line);
          border-top: none;
          border-radius: 0 0 var(--db-radius-sm) var(--db-radius-sm);
          min-height: 200px;
        }

        .db-tabs__panel {
          display: none;
          padding: var(--db-space-4);
        }

        .db-tabs__panel[aria-hidden="false"] {
          display: block;
        }

        /* Summary view for collapsed panels */
        .db-tabs__summary {
          display: flex;
          gap: var(--db-space-3);
          flex-wrap: wrap;
        }

        .db-tabs__summary-item {
          flex: 1;
          min-width: 140px;
          padding: var(--db-space-3);
          border: 1px solid var(--db-line);
          border-radius: var(--db-radius-sm);
          background: var(--db-panel);
          cursor: pointer;
          transition: border-color var(--db-transition-fast);
        }

        .db-tabs__summary-item:hover {
          border-color: #9cb3d6;
        }

        .db-tabs__summary-item--active {
          border-color: var(--db-accent);
          background: #f7fbff;
        }

        .db-tabs__summary-label {
          font-size: var(--db-text-xs);
          color: var(--db-muted);
          margin-bottom: var(--db-space-1);
        }

        .db-tabs__summary-value {
          font-size: var(--db-text-sm);
          color: var(--db-text);
          font-weight: 500;
        }
      </style>

      <div class="db-tabs__list" role="tablist" part="tablist"></div>
      <div class="db-tabs__panel-container" part="panel-container">
        <slot></slot>
      </div>
    `;

    this.#renderTabs();
  }

  /**
   * Render tab buttons
   */
  #renderTabs() {
    const tabList = this.shadowRoot?.querySelector('.db-tabs__list');
    if (!tabList) return;

    tabList.innerHTML = this.state.tabs.map((tab, index) => `
      <button
        class="db-tabs__tab"
        role="tab"
        aria-selected="${tab.name === this.state.activeTab}"
        aria-controls="panel-${tab.name}"
        id="tab-${tab.name}"
        data-tab="${tab.name}"
        part="tab">
        ${tab.label}
      </button>
    `).join('');

    // Bind click events
    tabList.querySelectorAll('.db-tabs__tab').forEach(tabBtn => {
      tabBtn.addEventListener('click', () => {
        this.activateTab(tabBtn.dataset.tab);
      });

      tabBtn.addEventListener('keydown', (e) => {
        const index = this.state.tabs.findIndex(t => t.name === tabBtn.dataset.tab);
        this.#handleKeyNavigation(e, index);
      });
    });
  }

  /**
   * Handle keyboard navigation
   */
  #handleKeyNavigation(event, currentIndex) {
    const tabs = this.state.tabs;
    let newIndex = currentIndex;

    switch (event.key) {
      case 'ArrowLeft':
        newIndex = currentIndex > 0 ? currentIndex - 1 : tabs.length - 1;
        break;
      case 'ArrowRight':
        newIndex = currentIndex < tabs.length - 1 ? currentIndex + 1 : 0;
        break;
      case 'Home':
        newIndex = 0;
        break;
      case 'End':
        newIndex = tabs.length - 1;
        break;
      default:
        return;
    }

    event.preventDefault();
    this.activateTab(tabs[newIndex].name);

    // Focus the new tab button
    const newTabBtn = this.shadowRoot?.querySelector(`[data-tab="${tabs[newIndex].name}"]`);
    newTabBtn?.focus();
  }

  /**
   * Update panel visibility based on active tab
   */
  #updateVisibility() {
    this.state.panels.forEach((panel, name) => {
      const isActive = name === this.state.activeTab;
      // Panel may not be upgraded yet, check if setActive exists
      if (typeof panel.setActive === 'function') {
        panel.setActive(isActive);
      }
    });

    // Update tab button states
    this.shadowRoot?.querySelectorAll('.db-tabs__tab').forEach(tabBtn => {
      const isSelected = tabBtn.dataset.tab === this.state.activeTab;
      tabBtn.setAttribute('aria-selected', String(isSelected));
    });
  }

  bindEvents() {
    // Watch for dynamically added panels
    const observer = new MutationObserver(() => {
      this.#discoverTabs();
      this.#renderTabs();
    });

    observer.observe(this, {
      childList: true,
      subtree: false,
    });
  }

  /**
   * Activate a specific tab
   * @param {string} tabName - The tab name to activate
   */
  activateTab(tabName) {
    if (!this.state.panels.has(tabName)) return;

    const previousTab = this.state.activeTab;
    this.state.activeTab = tabName;
    this.setAttribute('active-tab', tabName);
    this.#updateVisibility();

    // Auto-expand first detail-pane in the newly active tab
    const activePanel = this.state.panels.get(tabName);
    if (activePanel) {
      // QuerySelector on shadow DOM element only searches shadow DOM
      // Need to search light DOM for slotted elements
      setTimeout(() => {
        const firstDetailPane = activePanel.querySelector('db-detail-pane')
          ?? Array.from(activePanel.children).find(el => el.tagName === 'DB-DETAIL-PANE');
        if (firstDetailPane) {
          firstDetailPane.expanded = true;
        }
      }, 10);
    }

    // Collapse first detail-pane in previous tab (optional UX choice)
    if (previousTab && previousTab !== tabName) {
      const previousPanel = this.state.panels.get(previousTab);
      if (previousPanel) {
        setTimeout(() => {
          const firstDetailPane = previousPanel.querySelector('db-detail-pane')
            ?? Array.from(previousPanel.children).find(el => el.tagName === 'DB-DETAIL-PANE');
          if (firstDetailPane) {
            firstDetailPane.expanded = false;
          }
        }, 10);
      }
    }

    this.emit('db-tabs-change', {
      activeTab: tabName,
      panel: activePanel,
    });
  }

  /**
   * Get the currently active tab name
   */
  getActiveTab() {
    return this.state.activeTab;
  }

  /**
   * Get the active panel element
   */
  getActivePanel() {
    return this.state.panels.get(this.state.activeTab) || null;
  }

  onAttributeChange(name, oldValue, newValue) {
    if (name === 'active-tab' && newValue !== oldValue) {
      this.state.activeTab = newValue || '';
      this.#updateVisibility();
    }
  }
}

/**
 * Tab Panel Component
 * Individual panel within a tabs component
 */
class DbTabPanel extends BaseComponent {
  static get observedAttributes() {
    return ['name', 'label', 'summary', 'active'];
  }

  constructor() {
    super();
    this.state = {
      name: '',
      label: '',
      summary: '',
      active: false,
      tabs: null,
    };
  }

  connectedCallback() {
    super.connectedCallback();
    this.#syncAttributes();
    // Discover parent tabs element
    this.state.tabs = this.parentElement?.closest('db-tabs') || null;
    // Sync active state with parent tabs if available
    if (this.state.tabs) {
      const activeTab = this.state.tabs.getActiveTab();
      const isActive = this.state.name === activeTab;
      this.setActive(isActive);
    }
  }

  #syncAttributes() {
    this.state.name = this.getAttribute('name') || '';
    this.state.label = this.getAttribute('label') || this.state.name;
    this.state.summary = this.getAttribute('summary') || '';
    this.state.active = this.hasAttribute('active');
  }

  render() {
    const id = `panel-${this.state.name}`;

    this.shadowRoot.innerHTML = `
      <style>
        ${tokens}

        :host {
          display: block;
        }

        .db-tab-panel {
          display: none;
        }

        .db-tab-panel[aria-hidden="false"] {
          display: block;
        }

        .db-tab-panel__inner {
          padding: 0;
        }

        /* Detail panes inside tabs - no top margin on first item */
        ::slotted(db-detail-pane:first-child) {
          margin-top: 0;
        }

        ::slotted(db-detail-pane:not(:first-child)) {
          margin-top: var(--db-space-3);
        }

        /* Empty state */
        .db-tab-panel__empty {
          color: var(--db-muted);
          font-size: var(--db-text-sm);
          text-align: center;
          padding: var(--db-space-6);
        }
      </style>

      <div
        class="db-tab-panel"
        id="${id}"
        role="tabpanel"
        aria-labelledby="tab-${this.state.name}"
        aria-hidden="${!this.state.active}"
        part="panel">
        <div class="db-tab-panel__inner">
          <slot></slot>
        </div>
      </div>
    `;

    this.#syncAttributes();
  }

  /**
   * Set the parent tabs component
   */
  setTabs(tabsElement) {
    this.state.tabs = tabsElement;
  }

  /**
   * Set active state (called by parent tabs)
   */
  setActive(active) {
    this.state.active = active;
    const panel = this.shadowRoot?.querySelector('.db-tab-panel');
    if (panel) {
      panel.setAttribute('aria-hidden', String(!active));
    }
    this.setBoolAttribute('active', active);
  }

  /**
   * Set the summary text for when this panel is collapsed
   */
  setSummary(text) {
    this.state.summary = String(text || '');
    this.setAttribute('summary', this.state.summary);
  }

  onAttributeChange(name, oldValue, newValue) {
    this.#syncAttributes();
  }

  /**
   * Get summary data for displaying in collapsed view
   */
  getSummary() {
    return this.state.summary;
  }

  /**
   * Get panel name
   */
  getName() {
    return this.state.name;
  }

  /**
   * Get panel label
   */
  getLabel() {
    return this.state.label;
  }
}

customElements.define('db-tabs', DbTabs);
customElements.define('db-tab-panel', DbTabPanel);

export { DbTabs, DbTabPanel };
