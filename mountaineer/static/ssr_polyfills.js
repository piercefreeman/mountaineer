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

Intl.Locale = undefined;
