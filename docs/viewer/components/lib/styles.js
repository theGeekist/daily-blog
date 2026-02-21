/**
 * Shared styles library for dashboard and settings components.
 *
 * Design principles:
 * - Single source of truth for all visual tokens
 * - Component styles import from here, reducing duplication
 * - Easy to theme by modifying :root tokens
 *
 * Usage in web components:
 *   import { tokens, cardStyles, buttonStyles } from './lib/styles.js';
 *   root.innerHTML = `<style>${tokens}${cardStyles}</style>...`;
 */

/**
 * CSS Custom Properties (Design Tokens)
 * Define once, use everywhere. These align with the existing :root variables
 * in dashboard.html and settings.html to maintain visual consistency.
 */
export const tokens = `
  :host {
    /* Colors - semantic */
    --db-bg: #f5f7fa;
    --db-panel: #ffffff;
    --db-line: #d7dce5;
    --db-text: #1f2937;
    --db-muted: #6b7280;
    --db-accent: #0e60c8;
    --db-ok: #0f8a4b;
    --db-warn: #b15f00;
    --db-bad: #b42318;

    /* Colors - derived */
    --db-ok-bg: #f1fbf5;
    --db-warn-bg: #fff6eb;
    --db-bad-bg: #fff1f1;
    --db-ok-border: #b7e3cc;
    --db-warn-border: #f3d3ad;
    --db-bad-border: #f3b7b2;
    --db-field-bg: #fbfcfe;

    /* Spacing - 4px base unit scale */
    --db-space-1: 4px;
    --db-space-2: 8px;
    --db-space-3: 12px;
    --db-space-4: 16px;
    --db-space-5: 20px;
    --db-space-6: 24px;

    /* Typography */
    --db-font-sans: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
    --db-font-mono: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace;

    /* Font sizes */
    --db-text-xs: 11px;
    --db-text-sm: 12px;
    --db-text-base: 13px;
    --db-text-lg: 14px;
    --db-text-xl: 18px;

    /* Borders */
    --db-radius-sm: 4px;
    --db-radius-md: 6px;
    --db-radius-lg: 8px;
    --db-radius-full: 9999px;

    /* Shadows */
    --db-shadow-sm: 0 1px 2px rgba(0, 0, 0, 0.05);
    --db-shadow-md: 0 2px 4px rgba(0, 0, 0, 0.08);
    --db-shadow-lg: 0 4px 8px rgba(0, 0, 0, 0.1);

    /* Transitions */
    --db-transition-fast: 150ms ease;
    --db-transition-base: 200ms ease;
    --db-transition-slow: 300ms ease;

    /* Z-index scale */
    --db-z-dropdown: 100;
    --db-z-modal: 200;
    --db-z-toast: 300;
  }
`;

/**
 * Card pattern - used for all collapsible/expandable sections
 * Consistent collapsed height and expanded behavior
 */
export const cardStyles = `
  .db-card {
    background: var(--db-panel);
    border: 1px solid var(--db-line);
    border-radius: var(--db-radius-md);
    overflow: hidden;
    transition: border-color var(--db-transition-fast);
  }

  .db-card:hover {
    border-color: #c7d8f5;
  }

  /* Card header - always visible, shows title + summary */
  .db-card-header {
    display: grid;
    grid-template-columns: 1fr auto;
    align-items: center;
    gap: var(--db-space-3);
    padding: var(--db-space-3) var(--db-space-4);
    min-height: 48px;
    cursor: pointer;
    user-select: none;
  }

  .db-card-header:hover {
    background: #f7fbff;
  }

  .db-card-title {
    display: flex;
    flex-direction: column;
    gap: var(--db-space-1);
  }

  .db-card-title-text {
    font-size: var(--db-text-base);
    font-weight: 600;
    color: var(--db-text);
  }

  .db-card-summary {
    font-size: var(--db-text-sm);
    color: var(--db-muted);
    line-height: 1.4;
  }

  /* Expand/collapse indicator */
  .db-card-toggle {
    display: flex;
    align-items: center;
    justify-content: center;
    width: 24px;
    height: 24px;
    color: var(--db-muted);
    transition: transform var(--db-transition-base);
  }

  .db-card-toggle svg {
    width: 16px;
    height: 16px;
  }

  /* Expanded state: rotate chevron */
  :host([expanded]) .db-card-toggle {
    transform: rotate(180deg);
  }

  /* Card body - hidden when collapsed, revealed when expanded */
  .db-card-body {
    display: grid;
    grid-template-rows: 0fr;
    transition: grid-template-rows var(--db-transition-base);
  }

  :host([expanded]) .db-card-body {
    grid-template-rows: 1fr;
  }

  .db-card-content {
    overflow: hidden;
  }

  .db-card-content-inner {
    padding: var(--db-space-4);
    border-top: 1px solid var(--db-line);
  }

  /* When not expandable, remove toggle cursor */
  :host([non-expandable]) .db-card-header {
    cursor: default;
  }

  :host([non-expandable]) .db-card-toggle {
    display: none;
  }
`;

/**
 * Button styles - consistent across all components
 */
export const buttonStyles = `
  .db-button {
    display: inline-flex;
    align-items: center;
    justify-content: center;
    gap: var(--db-space-2);
    border: 1px solid var(--db-line);
    border-radius: var(--db-radius-sm);
    background: var(--db-panel);
    color: var(--db-text);
    font-size: var(--db-text-sm);
    font-family: var(--db-font-sans);
    padding: var(--db-space-2) var(--db-space-3);
    cursor: pointer;
    transition: all var(--db-transition-fast);
    white-space: nowrap;
  }

  .db-button:hover:not(:disabled) {
    border-color: #9cb3d6;
    background: #f7fbff;
  }

  .db-button:active:not(:disabled) {
    transform: translateY(1px);
  }

  .db-button:disabled {
    opacity: 0.5;
    cursor: not-allowed;
  }

  /* Button variants */
  .db-button--primary {
    background: var(--db-accent);
    color: #fff;
    border-color: var(--db-accent);
  }

  .db-button--primary:hover:not(:disabled) {
    background: #0b52b0;
  }

  .db-button--ghost {
    border-color: transparent;
    background: transparent;
  }

  .db-button--ghost:hover:not(:disabled) {
    background: #f7fbff;
    border-color: var(--db-line);
  }

  .db-button--sm {
    padding: var(--db-space-1) var(--db-space-2);
    font-size: var(--db-text-xs);
  }

  .db-button--lg {
    padding: var(--db-space-3) var(--db-space-4);
    font-size: var(--db-text-base);
  }
`;

/**
 * Form input styles - for settings fields
 */
export const formStyles = `
  .db-input {
    width: 100%;
    border: 1px solid var(--db-line);
    border-radius: var(--db-radius-sm);
    padding: var(--db-space-2) var(--db-space-3);
    font-size: var(--db-text-sm);
    font-family: var(--db-font-mono);
    color: var(--db-text);
    background: var(--db-panel);
    transition: border-color var(--db-transition-fast), box-shadow var(--db-transition-fast);
  }

  .db-input:focus {
    outline: none;
    border-color: var(--db-accent);
    box-shadow: 0 0 0 2px rgba(14, 96, 200, 0.1);
  }

  .db-input::placeholder {
    color: var(--db-muted);
  }

  .db-input:disabled {
    background: var(--db-bg);
    cursor: not-allowed;
  }

  .db-label {
    display: block;
    font-size: var(--db-text-sm);
    font-weight: 600;
    color: var(--db-text);
    margin-bottom: var(--db-space-1);
  }

  .db-hint {
    font-size: var(--db-text-xs);
    color: var(--db-muted);
    margin-top: var(--db-space-1);
  }

  .db-error {
    font-size: var(--db-text-xs);
    color: var(--db-bad);
    margin-top: var(--db-space-1);
    display: none;
  }

  .db-field--invalid .db-error {
    display: block;
  }

  .db-field--invalid .db-input {
    border-color: var(--db-bad);
  }
`;

/**
 * Status badge styles
 */
export const badgeStyles = `
  .db-badge {
    display: inline-flex;
    align-items: center;
    padding: 2px var(--db-space-2);
    border: 1px solid var(--db-line);
    border-radius: var(--db-radius-full);
    font-size: var(--db-text-xs);
    white-space: nowrap;
  }

  .db-badge--ok {
    color: var(--db-ok);
    border-color: var(--db-ok-border);
    background: var(--db-ok-bg);
  }

  .db-badge--warn {
    color: var(--db-warn);
    border-color: var(--db-warn-border);
    background: var(--db-warn-bg);
  }

  .db-badge--bad {
    color: var(--db-bad);
    border-color: var(--db-bad-border);
    background: var(--db-bad-bg);
  }
`;

/**
 * KPI strip styles - for one-line metric summaries
 */
export const kpiStyles = `
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
`;

/**
 * Utility class generator functions
 * These return CSS strings for common patterns
 */

/**
 * Generates CSS for a visually hidden element (screen-reader only)
 */
export function visuallyHidden() {
  return `
    .visually-hidden {
      position: absolute;
      width: 1px;
      height: 1px;
      padding: 0;
      margin: -1px;
      overflow: hidden;
      clip: rect(0, 0, 0, 0);
      white-space: nowrap;
      border: 0;
    }
  `;
}

/**
 * Generates CSS for focus-visible styles (keyboard focus only)
 */
export function focusVisible() {
  return `
    *:focus-visible {
      outline: 2px solid var(--db-accent);
      outline-offset: 2px;
    }
  `;
}

/**
 * Generates CSS for scrollable containers
 */
export function scrollableStyles() {
  return `
  .scrollable {
    overflow: auto;
    -webkit-overflow-scrolling: touch;
  }

  .scrollable::-webkit-scrollbar {
    width: 8px;
    height: 8px;
  }

  .scrollable::-webkit-scrollbar-track {
    background: var(--db-bg);
  }

  .scrollable::-webkit-scrollbar-thumb {
    background: var(--db-line);
    border-radius: var(--db-radius-full);
  }

  .scrollable::-webkit-scrollbar-thumb:hover {
    background: var(--db-muted);
  }
`;
}

/**
 * Chevron icon SVG - used across components
 */
export const chevronIcon = `
  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
    <polyline points="6 9 12 15 18 9"></polyline>
  </svg>
`;

/**
 * Combined stylesheet for components that need everything
 */
export const sharedStyles = `
  ${tokens}
  ${cardStyles}
  ${buttonStyles}
  ${formStyles}
  ${badgeStyles}
  ${kpiStyles}
  ${visuallyHidden()}
  ${focusVisible()}
  ${scrollableStyles()}
`;
