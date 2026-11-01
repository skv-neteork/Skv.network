// Service worker: the only place that knows the SKV key and talks to the server.
importScripts("mask.js");
const DEFAULTS = { base: "https://skv.network", enabled: true, key: "", autoMemory: true };
async function cfg() { return Object.assign({}, DEFAULTS, await chrome.storage.local.get(["base", "enabled", "key", "autoMemory"])); }

let lastErr = null, lastOk = null;
// Diagnostic timestamps in the user's zone (Moscow), labelled.
const mskTime = () => new Date().toLocaleTimeString("ru-RU", { timeZone: "Europe/Moscow", hour12: false }) + " MSK";
async function api(path, body) {
  const c = await cfg();
  if (!c.key) return { error: "no_key", message: "Set your SKV key in the extension options." };
  const r = await fetch(c.base.replace(/\/+$/, "") + path, {
    method: body ? "POST" : "GET",
    headers: Object.assign({ Authorization: "Bearer " + c.key }, body ? { "Content-Type": "application/json" } : {}),
    body: body ? JSON.stringify(body) : undefined,
    credentials: "omit"
  });
  let data; try { data = await r.json(); } catch (e) { data = { error: "bad_json" }; }
  if (!r.ok) data = Object.assign({ error: "http_" + r.status }, data);
  lastErr = data.error ? (data.error + (data.message || data.detail ? ": " + String(data.message || data.detail).slice(0, 120) : "")) + " @" + mskTime() : lastErr;
  lastOk = data.error ? lastOk : path + " ok @" + mskTime();
  return data;
}
const m = (s) => self.SKVMask.maskSecrets(String(s || "")).slice(0, 20000);
// Only fields the page needs. The key never goes back to the content script.
function slim(d) {
  return {
    error: d.error || null, message: d.message || d.detail || null,
    verdict: d.verdict || null, seal: d.seal || null, saved: !!d.saved, event_id: d.event_id || null,
    summary_mode: d.summary_mode || null,   // duties/self_check/summary_due are agent-only: not passed to the page
    seal_warning: d.seal_warning || null,
    invalid_ids: (d.invalid_ids || []).slice(0, 5).map(String), unknown_ids: (d.unknown_ids || []).slice(0, 5).map(String),
    profile_errors: d.profile_errors ? true : false,
    facts: (d.facts || []).slice(0, 8).map((f) => ({ ev: f.ev, fact: m(f.fact).slice(0, 300), time: f.time || null }))
  };
}

chrome.runtime.onMessage.addListener((msg, sender, reply) => {
  (async () => {
    const c = await cfg();
    if (msg.type === "diag") return reply({ lastErr, lastOk, enabled: c.enabled, hasKey: !!c.key });
    if (msg.type === "status") return reply({ enabled: c.enabled, hasKey: !!c.key, autoMemory: !!c.autoMemory });
    if (!c.enabled) return reply({ error: "off" });
    if (msg.type === "turn")
      return reply(slim(await api("/api/v7/agent/turn", { user_message: m(msg.user_message), draft: m(msg.draft), source: "guard2_ext:" + (msg.site || "") })));
    if (msg.type === "context")
      return reply(slim(await api("/api/v7/agent/turn", { user_message: m(msg.user_message), query: m(msg.user_message) })));
    if (msg.type === "install") {
      if (msg.user_confirmed !== true) return reply({ error: "consent_required" });
      const d = await api("/api/v7/constitution/install", { user_confirmed: true });
      return reply({ error: d.error || null, message: d.message || d.status || d.detail || "done" });
    }
    reply({ error: "unknown" });
  })().catch((e) => { lastErr = "network: " + String(e && e.message || e) + " @" + mskTime(); reply({ error: "network", message: String(e && e.message || e) }); });
  return true;
});
// 0.1.6: the toolbar button opens popup.html (on/off + status); settings stay in Options.
