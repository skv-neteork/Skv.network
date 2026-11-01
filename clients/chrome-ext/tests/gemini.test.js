const test = require("node:test"), assert = require("node:assert");
const fs = require("fs"), path = require("path");
const { JSDOM } = require("jsdom");
const A = require("../adapters/gemini.js");
const dom = () => new JSDOM(fs.readFileSync(path.join(__dirname, "fixtures/gemini_sample.html"), "utf8")).window.document;
test("gemini: host match", () => { assert.ok(A.matches("gemini.google.com")); assert.ok(!A.matches("gemini.google.com.evil.com")); assert.ok(!A.matches("chatgpt.com")); });
test("gemini: turns, ids, answer text without thinking", () => {
  const t = A.turns(dom());
  assert.deepStrictEqual(t.map((x) => x.role + ":" + x.id), ["user:c_r1", "assistant:c_r1"]);
  assert.strictEqual(t[0].text, "Как зовут проект?"); assert.strictEqual(t[1].text, "Проект Сокол-7.");
});
test("gemini: done / streaming via Stop", () => {
  const d = dom(); assert.strictEqual(A.isStreaming(d), false);
  assert.deepStrictEqual(A.diag(d).parts, { stop: false, state: null, copy: true, done: true });
  d.body.insertAdjacentHTML("beforeend", '<button aria-label="Stop response"></button>');
  assert.strictEqual(A.isStreaming(d), true);
});
test("gemini: composer read/write", () => {
  const d = dom(); assert.strictEqual(A.composerText(d), "новый вопрос");
  let n = 0; A.composer(d).addEventListener("input", () => n++);
  A.setComposerText(d, "a\nb"); assert.strictEqual(n, 1); assert.ok(A.composer(d).textContent.includes("b"));
});
test("gemini: user text without screen-reader label and duplicate (live 2026-11-01)", () => {
  const d = new JSDOM('<main><div class="conversation-container" id="c_r2"><user-query><span class="cdk-visually-hidden">Ваш запрос</span><div class="x">What is my test codeword?</div><div class="y">What is my test codeword?</div></user-query>' +
    '<model-response><message-content><div class="markdown"><p>ok</p></div></message-content></model-response></div></main><button class="send-button" aria-label="Send message"></button>').window.document;
  const t = A.turns(d);
  assert.strictEqual(t[0].text, "What is my test codeword?");
  assert.strictEqual(A.cleanUser("Ваш запрос Remember: X.  Remember: X."), "Remember: X.");
  assert.strictEqual(A.cleanUser("hi hi there"), "hi hi there");
  assert.ok(A.sendButton(d));
});
