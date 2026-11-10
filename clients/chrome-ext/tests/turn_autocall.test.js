// 0.1.8 (C3.3): the extension must call `turn` for EVERY finished reply (= every user message), however short,
// even when the page gives no message ids (two identical short replies) and even after a transient error.
const test = require("node:test"), assert = require("node:assert"), fs = require("fs"), path = require("path"), { JSDOM } = require("jsdom");
const root = path.join(__dirname, "..");
const wait = (ms) => new Promise((r) => setTimeout(r, ms));
function page(failFirst) {
  const dom = new JSDOM(fs.readFileSync(path.join(__dirname, "fixtures", "gemini_sample.html"), "utf8"), { runScripts: "outside-only", url: "https://gemini.google.com/app" });
  const w = dom.window, turns = []; let n = 0;
  w.chrome = { runtime: { lastError: null, getManifest: () => ({ version: "0.1.8" }), sendMessage: (m, cb) => {
    if (m.type === "turn") turns.push(m.user_message + "|" + m.draft);
    setTimeout(() => cb(m.type === "status" ? { enabled: true, hasKey: true, autoMemory: false, version: "0.1.8" }
      : m.type === "turn" ? (failFirst && ++n === 1 ? { error: "network", message: "blip" } : { verdict: "ok", saved: true, seal: "🔐 SKV | #1·abcd" })
      : m.type === "diag" ? { version: "0.1.8" } : {}), 2);
  } }, storage: { local: { get: async () => ({}) }, onChanged: { addListener() {} } } };
  w.__fast = true;
  for (const f of ["mask.js", "seal.js", "adapters/gemini.js", "content.js"]) w.eval(fs.readFileSync(path.join(root, f), "utf8"));
  return { w, turns, dom };
}
const pair = (u, a) => '<div class="conversation-container"><user-query><div class="query-text"><p class="query-text-line">' + u + '</p></div></user-query>' +
  '<model-response><div><message-content><div class="markdown"><p>' + a + '</p></div></message-content></div><div class="actions"><copy-button><button aria-label="Copy"></button></copy-button></div></model-response></div>';

test("turn is called for each of two identical short replies on a page without message ids", async () => {
  const p = page(false); await wait(1400);                 // history on the page is marked done
  p.w.document.querySelector("main").insertAdjacentHTML("beforeend", pair("ok?", "Да."));
  await wait(3300);
  p.w.document.querySelector("main").insertAdjacentHTML("beforeend", pair("ok?", "Да."));
  await wait(3300);
  try { assert.deepStrictEqual(p.turns, ["ok?|Да.", "ok?|Да."], JSON.stringify(p.turns)); } finally { p.w.close(); }
});

test("a transient network error on turn is retried, the reply is not lost", async () => {
  const p = page(true); await wait(1400);
  p.w.document.querySelector("main").insertAdjacentHTML("beforeend", pair("hello", "Привет"));
  await wait(7000);
  try { assert.ok(p.turns.length >= 2, JSON.stringify(p.turns)); assert.ok(p.turns.every((t) => t === "hello|Привет")); } finally { p.w.close(); }
});
