const test = require("node:test"), assert = require("node:assert");
const fs = require("fs"), path = require("path");
const { JSDOM } = require("jsdom");
const adapter = require("../adapters/chatgpt.js");
const raw = fs.readFileSync(path.join(__dirname, "fixtures/chatgpt_2026_sample.html"), "utf8");
const dom = () => new JSDOM(raw).window.document;

test("new DOM: turns user then assistant with ids and text", () => {
  const t = adapter.turns(dom());
  assert.deepStrictEqual(t.map((x) => x.role), ["user", "assistant"]);
  assert.strictEqual(t[0].text, "USER TEXT");
  assert.strictEqual(t[1].id, "MSGID");
  assert.ok(t[1].text.startsWith("word"));
  assert.ok(!t[1].text.includes("ChatGPT said"));
});
test("new DOM: lastPair + done when complete, Copy present, no stop", () => {
  const d = dom(), p = adapter.lastPair(d);
  assert.strictEqual(p.user.text, "USER TEXT");
  assert.ok(adapter.isReplyDone(d, p.assistant.el));
  assert.strictEqual(adapter.isStreaming(d), false);
});
test("new DOM: streaming when turn-state not complete", () => {
  const d = dom(); d.querySelector("[data-talvt-turn-state]").setAttribute("data-talvt-turn-state", "streaming");
  assert.strictEqual(adapter.isStreaming(d), true);
});
test("new DOM: streaming when no Copy button", () => {
  const d = dom(); d.querySelector("button[aria-label='Copy']").remove();
  assert.strictEqual(adapter.isStreaming(d), true);
});
test("new DOM: streaming when stop button", () => {
  const d = dom(); d.querySelector("form").insertAdjacentHTML("beforeend", '<button aria-label="Stop streaming"></button>');
  assert.strictEqual(adapter.isStreaming(d), true);
});
test("new DOM: composer is ProseMirror in form; set text fires input", () => {
  const d = dom(), c = adapter.composer(d);
  assert.ok(c.classList.contains("ProseMirror") && c.closest("form[data-chatgpt-composer]"));
  assert.strictEqual(adapter.composerText(d), "");
  let fired = 0; c.addEventListener("input", () => fired++);
  assert.ok(adapter.setComposerText(d, "строка1\nстрока2"));
  assert.strictEqual(fired, 1);
  assert.ok(c.textContent.includes("строка1") && c.textContent.includes("строка2"));
});
test("new DOM: user bubble-only fallback (no unit key)", () => {
  const d = new JSDOM('<div data-turn-key="x"><div data-user-message-bubble="true"><div>hi</div></div><div><h4 data-conversation-role="assistant">ChatGPT said:</h4><div data-markdown-text-style="assistant-message">ok</div></div></div>').window.document;
  const t = adapter.turns(d);
  assert.deepStrictEqual(t.map((x) => x.role), ["user", "assistant"]);
  assert.strictEqual(t[0].text, "hi"); assert.strictEqual(t[1].text, "ok");
});
test("stop via aria-label='Stop' (no data-testid)", () => {
  const d = dom(); d.querySelector("form").insertAdjacentHTML("beforeend", '<button aria-label="Stop"></button>');
  assert.strictEqual(adapter.doneParts(d, adapter.lastPair(d).assistant.el).stop, true);
  assert.strictEqual(adapter.isStreaming(d), true);
});
test("Copy as sibling of assistant block inside the same turn", () => {
  const d = dom(); const bar = d.querySelector("button[aria-label='Copy']").parentElement;
  d.querySelector("[data-talvt-turn-state]").appendChild(bar); // move outside assistant unit
  const p = adapter.lastPair(d);
  assert.strictEqual(p.assistant.el.querySelector("button[aria-label='Copy']"), null);
  assert.strictEqual(adapter.doneParts(d, p.assistant.el).copy, true);
  assert.strictEqual(adapter.isStreaming(d), false);
});
test("user 'Copy message' is not taken as reply Copy", () => {
  const d = dom(); d.querySelector("button[aria-label='Copy']").remove();
  assert.strictEqual(adapter.doneParts(d, adapter.lastPair(d).assistant.el).copy, false);
});
test("diag", () => {
  assert.deepStrictEqual(adapter.diag(dom()), { adapter: "chatgpt", users: 1, assistants: 1, composer: true, parts: { stop: false, state: "complete", copy: true, done: true } });
});
