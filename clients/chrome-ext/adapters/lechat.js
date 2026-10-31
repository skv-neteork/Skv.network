// Le Chat (chat.mistral.ai) adapter. UNVERIFIED against the live site: selectors come from public
// sources (ArcRift PLATFORM_SELECTORS.md "verified May 2026", greasyfork exporters), not our own capture.
// Same shape as chatgpt.js. The diagnostics line in the widget shows what is actually found.
(function (root) {
  const S = {
    composer: ["div.ProseMirror[contenteditable='true']", "[contenteditable='true'][role='textbox']", "textarea"],
    user: ["[data-message-author-role='user']", ".user-message", "[data-role='user']"],
    assistant: ["[data-message-author-role='assistant']", ".assistant-message", "[data-role='assistant']"],
    assistantText: ["[data-message-part-type='answer']", ".markdown", ".prose"],
    userText: ["div[dir='auto']", ".whitespace-pre-wrap"],
    stop: ["button[aria-label='Stop']", "button[aria-label*='Stop' i]", "button[aria-label*='Arrêter' i]"],
    copy: ["button[aria-label='Copy']", "button[aria-label^='Copy' i]", "button[aria-label*='Copier' i]"]
  };
  const first = (el, list) => { for (const s of list) { try { const r = el.querySelector(s); if (r) return r; } catch (e) {} } return null; };
  const txt = (el) => ((el.innerText !== undefined && el.innerText !== "" ? el.innerText : el.textContent) || "").trim();
  const adapter = {
    id: "lechat", verified: false, selectors: S,
    matches: (host) => /(^|\.)chat\.mistral\.ai$/.test(host),
    turns(doc) {
      const out = [];
      for (const role of ["user", "assistant"]) for (const s of S[role]) {
        let n = []; try { n = doc.querySelectorAll(s); } catch (e) {}
        for (const el of n) if (!out.some((o) => o.el === el || o.el.contains(el) || el.contains(o.el))) out.push({ role, el });
      }
      out.sort((a, b) => (a.el.compareDocumentPosition(b.el) & 4 ? -1 : 1));
      return out.map((t) => ({ role: t.role, el: t.el, id: adapter.idOf(t.el), text: adapter.textOf(t.el, t.role) }));
    },
    idOf(el) { const m = el.closest("[data-message-id]") || el.querySelector("[data-message-id]"); return (m && m.getAttribute("data-message-id")) || el.id || ""; },
    textOf(el, role) {
      if (role === "assistant") {
        const parts = el.querySelectorAll(S.assistantText[0]);   // answer only; skips "thinking" parts
        if (parts.length) return Array.from(parts).map(txt).join("\n").trim();
      }
      const b = first(el, role === "user" ? S.userText : S.assistantText.slice(1)) || el;
      const c = b.cloneNode(true); c.querySelectorAll("button").forEach((x) => x.remove()); return txt(c);
    },
    // No turn-state attribute known on Le Chat: done = no stop button (+ Copy if the site shows one);
    // content.js adds the 1.5 s stable-text debounce on top.
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
