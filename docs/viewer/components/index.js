/**
 * Component Library Index
 *
 * Central export point for all dashboard and settings components.
 *
 * Usage in HTML:
 *   <script type="module" src="/docs/viewer/components/index.js"></script>
 *
 * Or import specific components:
 *   import { DbCard, DbTabs } from '/docs/viewer/components/index.js';
 */

// === Core ===
export { BaseComponent, CollapsibleMixin, ListItemMixin } from './lib/base-component.js';
export { tokens, cardStyles, buttonStyles, formStyles, badgeStyles, kpiStyles, chevronIcon } from './lib/styles.js';

// === Dashboard Components ===
export { DbCard } from './db-card.js';
export { DbKpiStrip, DbKpiItem } from './db-kpi-strip.js';
export { DbTabs, DbTabPanel } from './db-tabs.js';
export { DbDetailPane } from './db-detail-pane.js';

// === Settings Components ===
export { SettingsFieldCard } from './settings-field-card.js';

// === Legacy (to be refactored) ===
// These are the original components, will be deprecated
// export { DbSplitLayout, DbPanel } from './ui-components.js';
// export { SettingsGroup, SettingsField, SettingsModelCard, SettingsPromptEditor } from './settings-components.js';

// === Auto-registration ===
// Uncomment to auto-register all components when this module is imported
// import('./db-card.js');
// import('./db-kpi-strip.js');
// import('./db-tabs.js');
// import('./db-detail-pane.js');
// import('./settings-field-card.js');
