const test = require("node:test"), assert = require("node:assert");
const fs = require("fs"), path = require("path");
const { JSDOM } = require("jsdom");
const A = require("../adapters/claude.js");
const dom = () => new JSDOM(fs.readFileSync(path.join(__dirname, "fixtures/claude_sample.html"), "utf8")).window.document;
test("claude: host match", () => { assert.ok(A.matches("claude.ai")); assert.ok(!A.matches("claude.ai.evil.com")); assert.ok(!A.matches("chatgpt.com")); });
test("claude: turns, ids, answer text without thinking", () => {
  const t = A.turns(dom());
  assert.deepStrictEqual(t.map((x) => x.role + ":" + x.id), ["user:", "assistant:"]);
  assert.strictEqual(t[0].text, "Как зовут проект?"); assert.strictEqual(t[1].text, "Проект Сокол-7.");
});
test("claude: done / streaming via Stop", () => {
  const d = dom(); assert.strictEqual(A.isStreaming(d), false);
  assert.deepStrictEqual(A.diag(d).parts, { stop: false, state: "false", copy: true, done: true });
  d.querySelector("[data-is-streaming]").setAttribute("data-is-streaming", "true"); assert.strictEqual(A.diag(d).parts.done, false);
  d.body.insertAdjacentHTML("beforeend", '<button aria-label="Stop response"></button>');
  assert.strictEqual(A.isStreaming(d), true);
});
test("claude: composer read/write", () => {
  const d = dom(); assert.strictEqual(A.composerText(d), "новый вопрос");
  let n = 0; A.composer(d).addEventListener("input", () => n++);
  A.setComposerText(d, "a\nb"); assert.strictEqual(n, 1); assert.ok(A.composer(d).textContent.includes("b"));
});
test("claude: seal guard text detection", () => {
  const { hasSeal } = require("../seal.js");
  assert.ok(hasSeal("Ответ.\nSKV | #897·715c")); assert.ok(!hasSeal("обычный ответ про SKV"));
});
