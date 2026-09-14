// Shared, dependency-free (no jsdom/npm) minimal harness for evaluating
// custom_components/helix_cultivate/www/helix-panel.js in plain Node and
// instantiating its custom elements well enough to call their _render()
// and inspect the resulting shadowRoot.innerHTML as a plain string.
//
// This intentionally does NOT implement real DOM query semantics —
// querySelector/querySelectorAll return inert stub objects (never null,
// so unguarded `el.addEventListener(...)` calls in the source never
// throw) rather than actually finding elements within the assigned
// innerHTML markup. That's sufficient for tests that only need to
// (a) confirm _render() completes without throwing for a given `.data`,
// and (b) inspect the resulting HTML string for presence/absence/order
// of specific markup — which covers what these checks need without
// pulling in a real browser/DOM dependency this project doesn't otherwise
// have (see README's Known Issues: frontend is verified by code review
// and syntax/logic checks, not a browser test suite).
'use strict';

const fs = require('fs');
const path = require('path');
const vm = require('vm');

const PANEL_PATH = path.join(__dirname, '..', '..', 'custom_components', 'helix_cultivate', 'www', 'helix-panel.js');

function makeInertStub() {
  const handler = {
    get(_target, prop) {
      if (prop === Symbol.toPrimitive || prop === 'toString' || prop === 'valueOf') {
        return () => '';
      }
      // Every property access returns a callable, chainable no-op — safe
      // for `.addEventListener(...)`, `.forEach(...)` (never actually
      // called, since querySelectorAll returns a real empty array
      // instead of this stub), `.value`/`.textContent` reads, etc.
      return () => makeInertStub();
    },
    set() { return true; }, // swallow assignments: el.textContent = x, el.disabled = true, ...
  };
  return new Proxy({}, handler);
}

function makeShadowRoot() {
  let html = '';
  return {
    get innerHTML() { return html; },
    set innerHTML(v) { html = v; },
    querySelector: () => makeInertStub(),
    querySelectorAll: () => [],
  };
}

function makeFakeHTMLElement() {
  return class FakeHTMLElement {
    attachShadow() { this.shadowRoot = makeShadowRoot(); return this.shadowRoot; }
    closest() { return null; }
    addEventListener() {}
    removeEventListener() {}
    querySelector() { return makeInertStub(); }
    querySelectorAll() { return []; }
  };
}

/**
 * Evaluates helix-panel.js in a sandboxed context and returns
 * { context, elements } where `elements` maps custom-element tag name
 * (e.g. 'helix-tab-cycle') to its registered class.
 */
function loadPanelModule() {
  const src = fs.readFileSync(PANEL_PATH, 'utf8');
  const elements = {};
  const noopStorage = { getItem: () => null, setItem: () => {}, removeItem: () => {} };
  const context = {
    HTMLElement: makeFakeHTMLElement(),
    customElements: { define: (name, cls) => { elements[name] = cls; } },
    localStorage: noopStorage,
    sessionStorage: noopStorage,
    window: { matchMedia: () => ({ matches: false, addEventListener: () => {} }) },
    document: {
      createElement: () => makeInertStub(),
      addEventListener: () => {},
      head: { appendChild: () => {} },
    },
    console,
  };
  vm.createContext(context);
  new vm.Script(src, { filename: 'helix-panel.js' }).runInContext(context);
  return { context, elements };
}

module.exports = { loadPanelModule, makeInertStub, makeShadowRoot, PANEL_PATH };
