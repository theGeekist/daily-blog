/**
 * Base component class for all custom elements.
 *
 * Provides common patterns:
 * - Attribute reflection (attributes ↔ properties)
 * - Reactive state updates
 * - Event dispatching with type safety
 * - Lifecycle hooks
 * - Shadow DOM helpers
 *
 * Usage:
 *   class MyComponent extends BaseComponent {
 *     static get observedAttributes() {
 *       return ['value', 'disabled'];
 *     }
 *
 *     constructor() {
 *       super();
 *       this.state = { count: 0 };
 *     }
 *
 *     render() {
 *       // Define this.shadowRoot.innerHTML here
 *     }
 *   }
 */
export class BaseComponent extends HTMLElement {
  /**
   * Internal state object. Subclasses should set this in constructor.
   * @type {Object}
   */
  state = {};

  /**
   * Track if component has been initialized (connectedCallback called)
   * @type {boolean}
   */
  #initialized = false;

  /**
   * Track if render has been called at least once
   * @type {boolean}
   */
  #rendered = false;

  /**
   * Cache for DOM lookups to avoid repeated queries
   * @type {Map<string, Element>}
   */
  #domCache = new Map();

  constructor() {
    super();
    // Attach shadow DOM by default (can be overridden in subclass)
    this.attachShadow({ mode: 'open' });
  }

  /**
   * Called when element is added to DOM. Override render() to define content.
   */
  connectedCallback() {
    if (this.#initialized) return;
    this.#initialized = true;
    this.render();
    this.#rendered = true;
    this.#bindEvents();
  }

  /**
   * Called when element is removed from DOM. Cleanup here.
   */
  disconnectedCallback() {
    // Clear DOM cache
    this.#domCache.clear();
  }

  /**
   * Called when observed attributes change. Override attributeChangedCallback
   * in subclass for custom behavior.
   * @param {string} name - Attribute name
   * @param {string} oldValue - Old value
   * @param {string} newValue - New value
   */
  attributeChangedCallback(name, oldValue, newValue) {
    if (!this.#rendered) return;
    if (oldValue === newValue) return;
    this.onAttributeChange(name, oldValue, newValue);
  }

  /**
   * Hook for subclasses to respond to attribute changes.
   * @param {string} name - Attribute name
   * @param {string} oldValue - Old value
   * @param {string} newValue - New value
   */
  onAttributeChange(name, oldValue, newValue) {
    // Override in subclass
  }

  /**
   * Define the component's DOM. Override this in subclasses.
   * Use this.shadowRoot.innerHTML to set content.
   */
  render() {
    // Override in subclass
  }

  /**
   * Bind event listeners. Override this in subclasses.
   * Called after render(), only once.
   */
  #bindEvents() {
    // Override in subclass if needed
    // Note: This is private, override a different method if you need custom binding
    this.bindEvents?.();
  }

  /**
   * Override this method to bind event listeners in your subclass.
   * This is called once after initial render.
   */
  bindEvents() {
    // Override in subclass
  }

  /**
   * Get a cached DOM element by selector or ID.
   * @param {string} key - Cache key or selector
   * @param {string} [selector] - Optional selector if key is not the selector
   * @returns {Element|null}
   */
  $(key, selector) {
    if (!this.shadowRoot) return null;

    if (selector) {
      // Store under key, query using selector
      if (!this.#domCache.has(key)) {
        this.#domCache.set(key, this.shadowRoot.querySelector(selector));
      }
      return this.#domCache.get(key);
    }

    // Key is the selector
    if (!this.#domCache.has(key)) {
      this.#domCache.set(key, this.shadowRoot.querySelector(key));
    }
    return this.#domCache.get(key);
  }

  /**
   * Get multiple elements by selector.
   * @param {string} selector - CSS selector
   * @returns {NodeList}
   */
  $$(selector) {
    return this.shadowRoot?.querySelectorAll(selector) ?? [];
  }

  /**
   * Clear the DOM cache (call after major DOM updates)
   */
  clearCache() {
    this.#domCache.clear();
  }

  /**
   * Update state and trigger re-render if needed.
   * @param {Object} newState - Partial state to merge
   * @param {boolean} [shouldRender=true] - Whether to re-render
   */
  setState(newState, shouldRender = true) {
    const oldState = { ...this.state };
    this.state = { ...this.state, ...newState };
    if (shouldRender) {
      this.update();
    }
    this.onStateChange?.(this.state, oldState);
  }

  /**
   * Hook for subclasses to respond to state changes.
   * @param {Object} newState - New state
   * @param {Object} oldState - Old state
   */
  onStateChange(newState, oldState) {
    // Override in subclass
  }

  /**
   * Update the component's DOM without full re-render.
   * Override this in subclasses for efficient updates.
   */
  update() {
    // Override in subclass for targeted updates
    // Default is to call render() again
    this.render();
  }

  /**
   * Dispatch a custom event from this element.
   * @param {string} type - Event type
   * @param {Object} [detail] - Event detail
   * @param {Object} [options] - Event options (bubbles, cancelable, etc.)
   */
  emit(type, detail = {}, options = {}) {
    const event = new CustomEvent(type, {
      detail,
      bubbles: true,
      cancelable: true,
      composed: true, // Cross shadow DOM boundary
      ...options,
    });
    this.dispatchEvent(event);
  }

  /**
   * Listen to events from child elements.
   * @param {string} selector - CSS selector for target element
   * @param {string} eventType - Event type
   * @param {Function} handler - Event handler
   * @param {Object} [options] - AddEventListener options
   */
  on(selector, eventType, handler, options = {}) {
    if (!this.shadowRoot) return;
    this.shadowRoot.querySelector(selector)?.addEventListener(eventType, handler, options);
  }

  /**
   * Get a boolean attribute value.
   * @param {string} name - Attribute name
   * @returns {boolean}
   */
  getBoolAttribute(name) {
    return this.hasAttribute(name);
  }

  /**
   * Set a boolean attribute value.
   * @param {string} name - Attribute name
   * @param {boolean} value - Value to set
   */
  setBoolAttribute(name, value) {
    if (value) {
      this.setAttribute(name, '');
    } else {
      this.removeAttribute(name);
    }
  }

  /**
   * Reflect a property to an attribute and vice versa.
   * Call this in your property getters/setters.
   * @param {string} name - Property/attribute name
   * @param {*} value - Property value
   * @param {string} [type='string'] - Type conversion ('string', 'number', 'boolean')
   */
  reflectAttribute(name, value, type = 'string') {
    switch (type) {
      case 'boolean':
        this.setBoolAttribute(name, Boolean(value));
        break;
      case 'number':
        this.setAttribute(name, String(Number(value) || 0));
        break;
      default:
        if (value == null) {
          this.removeAttribute(name);
        } else {
          this.setAttribute(name, String(value));
        }
    }
  }

  /**
   * Parse an attribute value to a specific type.
   * @param {string} name - Attribute name
   * @param {*} [defaultValue] - Default value if attribute doesn't exist
   * @param {string} [type='string'] - Type to parse to ('string', 'number', 'boolean')
   * @returns {*}
   */
  parseAttribute(name, defaultValue, type = 'string') {
    if (!this.hasAttribute(name)) return defaultValue;

    const value = this.getAttribute(name);
    switch (type) {
      case 'boolean':
        return true;
      case 'number':
        return Number(value) || 0;
      default:
        return value;
    }
  }

  /**
   * Create a debounced version of a function.
   * @param {Function} fn - Function to debounce
   * @param {number} delay - Delay in ms
   * @returns {Function}
   */
  debounce(fn, delay = 200) {
    let timeoutId;
    return (...args) => {
      clearTimeout(timeoutId);
      timeoutId = setTimeout(() => fn.apply(this, args), delay);
    };
  }

  /**
   * Create a throttled version of a function.
   * @param {Function} fn - Function to throttle
   * @param {number} interval - Interval in ms
   * @returns {Function}
   */
  throttle(fn, interval = 200) {
    let lastTime = 0;
    return (...args) => {
      const now = Date.now();
      if (now - lastTime >= interval) {
        lastTime = now;
        return fn.apply(this, args);
      }
    };
  }

  /**
   * Wait for a condition to be true (polling).
   * @param {Function} condition - Function that returns true when condition is met
   * @param {number} [timeout=5000] - Maximum time to wait
   * @param {number} [interval=50] - Polling interval
   * @returns {Promise<boolean>}
   */
  async waitFor(condition, timeout = 5000, interval = 50) {
    const start = Date.now();
    while (Date.now() - start < timeout) {
      if (condition()) return true;
      await new Promise(resolve => setTimeout(resolve, interval));
    }
    return false;
  }

  /**
   * Log a warning if in development mode.
   * @param {string} message - Warning message
   */
  warn(message) {
    if (this.hasAttribute('debug') || window.location.hostname === 'localhost') {
      console.warn(`[${this.tagName.toLowerCase()}]`, message);
    }
  }

  /**
   * Log an error.
   * @param {string} message - Error message
   * @param {Error} [error] - Optional error object
   */
  error(message, error) {
    console.error(`[${this.tagName.toLowerCase()}]`, message, error || '');
  }
}

/**
 * Mixin for components that need to manage a list of items.
 * Provides add/remove/get/clear methods.
 */
export function ListItemMixin(Base) {
  return class extends Base {
    #items = [];

    get items() {
      return [...this.#items];
    }

    set items(value) {
      this.#items = Array.isArray(value) ? value : [];
      this.onItemsChange?.(this.#items);
    }

    addItem(item) {
      this.#items.push(item);
      this.onItemsChange?.(this.#items);
      return this.#items.length - 1;
    }

    removeItem(index) {
      if (index >= 0 && index < this.#items.length) {
        const removed = this.#items.splice(index, 1)[0];
        this.onItemsChange?.(this.#items);
        return removed;
      }
      return null;
    }

    getItem(index) {
      return this.#items[index] ?? null;
    }

    clearItems() {
      this.#items = [];
      this.onItemsChange?.(this.#items);
    }

    onItemsChange(items) {
      // Override in subclass
    }
  };
}

/**
 * Mixin for components that need collapsible behavior.
 */
export function CollapsibleMixin(Base) {
  return class extends Base {
    static get observedAttributes() {
      return ['expanded', 'collapsed'];
    }

    constructor() {
      super();
      this._expanded = false;
    }

    connectedCallback() {
      super.connectedCallback?.();
      // Check initial expanded state
      this._expanded = this.hasAttribute('expanded');
      this.#updateExpanded();
    }

    attributeChangedCallback(name, oldValue, newValue) {
      super.attributeChangedCallback?.(name, oldValue, newValue);
      if (name === 'expanded' || name === 'collapsed') {
        this._expanded = this.hasAttribute('expanded');
        this.#updateExpanded();
      }
    }

    #updateExpanded() {
      this.toggleClass('expanded', this._expanded);
      this.onExpandedChange?.(this._expanded);
    }

    /**
     * Toggle expanded state.
     */
    toggle() {
      this.expanded = !this.expanded;
    }

    /**
     * Get or set expanded state.
     */
    get expanded() {
      return this._expanded;
    }

    set expanded(value) {
      this._expanded = Boolean(value);
      this.reflectAttribute('expanded', this._expanded, 'boolean');
      this.#updateExpanded();
    }

    /**
     * Add or remove a class.
     */
    toggleClass(className, force) {
      const classList = this.shadowRoot?.querySelector('.db-card')?.classList ?? this.classList;
      if (force === undefined) {
        classList.toggle(className);
      } else if (force) {
        classList.add(className);
      } else {
        classList.remove(className);
      }
    }

    onExpandedChange(expanded) {
      // Override in subclass
    }
  };
}
