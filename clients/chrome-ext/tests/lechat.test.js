const test = require("node:test"), assert = require("node:assert");
const fs = require("fs"), path = require("path");
const { JSDOM } = require("jsdom");
const A = require("../adapters/lechat.js");
const dom = () => new JSDOM(fs.readFileSync(path.join(__dirname, "fixtures/lechat_sample.html"), "utf8")).window.document;
test("lechat: host match", () => { assert.ok(A.matches("chat.mistral.ai")); assert.ok(!A.matches("chat.mistral.ai.evil.com")); assert.ok(!A.matches("chatgpt.com")); });
test("lechat: turns, ids, answer text without thinking", () => {
  const t = A.turns(dom());
  assert.deepStrictEqual(t.map((x) => x.role + ":" + x.id), ["user:m1", "assistant:m2"]);
  assert.strictEqual(t[0].text, "Как зовут проект?"); assert.strictEqual(t[1].text, "Проект Сокол-7.");
});
test("lechat: done / streaming via Stop", () => {
  const d = dom(); assert.strictEqual(A.isStreaming(d), false);
  assert.deepStrictEqual(A.diag(d).parts, { stop: false, state: null, copy: true, done: true });
  d.querySelector("form").insertAdjacentHTML("beforeend", '<button aria-label="Stop"></button>');
  assert.strictEqual(A.isStreaming(d), true);
});
test("lechat: composer read/write", () => {
  const d = dom(); assert.strictEqual(A.composerText(d), "новый вопрос");
  let n = 0; A.composer(d).addEventListener("input", () => n++);
  A.setComposerText(d, "a\nb"); assert.strictEqual(n, 1); assert.ok(A.composer(d).textContent.includes("b"));
});
