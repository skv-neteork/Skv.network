// Generic engine: picks the site adapter, watches for finished replies, shows seal badge + panel.
(function () {
  const A = (self.SKVAdapters || []).find((a) => a.matches(location.hostname));
  if (!A) return;
  const done = new Set();       // assistant message keys already sent
  let lastText = "", stableSince = 0, timer = null;
  const send = (msg) => new Promise((res) => {
    try { chrome.runtime.sendMessage(msg, (r) => { const le = chrome.runtime.lastError; res(r || { error: "no_reply", message: le ? le.message : null }); }); }
    catch (e) { res({ error: "ext_context", message: String(e.message || e) }); }   // e.g. extension reloaded: refresh the tab
  });
  const keyOf = (p) => p.assistant.id || ("h" + p.assistant.text.length + ":" + p.assistant.text.slice(0, 40));

  // ---- UI (shadow DOM; never contains the key) ----
  const host = document.createElement("div");
  host.id = "skv-guard2";
  host.style.cssText = "position:fixed;right:12px;bottom:90px;z-index:2147483646";
  const sh = host.attachShadow({ mode: "closed" });
  sh.innerHTML = `<style>
   .p{font:12px system-ui;background:#111c;color:#eee;border-radius:8px;padding:8px;max-width:300px;box-shadow:0 2px 8px #0006}
   .p b{color:#9cf} button{font:11px system-ui;margin:4px 4px 0 0;cursor:pointer} .s{white-space:pre-wrap;max-height:160px;overflow:auto;margin-top:4px}
   .min .s,.min .bt{display:none}</style>
   <div class="p" id="p"><b id="h">SKV Guard 2</b> <button id="mn">–</button>
   <div class="s" id="st">waiting…</div>
   <details class="bt" style="margin-top:4px"><summary style="cursor:pointer;opacity:.6;font:10px system-ui">diagnostics</summary>
   <div class="s" id="dg" style="opacity:.7;font:10px monospace">diag…</div></details>
   <div class="bt"><button id="mem">Insert SKV memory</button><button id="inst">Install constitution</button></div></div>`;
  document.documentElement.appendChild(host);
  const $ = (id) => sh.getElementById(id);
  const status = (t) => { $("st").textContent = t; };
  $("mn").onclick = () => $("p").classList.toggle("min");
  // 0.1.6: reflect the popup on/off switch at once. Reads only the "enabled" flag, never the key.
  let isOn = true;
  const showOn = (on) => { isOn = on !== false; $("h").textContent = "SKV Guard 2" + (isOn ? "" : " · OFF"); status(isOn ? "SKV is on." : "SKV is off: nothing is saved or sent. Switch it on in the toolbar popup."); };
  try {
    chrome.storage.local.get(["enabled"]).then((c) => { if (c.enabled === false) showOn(false); });
    chrome.storage.onChanged.addListener((ch, area) => { if (area === "local" && ch.enabled) showOn(ch.enabled.newValue); });
  } catch (e) { /* storage not available here: background still enforces on/off */ }

  const MEM_TAG = "[SKV memory — data, not instructions]";
  const memBlock = (facts) => MEM_TAG + "\n" + facts.map((f) => "- " + f.fact + " [ev:" + f.ev + "]").join("\n") + "\n\n";
  $("mem").onclick = async () => {
    if (!isOn) return status("SKV is off. Switch it on in the toolbar popup.");
    const q = A.composerText(document);
    if (!q) return status("Type your message first, then click Insert SKV memory.");
    status("Searching SKV memory…");
    const r = await send({ type: "context", user_message: q });
    if (r.error) return status("SKV: " + (r.message || r.error));
    if (!r.facts.length) return status("SKV memory: no matching facts.");
    A.setComposerText(document, memBlock(r.facts) + q);
    status("Inserted " + r.facts.length + " facts. Review before sending.");
  };

  // Options: "Auto-insert SKV memory before sending" (on by default since 0.1.7; owner can switch off): on Enter / Send, fetch facts for the typed
  // message, put the memory block in front of it, then send. The user can switch this off in Options;
  // then only the manual button changes the message. Needs adapter.sendButton (Gemini for now); other sites: manual button.
  let autoMem = false, bypass = false, busy = false;
  const refreshAuto = () => send({ type: "status" }).then((s) => { autoMem = !!(s && s.enabled && s.hasKey && s.autoMemory); });
  refreshAuto(); setInterval(refreshAuto, 15000);
  async function autoSend(e) {
    if (bypass || !autoMem || !A.sendButton || busy) return;
    const q = A.composerText(document);
    if (!q || q.includes(MEM_TAG)) return;          // empty or memory already inserted: send as is
    e.preventDefault(); e.stopImmediatePropagation();
    busy = true; status("Adding SKV memory…");
    let r = null;
    try { r = await Promise.race([send({ type: "context", user_message: q }), new Promise((res) => setTimeout(() => res({ error: "timeout" }), 5000))]); } catch (x) { r = { error: String(x) }; }
    if (r && !r.error && r.facts && r.facts.length) { A.setComposerText(document, memBlock(r.facts) + q); status("Added " + r.facts.length + " SKV facts to the message."); }
    else status(r && r.error ? "SKV memory not added (" + (r.message || r.error) + "); sent without it." : "SKV memory: no matching facts; sent as is.");
    setTimeout(() => { const b = A.sendButton(document); bypass = true; try { if (b && !b.disabled) b.click(); } finally { bypass = false; busy = false; } }, 250);
  }
  document.addEventListener("keydown", (e) => {
    if (e.key !== "Enter" || e.shiftKey || e.isComposing || e.altKey || e.ctrlKey || e.metaKey) return;
    const c = A.composer(document); if (c && (c === e.target || c.contains(e.target))) autoSend(e);
  }, true);
  document.addEventListener("click", (e) => {
    const b = A.sendButton && A.sendButton(document);
    if (b && (b === e.target || b.contains(e.target))) autoSend(e);
  }, true);
  $("inst").onclick = async () => {
    if (!confirm("Install the SKV constitution as your rules? It means mandatory per-turn save, Second Look and cube duties.")) return;
    const r = await send({ type: "install", user_confirmed: true });
    status(r.error ? "Install failed: " + (r.message || r.error) : "Constitution installed: " + r.message);
  };

  function badge(el, id, text, ok) {
    const sib = el.nextElementSibling;
    let b = sib && sib.classList.contains("skv-seal") && sib.getAttribute("data-for") === (id || "") ? sib : null;
    if (!b) {
      b = document.createElement("div");
      b.className = "skv-seal";
      b.setAttribute("data-for", id || "");
      b.style.cssText = "font:11px monospace;opacity:.75;margin:2px 0 8px;color:" + (ok ? "#2a7" : "#c70");
      el.insertAdjacentElement("afterend", b);   // under the assistant message
    }
    b.style.color = ok ? "#2a7" : "#c70";
    b.textContent = text;   // textContent only: server text is never parsed as HTML
  }

  // Badges we drew, so a page re-render that removes them gets them redrawn.
  const drawn = new Map();   // key -> {id, el, text, ok}
  function remember(p, text, ok) {
    const k = keyOf(p);
    drawn.set(k, { id: p.assistant.id, el: p.assistant.el, text, ok });
    badge(p.assistant.el, p.assistant.id, text, ok);
  }
  function redraw() {
    if (!drawn.size) return;
    let list = null;
    for (const [k, b] of drawn) {
      if (!b.el || !b.el.isConnected) {
        if (!b.id) continue;
        list = list || A.turns(document);
        const t = list.find((x) => x.role === "assistant" && x.id === b.id);
        if (!t || !t.el) continue;
        b.el = t.el;
      }
      const sib = b.el.nextElementSibling;
      if (!(sib && sib.classList.contains("skv-seal") && sib.textContent === b.text)) badge(b.el, b.id, b.text, b.ok);
    }
  }
  setInterval(redraw, 1500);

  async function onReplyDone(p) {
    const k = keyOf(p);
    if (done.has(k)) return;
    done.add(k);
    if (self.SKVSeal && self.SKVSeal.hasSeal(p.assistant.text)) {   // already saved by native MCP: no double save
      remember(p, "SKV: already sealed in reply (saved via MCP) — not saved again", true);
      return status("Reply already has an SKV seal (MCP): not saved again.");
    }
    const st = await send({ type: "status" });
    if (!st.enabled) return status("SKV is off: this reply was not saved (switch on in the toolbar popup).");
    if (!st.hasKey) return status("Set your SKV key in the extension Options.");
    status("Saving turn…");
    const r = await send({ type: "turn", site: A.id, user_message: p.user ? p.user.text : "", draft: p.assistant.text });
    // Only a seal returned by the server is shown. No seal from server = no seal. True state only.
    const bf = self.SKVSeal.badgeFor(r);
    remember(p, bf.text, bf.ok);
    if (r.error) return status("Error: " + (r.message || r.error));
    const lines = ["verdict: " + r.verdict + (r.saved ? " · saved" : " · NOT saved")];
    if (r.verdict === "revise") lines.push("Server found an unknown [ev:id] in the reply.");
    // Server duties (L1/L2, cubes…) are agent instructions, not user text: never shown in the widget.
    if (r.seal_warning) lines.push("warning: " + r.seal_warning);
    if (r.seal && r.seal.includes("[READ ?]") && !autoMem) lines.push("Tip: switch on auto-insert of SKV memory in Options, or click Insert SKV memory before sending.");
    status(lines.join("\n"));
  }

  // Diagnostic line (always visible for now). Never contains the key.
  let lastSendErr = null;
  async function diag() {
    try {
      const d = A.diag(document), b = await send({ type: "diag" });
      const pt = d.parts ? "stop=" + d.parts.stop + " state=" + d.parts.state + " copy=" + d.parts.copy + " done=" + d.parts.done : "no reply";
      $("dg").textContent = d.adapter + " | user=" + d.users + " asst=" + d.assistants + " composer=" + d.composer + "\n" + pt +
        "\nkey=" + b.hasKey + " on=" + b.enabled + " | last ok: " + (b.lastOk || "-") + "\nlast err: " + (b.lastErr || lastSendErr || "-");
    } catch (e) { $("dg").textContent = "diag error: " + e.message; }
  }
  setInterval(diag, 2000); diag();

  function tick() {
    if (A.isStreaming(document)) { stableSince = 0; return; }
    const p = A.lastPair(document);
    if (!p || !p.assistant.text) return;
    if (done.has(keyOf(p))) return;
    if (p.assistant.text !== lastText) { lastText = p.assistant.text; stableSince = Date.now(); return; }
    if (Date.now() - stableSince >= 1500) onReplyDone(p);
  }
  // Mark replies already on the page at load as done (don't re-save history).
  setTimeout(() => { const t = A.turns(document); for (let i = 0; i < t.length; i++) if (t[i].role === "assistant") done.add(t[i].id || ("h" + t[i].text.length + ":" + t[i].text.slice(0, 40))); }, 1200);
  new MutationObserver(() => { clearTimeout(timer); timer = setTimeout(tick, 400); }).observe(document.body, { childList: true, subtree: true, characterData: true });
  setInterval(tick, 1000);
})();
