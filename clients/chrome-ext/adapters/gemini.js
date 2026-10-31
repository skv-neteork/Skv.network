// Gemini (gemini.google.com) adapter. UNVERIFIED against the live site: selectors from public sources
// (Gemini exporter userscripts / extensions, 2025-2026: <user-query>, <model-response>, rich-textarea .ql-editor,
// "Stop response" button), not our own capture. The widget diagnostics show what is actually found.
(function (root) {
  const S = {
    composer: ["rich-textarea .ql-editor[contenteditable='true']", ".ql-editor[contenteditable='true']", "[contenteditable='true'][role='textbox']", "textarea"],
    user: ["user-query", ".user-query-container", "[data-test-id='user-query']"],
    assistant: ["model-response", ".model-response-container", "[data-test-id='model-response']"],
    assistantText: ["message-content .markdown", ".model-response-text .markdown", "message-content", ".markdown"],
    userText: [".query-text", ".query-text-line", ".user-query-bubble-with-background"],
    stop: ["button[aria-label='Stop response']", "button.send-button.stop", "button[aria-label*='Stop' i]"],
    copy: ["copy-button button", "button[aria-label='Copy']", "button[data-test-id='copy-button']", "button[aria-label^='Copy' i]"]
  };
  const first = (el, list) => { for (const s of list) { try { const r = el.querySelector(s); if (r) return r; } catch (e) {} } return null; };
  const txt = (el) => ((el.innerText !== undefined && el.innerText !== "" ? el.innerText : el.textContent) || "").trim();
  const adapter = {
    id: "gemini", verified: false, selectors: S,
    matches: (host) => /(^|\.)gemini\.google\.com$/.test(host),
    turns(doc) {
      const out = [];
      for (const role of ["user", "assistant"]) for (const s of S[role]) {
        let n = []; try { n = doc.querySelectorAll(s); } catch (e) {}
        for (const el of n) if (!out.some((o) => o.el === el || o.el.contains(el) || el.contains(o.el))) out.push({ role, el });
      }
      out.sort((a, b) => (a.el.compareDocumentPosition(b.el) & 4 ? -1 : 1));
      return out.map((t) => ({ role: t.role, el: t.el, id: adapter.idOf(t.el), text: adapter.textOf(t.el, t.role) }));
    },
    idOf(el) { const c = el.closest(".conversation-container[id], [data-response-id]") || el.querySelector("[id^='model-response-message-content'], [data-response-id]");
      return (c && (c.getAttribute("data-response-id") || c.id)) || el.id || ""; },
    textOf(el, role) {
      if (role === "assistant") {
        const parts = el.querySelectorAll(S.assistantText[0]);   // answer only; skips "thinking" parts
        if (parts.length) return Array.from(parts).map(txt).join("\n").trim();
      }
      const b = first(el, role === "user" ? S.userText : S.assistantText.slice(1)) || el;
      const c = b.cloneNode(true); c.querySelectorAll("button").forEach((x) => x.remove()); return txt(c);
    },
    // Gemini: done = no "Stop response" button anywhere; Copy on the response is a hint only.
    doneParts(doc, el) {
      const stop = !!first(doc, S.stop);
      const copy = !!(first(el, S.copy) || (el.parentElement && first(el.parentElement, S.copy)));
      return { stop, state: null, copy, done: !stop };
    },
    isReplyDone(doc, el) { return adapter.doneParts(doc, el).done; },
    isStreaming(doc) { return !!first(doc, S.stop); },
    lastPair(doc) {
      const t = adapter.turns(doc);
      for (let i = t.length - 1; i >= 0; i--) {
        if (t[i].role !== "assistant") continue;
        for (let j = i - 1; j >= 0; j--) if (t[j].role === "user") return { user: t[j], assistant: t[i] };
        return { user: null, assistant: t[i] };
      }
      return null;
    },
    diag(doc) {
      const t = adapter.turns(doc), p = adapter.lastPair(doc);
      return { adapter: adapter.id + " (unverified)", users: t.filter((x) => x.role === "user").length, assistants: t.filter((x) => x.role === "assistant").length,
        parts: p ? adapter.doneParts(doc, p.assistant.el) : null, composer: !!adapter.composer(doc) };
    },
    composer(doc) { return first(doc, S.composer); },
    composerText(doc) { const c = adapter.composer(doc); return c ? (c.tagName === "TEXTAREA" ? c.value : txt(c)).trim() : ""; },
    setComposerText(doc, text) {
      const c = adapter.composer(doc); if (!c) return false;
      c.focus();
      if (c.tagName === "TEXTAREA") { c.value = text; c.dispatchEvent(new Event("input", { bubbles: true })); return true; }
      let ok = false;
      try {
        const sel = doc.getSelection && doc.getSelection();
        if (sel) { const r = doc.createRange(); r.selectNodeContents(c); sel.removeAllRanges(); sel.addRange(r); }
        ok = doc.execCommand && doc.execCommand("insertText", false, text);
      } catch (e) { ok = false; }
      if (!ok) { c.innerHTML = ""; text.split("\n").forEach((l) => { const p = doc.createElement("p"); p.textContent = l; c.appendChild(p); }); }
      const IE = (doc.defaultView && doc.defaultView.InputEvent) || Event;
      c.dispatchEvent(new IE("input", { bubbles: true, inputType: "insertText", data: text }));
      return true;
    }
  };
  root.SKVAdapters = (root.SKVAdapters || []).concat([adapter]);
  if (typeof module !== "undefined") module.exports = adapter;
})(typeof self !== "undefined" ? self : globalThis);
