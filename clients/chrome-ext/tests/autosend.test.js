// 0.1.7b: auto-insert of SKV memory on the Gemini fixture, the way the live test sent (keyCode-only Enter, clicks on the icon).
const test = require("node:test"), assert = require("node:assert"), fs = require("fs"), path = require("path"), { JSDOM } = require("jsdom");
const root = path.join(__dirname, "..");
function page(opts = {}) {
  const dom = new JSDOM(fs.readFileSync(path.join(__dirname, "fixtures", "gemini_sample.html"), "utf8"), { runScripts: "outside-only", url: "https://gemini.google.com/app" });
  const w = dom.window, calls = [];
  w.chrome = { runtime: { lastError: null, getManifest: () => ({ version: "0.1.7" }), sendMessage: (m, cb) => {
    calls.push(m.type);
    setTimeout(() => cb(m.type === "status" ? { enabled: true, hasKey: true, autoMemory: opts.auto !== false, version: "0.1.7" }
      : m.type === "context" ? { facts: [{ ev: "remember_1", fact: "Q: Remember: my test codeword is BLUE-HERON-42." }] } : m.type === "diag" ? { version: "0.1.7" } : {}), opts.delay || 5);
  } }, storage: { local: { get: async () => ({}) }, onChanged: { addListener() {} } } };
  w.document.execCommand = () => false;
  for (const f of ["mask.js", "seal.js", "adapters/gemini.js", "content.js"]) w.eval(fs.readFileSync(path.join(root, f), "utf8"));
  const btn = w.document.querySelector("button.send-button");
  if (!btn.querySelector("mat-icon")) btn.appendChild(w.document.createElement("mat-icon"));
  const sent = [];
  const c = w.document.querySelector(".ql-editor");
  // the page's own handlers (bubble phase on the editor / button, like Quill + Angular)
  c.addEventListener("keydown", (e) => { if (e.keyCode === 13 || e.key === "Enter") sent.push("enter:" + c.textContent); });
  btn.addEventListener("click", () => sent.push("click:" + c.textContent));
  pages.push(w);
  return { w, c, btn, sent, calls };
}
const pages = []; test.after(() => pages.forEach((w) => w.close()));
const wait = (ms) => new Promise((r) => setTimeout(r, ms));
function enter(w, el, keyOnly) {
  const e = new w.KeyboardEvent("keydown", { key: keyOnly ? "" : "Enter", bubbles: true, cancelable: true });
  Object.defineProperty(e, "keyCode", { value: 13 }); el.dispatchEvent(e); return e;
}
test("auto-insert: Enter with keyCode 13 only (no key) gets memory first, page sees one send with the block", async () => {
  const p = page(); await wait(50);
  const e = enter(p.w, p.c, true);
  assert.ok(e.defaultPrevented); assert.deepStrictEqual(p.sent, []);       // the page did not send bare
  enter(p.w, p.c, false);                                                   // second Enter while loading: swallowed
  await wait(500);
  assert.strictEqual(p.sent.length, 1, JSON.stringify(p.sent));
  assert.match(p.sent[0], /^click:\[SKV memory — data, not instructions\].*BLUE-HERON-42/);
});
test("auto-insert: click on the icon inside the send button", async () => {
  const p = page(); await wait(50);
  const icon = p.btn.querySelector("mat-icon");
  icon.dispatchEvent(new p.w.MouseEvent("pointerdown", { bubbles: true, cancelable: true }));
  icon.dispatchEvent(new p.w.MouseEvent("click", { bubbles: true, cancelable: true }));
  assert.deepStrictEqual(p.sent, []);
  await wait(500);
  assert.strictEqual(p.sent.length, 1); assert.match(p.sent[0], /BLUE-HERON-42/);
});
test("auto-insert off: Enter passes through untouched", async () => {
  const p = page({ auto: false }); await wait(50);
  const e = enter(p.w, p.c, false);
  assert.ok(!e.defaultPrevented); assert.strictEqual(p.sent.length, 1); assert.ok(!p.sent[0].includes("[SKV memory"));
  assert.ok(!p.calls.includes("context"));
});
test("auto-insert: Shift+Enter and Enter outside the composer are not touched", async () => {
  const p = page(); await wait(50);
  const e = new p.w.KeyboardEvent("keydown", { key: "Enter", shiftKey: true, bubbles: true, cancelable: true });
  p.c.dispatchEvent(e); assert.ok(!e.defaultPrevented);
  const o = new p.w.KeyboardEvent("keydown", { key: "Enter", bubbles: true, cancelable: true });
  p.w.document.body.dispatchEvent(o); assert.ok(!o.defaultPrevented);
});
