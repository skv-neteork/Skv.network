const test = require("node:test"), assert = require("node:assert"), fs = require("fs"), path = require("path");
const { JSDOM } = require("jsdom");
const { maskSecrets } = require("../mask.js");
const root = path.join(__dirname, "..");

test("mask: provider keys and bearer tokens", () => {
  const raw = "a sk_" + "A".repeat(20) + " b pza_" + "b".repeat(20) + " c skint_" + "c".repeat(12) +
    " d xai-" + "d".repeat(20) + " e sk-ant-api03-" + "e".repeat(20) + " f Authorization: Bearer " + "f".repeat(30) +
    " g AIza" + "g".repeat(35) + " h password=hunter2xyz";
  const out = maskSecrets(raw);
  for (const leak of ["AAAAAAAA", "bbbbbbbb", "cccccccc", "dddddddd", "eeeeeeee", "ffffffff", "gggggggg", "hunter2"]) assert.ok(!out.includes(leak), leak + " leaked: " + out);
  assert.match(out, /Bearer \[SECRET\]/);
});
test("mask: ordinary text untouched", () => {
  const t = "Meeting at 18:43 MSK, task-board item T_EXT015, see skv.network docs";
  assert.equal(maskSecrets(t), t);
});
test("manifest 0.1.7: popup, minimal permissions", () => {
  const m = JSON.parse(fs.readFileSync(path.join(root, "manifest.json"), "utf8"));
  assert.equal(m.version, "0.1.7");
  assert.equal(m.action.default_popup, "popup.html");
  assert.deepEqual(m.permissions, ["storage"]);
  assert.deepEqual(m.host_permissions, ["https://skv.network/*"]);
});
function popupDom(state) {
  const dom = new JSDOM(fs.readFileSync(path.join(root, "popup.html"), "utf8").replace(/<script[^>]*><\/script>/, ""), { runScripts: "outside-only" });
  const w = dom.window;
  w.chrome = {
    runtime: { lastError: null, sendMessage: (msg, cb) => cb({ enabled: state.enabled, hasKey: state.hasKey, lastOk: null, lastErr: null }), openOptionsPage: () => (state.opened = true) },
    storage: { local: { set: async (o) => Object.assign(state, o) } }
  };
  w.eval(fs.readFileSync(path.join(root, "popup.js"), "utf8"));
  return w;
}
test("popup: shows ON and key set, never the key", () => {
  const w = popupDom({ enabled: true, hasKey: true });
  assert.equal(w.document.getElementById("enabled").checked, true);
  assert.match(w.document.getElementById("state").textContent, /ON/);
  assert.equal(w.document.getElementById("key").textContent, "set");
  assert.ok(!/sk_/.test(w.document.body.textContent));
});
test("popup: toggle off writes enabled=false and shows OFF", async () => {
  const st = { enabled: true, hasKey: false };
  const w = popupDom(st);
  const cb = w.document.getElementById("enabled");
  cb.checked = false; cb.dispatchEvent(new w.Event("change"));
  await new Promise((r) => setTimeout(r, 10));
  assert.equal(st.enabled, false);
  assert.match(w.document.getElementById("state").textContent, /OFF/);
  assert.match(w.document.getElementById("key").textContent, /not set/);
});
test("content: listens to on/off changes and never reads the key", () => {
  const c = fs.readFileSync(path.join(root, "content.js"), "utf8");
  assert.match(c, /storage\.onChanged/);
  assert.ok(!/storage\.local\.get\(\[[^\]]*key/.test(c));
});
test("background: off blocks turn/context before any network call", () => {
  const b = fs.readFileSync(path.join(root, "background.js"), "utf8");
  const off = b.indexOf('if (!c.enabled) return reply({ error: "off" })'), turn = b.indexOf('msg.type === "turn"');
  assert.ok(off > 0 && off < turn);
});
