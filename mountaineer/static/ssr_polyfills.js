// Ensure global is defined in the V8 runtime environment
var global = typeof global !== 'undefined' ? global : typeof self !== 'undefined' ? self : typeof window !== 'undefined' ? window : {};

// Define MessageChannel directly in the global scope
global.MessageChannel = class MessageChannel {
  constructor() {
    this.port1 = {
      onmessage: null,
      postMessage: (message) => {
        if (this.port2.onmessage) {
          const event = { data: message };
          this.port2.onmessage(event);
        }
      }
    };
    this.port2 = {
      onmessage: null,
      postMessage: (message) => {
        if (this.port1.onmessage) {
          const event = { data: message };
          this.port1.onmessage(event);
        }
      }
    };
  }
};

class TextEncoder {
  /*
   * We provide a stub polyfill of TextEncoder because it's not bundled
   * with the V8 runtime. New versions of ReactDOM Server require this for the
   * require_react_dom_server_browser_development plugin.
   */
  constructor() {}
  encode(str) {
    return str;
  }
}

// React 19 uses Intl.Locale which isn't available in the V8 runtime
Intl.Locale = undefined;

// React 19 may use these additional browser APIs
if (typeof AbortController === 'undefined') {
  global.AbortController = class AbortController {
    constructor() {
      this.signal = { aborted: false };
    }
    abort() {
      this.signal.aborted = true;
    }
  };
}

if (typeof ReadableStream === 'undefined') {
  global.ReadableStream = class ReadableStream {
    constructor() {}
    getReader() {
      return {
        read: () => Promise.resolve({ done: true, value: undefined }),
        releaseLock: () => {}
      };
    }
  };
}

// Create a minimal document object for SSR
if (typeof document === 'undefined') {
  global.document = {
    createElement: () => ({}),
    createTextNode: () => ({}),
    querySelector: () => null,
    querySelectorAll: () => [],
    getElementById: () => null,
    all: undefined
  };
} else {
  // Ensure document.all is properly handled for React 19
  document.all = undefined;
}
