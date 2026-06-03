// Test the navigation logic in two passes:
//   1. Pure-function test of computeNavState (extracted from app.js).
//   2. DOM-binding smoke test using a minimal hand-rolled DOM mock that
//      actually runs the IIFE in app.js — catches any TypeError and confirms
//      that the bottom-nav buttons + sub-tab strip + a target pane all end
//      up in the right active state after init and after each click.
//
// Run with: node retail/test/nav.test.js
// Exits non-zero on the first failed assertion.

'use strict';
const fs = require("fs");
const path = require("path");

const root = path.resolve(__dirname, "..");
const html = fs.readFileSync(path.join(root, "src/static/index.html"), "utf8");
const js   = fs.readFileSync(path.join(root, "src/static/app.js"), "utf8");

let failed = 0;
function ok(label, cond, extra) {
  if (cond) {
    console.log(`  ✓ ${label}`);
  } else {
    failed++;
    console.log(`  ✗ ${label}${extra ? " — " + extra : ""}`);
  }
}

// ---- Pure-function test of computeNavState ----
console.log("\n[1] computeNavState — pure logic");

// Mirror the TAB_GROUPS definition from app.js. Kept inline rather than
// imported because app.js is an IIFE that runs against a browser DOM.
const TAB_GROUPS = [
  { key: "home",    panes: ["transfers"] },
  { key: "cards",   panes: ["card", "creditcard"] },
  { key: "wealth",  panes: ["savings", "invest", "brokerage"] },
  { key: "borrow",  panes: ["loans", "carloan", "mortgage", "refinance"] },
  { key: "friends", panes: ["invite"] },
];

function computeNavState(groupKey, paneOverride, lastPaneOf) {
  const group = TAB_GROUPS.find(g => g.key === groupKey);
  if (!group) return null;
  const pane = paneOverride && group.panes.indexOf(paneOverride) >= 0
    ? paneOverride
    : (lastPaneOf[groupKey] || group.panes[0]);
  return {
    groupKey, activePane: pane,
    showStrip: group.panes.length > 1, stripPanes: group.panes,
  };
}

let s;
const empty = {};
s = computeNavState("home", null, empty);
ok("home group → transfers pane", s && s.activePane === "transfers");
ok("home group has no sub-strip", s && s.showStrip === false);

s = computeNavState("cards", null, empty);
ok("cards group default → card pane", s && s.activePane === "card");
ok("cards group has strip", s && s.showStrip === true);
ok("cards strip has 2 panes", s && s.stripPanes.length === 2);

s = computeNavState("cards", "creditcard", empty);
ok("cards override → creditcard", s && s.activePane === "creditcard");

s = computeNavState("borrow", null, empty);
ok("borrow group default → loans", s && s.activePane === "loans");
ok("borrow group has 4 panes",     s && s.stripPanes.length === 4);

s = computeNavState("wealth", null, { wealth: "brokerage" });
ok("wealth remembers last pane (brokerage)", s && s.activePane === "brokerage");

s = computeNavState("cards", "savings", empty);
ok("invalid override falls back to default",
   s && s.activePane === "card",
   `got ${s && s.activePane}`);

s = computeNavState("nonexistent", null, empty);
ok("unknown group returns null", s === null);

// ---- HTML structure sanity ----
console.log("\n[2] HTML structure");
ok('has <div class="tabs"></div>',  html.includes('<div class="tabs"></div>'));
ok('has <div id="sub-tabs">',       html.includes('id="sub-tabs"'));
for (const p of ["transfers","card","creditcard","savings","invest","brokerage",
                 "loans","carloan","mortgage","refinance","invite"]) {
  ok(`pane[data-pane="${p}"] exists`, html.includes(`data-pane="${p}"`));
}
ok('transfers is the initially-visible pane',
   /class="tab-pane show" data-pane="transfers"/.test(html));

// ---- JS structure sanity ----
console.log("\n[3] app.js structure");
ok("TAB_GROUPS defined",     js.includes("const TAB_GROUPS = ["));
ok("computeNavState defined",js.includes("function computeNavState"));
ok("applyNavState defined",  js.includes("function applyNavState"));
ok("showPane defined",       js.includes("function showPane"));
ok("showGroup defined",      js.includes("function showGroup"));
ok("init: showGroup('home')",js.includes('showGroup("home")'));
ok("nav build queries .tabs", js.includes('document.querySelector(".tabs")'));
ok("strip element queried by id", js.includes('document.getElementById("sub-tabs")'));
ok("data-group attribute used", js.includes('data-group="${g.key}"'));
ok("dataset.group read",       js.includes("dataset.group"));
ok("dataset.pane read on sub-tabs", js.includes("dataset.pane"));
ok("no orphan TAB_DEFS",       !/\bTAB_DEFS\b/.test(js));
ok("no orphan activateGroup",  !/\bactivateGroup\b/.test(js));
// Pane loaders for every interactive pane
for (const p of ["card","creditcard","savings","invest","brokerage",
                 "mortgage","carloan","refinance","invite"]) {
  ok(`PANE_LOADERS has ${p}`, js.includes(`${p}:`) && new RegExp(`PANE_LOADERS = \\{[\\s\\S]*?\\b${p}:`).test(js));
}

// ---- DOM-binding smoke test against a minimal DOM mock ----
console.log("\n[4] DOM-binding smoke test (mock DOM, runs app.js IIFE)");

// Tiny DOM mock: enough for the navigation paths we care about.
class El {
  constructor(tag, attrs) {
    this.tagName = (tag || "div").toUpperCase();
    this.children = [];
    this.parent = null;
    this.attrs = {};
    this.dataset = {};
    this._listeners = {};
    this._innerHTML = "";
    this.style = {};
    this.classes = new Set();
    this.classList = {
      add:    (...c) => c.forEach(x => this.classes.add(x)),
      remove: (...c) => c.forEach(x => this.classes.delete(x)),
      toggle: (c, on) => { if (on === undefined ? !this.classes.has(c) : on) this.classes.add(c); else this.classes.delete(c); },
      contains: (c) => this.classes.has(c),
    };
    if (attrs) for (const k of Object.keys(attrs)) this.setAttribute(k, attrs[k]);
  }
  setAttribute(name, value) {
    this.attrs[name] = value;
    if (name === "class") {
      this.classes = new Set(String(value).split(/\s+/).filter(Boolean));
    } else if (name === "id") {
      this.id = value;
    } else if (name.startsWith("data-")) {
      const key = name.slice(5).replace(/-([a-z])/g, (_, c) => c.toUpperCase());
      this.dataset[key] = value;
    }
  }
  getAttribute(name) { return this.attrs[name]; }
  get className() { return [...this.classes].join(" "); }
  set className(v) { this.classes = new Set(String(v).split(/\s+/).filter(Boolean)); }
  get textContent() { return this._text || ""; }
  set textContent(v) { this._text = String(v); }
  appendChild(c) { c.parent = this; this.children.push(c); return c; }
  addEventListener(evt, fn) {
    (this._listeners[evt] = this._listeners[evt] || []).push(fn);
  }
  click() { (this._listeners.click || []).forEach(fn => fn({ preventDefault(){} })); }
  set innerHTML(html) {
    this._innerHTML = html;
    this.children = [];
    parseHtml(html).forEach(c => { c.parent = this; this.children.push(c); });
  }
  get innerHTML() { return this._innerHTML; }
  // Traversal helpers
  *walk() {
    yield this;
    for (const c of this.children) yield* c.walk();
  }
  querySelector(sel) {
    for (const el of this.walk()) {
      if (el === this) continue;
      if (matches(el, sel)) return el;
    }
    return null;
  }
  querySelectorAll(sel) {
    const out = [];
    for (const el of this.walk()) {
      if (el === this) continue;
      if (matches(el, sel)) out.push(el);
    }
    return out;
  }
  getElementById(id) {
    for (const el of this.walk()) {
      if (el !== this && el.id === id) return el;
    }
    return null;
  }
}

// Crude tag/attribute matcher supporting `.class`, `#id`, `tag`, `[attr="v"]`,
// descendant combinator (spaces), and compound `.foo.bar`.
function matches(el, sel) {
  const parts = sel.trim().split(/\s+/);
  if (parts.length > 1) {
    // Descendant: rightmost must match, ancestor chain must contain a match for each previous part.
    if (!matchesSimple(el, parts[parts.length - 1])) return false;
    let p = el.parent;
    let i = parts.length - 2;
    while (p && i >= 0) {
      if (matchesSimple(p, parts[i])) i--;
      p = p.parent;
    }
    return i < 0;
  }
  return matchesSimple(el, sel);
}
function matchesSimple(el, sel) {
  // Pull out tag, classes, id, attributes
  let work = sel;
  const attrRe = /\[([a-zA-Z-]+)(?:="([^"]*)")?\]/g;
  const attrs = [];
  work = work.replace(attrRe, (_, name, value) => { attrs.push([name, value]); return ""; });
  let tag = null;
  const classes = [];
  let id = null;
  const tokRe = /([.#]?[A-Za-z][A-Za-z0-9_-]*)/g;
  let m;
  while ((m = tokRe.exec(work))) {
    const tok = m[1];
    if (tok.startsWith(".")) classes.push(tok.slice(1));
    else if (tok.startsWith("#")) id = tok.slice(1);
    else tag = tok;
  }
  if (tag && el.tagName !== tag.toUpperCase()) return false;
  if (id && el.id !== id) return false;
  for (const c of classes) if (!el.classes.has(c)) return false;
  for (const [n, v] of attrs) {
    const got = el.getAttribute(n);
    if (v === undefined ? got === undefined : got !== v) return false;
  }
  return true;
}

// Bare-minimum HTML parser for the snippets app.js sets via innerHTML.
// Supports: <tag attr="v" ...>...</tag> with arbitrary nesting + text nodes.
function parseHtml(src) {
  const root = new El("__frag__");
  const stack = [root];
  let i = 0;
  while (i < src.length) {
    if (src[i] === "<") {
      const close = src.indexOf(">", i);
      if (close < 0) break;
      const tagSrc = src.slice(i + 1, close);
      if (tagSrc.startsWith("/")) {
        stack.pop();
      } else {
        const selfClosing = tagSrc.endsWith("/");
        const inner = selfClosing ? tagSrc.slice(0, -1) : tagSrc;
        const sp = inner.indexOf(" ");
        const name = (sp >= 0 ? inner.slice(0, sp) : inner).trim();
        const rest = sp >= 0 ? inner.slice(sp + 1) : "";
        const el = new El(name);
        // Attribute parser: name="value" or boolean
        const re = /([A-Za-z_:][-A-Za-z0-9_:.]*)(?:="([^"]*)")?/g;
        let am;
        while ((am = re.exec(rest))) el.setAttribute(am[1], am[2] === undefined ? "" : am[2]);
        stack[stack.length - 1].appendChild(el);
        if (!selfClosing && !VOID.has(name.toLowerCase())) stack.push(el);
      }
      i = close + 1;
    } else {
      const next = src.indexOf("<", i);
      const end = next < 0 ? src.length : next;
      const text = src.slice(i, end);
      if (text.trim()) {
        const t = new El("#text");
        t.textContent = text;
        stack[stack.length - 1].appendChild(t);
      }
      i = end;
    }
  }
  return root.children;
}
// Only truly void HTML elements. SVG children like <path>/<rect>/<circle>
// are usually authored as self-closing (parser detects via trailing `/`).
const VOID = new Set(["br","hr","img","input","meta","link"]);

// Build the document by parsing the real index.html body markup so we test
// against the actual structure shipped to customers.
const bodyMatch = html.match(/<body>([\s\S]*?)<\/body>/);
if (!bodyMatch) { console.error("Could not find <body>"); process.exit(2); }
const document = new El("document");
parseHtml(bodyMatch[1]).forEach(c => document.appendChild(c));
// applyLang() writes to documentElement.lang — give it a stub.
document.documentElement = new El("html");

// Window globals expected by app.js
const window = {};
window.crypto = { randomUUID: () => "test-sid-12345678" };
window.fetch = async () => ({ ok: false, json: async () => ({}) });
window.addEventListener = () => {};
const sessionStorage = {
  _: {},
  getItem(k) { return this._[k] || null; },
  setItem(k, v) { this._[k] = String(v); },
};
const navigator = { sendBeacon: () => {}, clipboard: { writeText: async () => {} } };
const localStorage = { getItem: () => null, setItem: () => {} };
const setInterval = () => 0;
const clearInterval = () => {};
const setTimeout = () => {};
const Intl = {
  NumberFormat: function() { return { format: (n) => String(n) }; },
};

// Stub the select element so sel.selectedOptions[0] returns a fake option.
const fakeSel = new El("select", { id: "client-select" });
const fakeOpt = new El("option");
fakeOpt.dataset.balance = "1000"; fakeOpt.dataset.name = "Test"; fakeOpt.value = "c-01000";
fakeSel.selectedOptions = [fakeOpt];
// Replace the real client-select with our fake.
const realSel = document.querySelector("#client-select");
if (realSel) {
  fakeSel.parent = realSel.parent;
  const i = realSel.parent.children.indexOf(realSel);
  realSel.parent.children[i] = fakeSel;
}

// Run app.js inside a Function() with the fakes injected as locals.
const wrapped = `
  with (sandbox) {
    ${js}
  }
`;
const sandbox = {
  document, window, navigator, sessionStorage, localStorage,
  setInterval, clearInterval, setTimeout, Intl,
  fetch: window.fetch, crypto: window.crypto,
  Math, JSON, FormData: function() { return { get: () => "" }; },
  Blob: function() {}, console,
};
let runErr = null;
try {
  new Function("sandbox", wrapped)(sandbox);
} catch (e) {
  runErr = e;
}
ok("app.js IIFE runs without throwing", runErr === null,
   runErr ? `${runErr.message}\n${runErr.stack}` : "");

// After init: home group should be active, transfers pane visible.
const homeBtn = document.querySelector('[data-group="home"]');
ok("bottom nav rendered: home button exists", !!homeBtn);
ok("home button active after init", homeBtn && homeBtn.classes.has("active"));
const transfersPane = document.querySelector('[data-pane="transfers"]');
ok("transfers pane has .show after init", transfersPane && transfersPane.classes.has("show"));
const subTabs = document.querySelector("#sub-tabs");
ok("sub-tabs strip exists",       !!subTabs);
ok("sub-tabs hidden on home",     subTabs && subTabs.style.display === "none");

// Click "cards" → expect card pane visible + sub-tab strip showing Debit/Credit
const cardsBtn = document.querySelector('[data-group="cards"]');
ok("cards button exists", !!cardsBtn);
if (cardsBtn) {
  cardsBtn.click();
  const cardPane = document.querySelector('[data-pane="card"]');
  ok("card pane shown after clicking Cards",
     cardPane && cardPane.classes.has("show"));
  ok("transfers pane hidden after clicking Cards",
     !document.querySelector('[data-pane="transfers"]').classes.has("show"));
  ok("sub-tabs strip visible on cards group",
     subTabs && subTabs.style.display === "flex");
  ok("sub-tab strip has 2 buttons",
     subTabs.querySelectorAll(".sub-tab").length === 2);
  ok("first sub-tab is Debit (data-pane=card)",
     subTabs.querySelectorAll(".sub-tab")[0].getAttribute("data-pane") === "card");
}

// Click the Credit sub-tab → creditcard pane should show
if (cardsBtn) {
  const subTabBtns = subTabs.querySelectorAll(".sub-tab");
  const creditBtn = subTabBtns.find ? subTabBtns.find(b => b.getAttribute("data-pane") === "creditcard")
                                    : subTabBtns[1];
  if (creditBtn) {
    creditBtn.click();
    const ccPane = document.querySelector('[data-pane="creditcard"]');
    ok("creditcard pane shown after sub-tap",
       ccPane && ccPane.classes.has("show"));
    ok("card pane hidden after sub-tap",
       !document.querySelector('[data-pane="card"]').classes.has("show"));
  }
}

// Click "borrow" → loans pane first, strip shows 4 panes
const borrowBtn = document.querySelector('[data-group="borrow"]');
if (borrowBtn) {
  borrowBtn.click();
  const loansPane = document.querySelector('[data-pane="loans"]');
  ok("loans pane shown after clicking Borrow",
     loansPane && loansPane.classes.has("show"));
  ok("borrow strip has 4 panes",
     subTabs.querySelectorAll(".sub-tab").length === 4);
}

// Click "friends" → invite pane, strip hidden
const friendsBtn = document.querySelector('[data-group="friends"]');
if (friendsBtn) {
  friendsBtn.click();
  const invitePane = document.querySelector('[data-pane="invite"]');
  ok("invite pane shown after clicking Friends",
     invitePane && invitePane.classes.has("show"));
  ok("sub-tabs hidden on friends group",
     subTabs && subTabs.style.display === "none");
}

// Return to Cards → strip should restore Credit (lastPaneOf memory)
if (cardsBtn) {
  cardsBtn.click();
  const ccPane = document.querySelector('[data-pane="creditcard"]');
  ok("returning to Cards remembers last sub-pane (creditcard)",
     ccPane && ccPane.classes.has("show"));
}

console.log("\n" + (failed === 0 ? "✓ all checks passed" : `✗ ${failed} check(s) failed`));
process.exit(failed === 0 ? 0 : 1);
