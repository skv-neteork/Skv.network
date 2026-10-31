const test = require("node:test"), assert = require("node:assert");
const fs = require("fs"), path = require("path");
const { JSDOM } = require("jsdom");
const adapter = require("../adapters/chatgpt.js");
const { maskSecrets } = require("../mask.js");
const doc = () => new JSDOM(fs.readFileSync(path.join(__dirname, "fixtures/chatgpt_sample.html"), "utf8")).window.document;

test("turns parsed in order with roles", () => {
  const t = adapter.turns(doc());
  assert.deepStrictEqual(t.map((x) => x.role + ":" + x.id), ["user:u1", "assistant:a1", "user:u2", "assistant:a2"]);
  assert.strictEqual(t[1].text, "Запомнил: проект Сокол-7.");
});
test("lastPair = last reply + its user message", () => {
  const p = adapter.lastPair(doc());
  assert.strictEqual(p.user.id, "u2"); assert.strictEqual(p.assistant.id, "a2");
});
test("streaming detection", () => {
  const d = doc(); assert.strictEqual(adapter.isStreaming(d), false);
  d.querySelector("form").insertAdjacentHTML("beforeend", '<button data-testid="stop-button"></button>');
  assert.strictEqual(adapter.isStreaming(d), true);
});
test("composer text", () => assert.strictEqual(adapter.composerText(doc()), "новый вопрос"));
test("host match", () => { assert.ok(adapter.matches("chatgpt.com")); assert.ok(!adapter.matches("evil-chatgpt.com.x")); });
test("masking", () => {
  const s = maskSecrets(adapter.lastPair(doc()).user.text);
  assert.ok(!s.includes("hunter2") && !s.includes("sk_abcdef")); assert.ok(s.includes("[SECRET]"));
  assert.strictEqual(maskSecrets("card 4111 1111 1111 1111 ok"), "card [SECRET]ok");
});
