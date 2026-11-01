const test = require("node:test"), assert = require("node:assert");
const { badgeFor } = require("../seal.js");
test("revise with unknown id is not 'saved'", () => {
  const b = badgeFor({ verdict: "revise", saved: false, seal: null, invalid_ids: ["remember_A"] });
  assert.match(b.text, /not saved: unknown ev id remember_A/); assert.equal(b.ok, false);
});
test("saved with [VERIFY ?] shows seal + unknown ids", () => {
  const b = badgeFor({ saved: true, seal: "🔐 SKV | #1·ab | [VERIFY ?]", unknown_ids: ["remember_A"] });
  assert.match(b.text, /#1·ab.*unknown ev id: remember_A/); assert.equal(b.ok, false);
});
test("clean seal ok", () => { const b = badgeFor({ saved: true, seal: "S" }); assert.equal(b.text, "S"); assert.equal(b.ok, true); });
test("error", () => { assert.match(badgeFor({ error: "http_401", message: "Invalid API key" }).text, /not saved \(Invalid API key\)/); });
test("saved without seal", () => { assert.equal(badgeFor({ saved: true }).text, "SKV: saved, no seal returned"); });
test("badge: [READ ?] seal is shown but not green", () => {
  const S = require("../seal.js");
  const b = S.badgeFor({ saved: true, verdict: "pass", seal: "🔐 SKV | #2887·1dce | [READ ?] [VERIFY ✓] [CORRECT ✓] [OUTPUT ✓]" });
  assert.strictEqual(b.ok, false); assert.ok(b.text.startsWith("🔐 SKV | #2887·1dce") && b.text.includes("not given"));
});
