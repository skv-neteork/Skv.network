// ChatGPT adapter: everything site-specific lives here. Other sites = another file with the same shape.
// Selectors are ordered lists: current DOM first (2026-10), legacy [data-message-author-role] last.
(function (root) {
  const S = {
    composer: [
      "form[data-chatgpt-composer] div.ProseMirror[contenteditable='true'][role='textbox']",
      "form[data-chatgpt-composer] [contenteditable='true']",
      "div.ProseMirror[contenteditable='true'][role='textbox']",
      "#prompt-textarea", "div[contenteditable='true'].ProseMirror", "form textarea", "textarea"
    ],
    user: [
      "[data-chatgpt-search-unit-key$=':user']",
      "div[data-user-message-bubble='true']",
      "[data-message-author-role='user']"
    ],
    assistant: [
      "[data-chatgpt-search-unit-key$=':assistant']",
      "h4[data-conversation-role='assistant']",
      "[data-message-author-role='assistant']"
    ],
    assistantText: ["[data-dil-source-message-id]", "[data-markdown-text-style='assistant-message']", ".markdown"],
    userText: ["div[data-user-message-bubble='true']", ".whitespace-pre-wrap"],
    turn: ["div[data-turn-key]", "[data-content-search-turn-key]", "article[data-testid^='conversation-turn']"],
    stop: ["button[aria-label='Stop']", "button[aria-label='Stop streaming']", "[data-testid='stop-button']", "button[aria-label*='Stop' i]", ".result-streaming"],
    copy: ["button[aria-label='Copy']", "button[data-testid='copy-turn-action-button']", "button[aria-label^='Copy' i]"]
  };
  const first = (el, list) => { for (const s of list) { try { const r = el.querySelector(s); if (r) return r; } catch (e) {} } return null; };
  const unitOf = (el, role) => {
    // Normalise any matched node to its message container.
    return el.closest("[data-chatgpt-search-unit-key$=':" + role + "']") ||
      el.closest("[data-message-author-role='" + role + "']") ||
      (role === "assistant" && el.matches("h4") ? el.parentElement : null) ||
      (role === "user" ? (el.closest(".group\\/user-message") || el) : el);
  };
  const txt = (el) => ((el.innerText !== undefined && el.innerText !== "" ? el.innerText : el.textContent) || "").replace(/\s+\n/g, "\n").trim();

  const adapter = {
    id: "chatgpt",
    selectors: S,
    matches: (host) => /(^|\.)chatgpt\.com$|(^|\.)chat\.openai\.com$/.test(host),
    // All turns in page order: [{role, id, el, text}]; el = message container (badge goes after it).
    turns(doc) {
      const seen = new Set(), out = [];
      for (const role of ["user", "assistant"]) {
        for (const s of S[role]) {
          let nodes = []; try { nodes = doc.querySelectorAll(s); } catch (e) {}
          for (const n of nodes) {
            const el = unitOf(n, role);
            if (seen.has(el)) continue;
            // skip nested duplicates (e.g. bubble inside an already-collected user unit)
            if (out.some((o) => o.el.contains(el) || el.contains(o.el))) continue;
            seen.add(el); out.push({ role, el });
          }
        }
      }
      out.sort((a, b) => (a.el.compareDocumentPosition(b.el) & 4 ? -1 : 1));
      return out.map((t) => ({ role: t.role, el: t.el, id: adapter.idOf(t.el, t.role), text: adapter.textOf(t.el, t.role) }));
    },
    idOf(el, role) {
      const m = el.querySelector("[data-dil-source-message-id],[data-chatgpt-selection-message-id],[data-message-id]");
      return el.getAttribute("data-message-id") ||
        (m && (m.getAttribute("data-dil-source-message-id") || m.getAttribute("data-chatgpt-selection-message-id") || m.getAttribute("data-message-id"))) ||
        el.getAttribute("data-chatgpt-search-unit-key") || "";
    },
    textOf(el, role) {
      const body = first(el, role === "user" ? S.userText : S.assistantText) || el;
      if (role === "user" || !first(el, S.assistantText)) {
        // fallback: exclude sr-only headings / buttons
        const c = body.cloneNode(true); c.querySelectorAll("h4.sr-only, button").forEach((x) => x.remove()); return txt(c);
      }
      return txt(body);
    },
    turnOf(el) { for (const s of S.turn) { const t = el.closest(s); if (t) return t; } return null; },
    // Copy button for this reply: inside the assistant block first, else anywhere in its turn container
    // (action bar may be a sibling), skipping buttons that belong to the user message.
    copyFor(el) {
      const own = first(el, S.copy); if (own) return own;
      const t = adapter.turnOf(el); if (!t) return null;
      for (const s of S.copy) {
        let nodes = []; try { nodes = t.querySelectorAll(s); } catch (e) {}
        for (const b of nodes) {
          if (b.closest("[data-chatgpt-search-unit-key$=':user'], [data-user-message-bubble], .group\\/user-message, [data-message-author-role='user']")) continue;
          if (/message/i.test(b.getAttribute("aria-label") || "")) continue; // "Copy message" = user bubble
          return b;
        }
      }
      return null;
    },
    // Parts of the done check, for diagnostics: {stop, state, copy, done}
    doneParts(doc, el) {
      const stop = !!first(doc, S.stop);
      const t = adapter.turnOf(el);
      const stEl = t && (t.matches("[data-talvt-turn-state]") ? t : t.querySelector("[data-talvt-turn-state]"));
      const state = stEl ? stEl.getAttribute("data-talvt-turn-state") : null;
      const copy = !!adapter.copyFor(el);
      const newDom = !!el.closest("[data-chatgpt-search-unit-key]") || !!stEl;
      const done = !stop && (state === null || state === "complete") && (!newDom || copy);
      return { stop, state, copy, done };
    },
    // Reply finished: turn-state complete (if present) AND Copy present AND no stop button.
    isReplyDone(doc, el) { return adapter.doneParts(doc, el).done; },
    diag(doc) {
      const t = adapter.turns(doc), p = adapter.lastPair(doc);
      return { adapter: adapter.id, users: t.filter((x) => x.role === "user").length, assistants: t.filter((x) => x.role === "assistant").length,
        parts: p ? adapter.doneParts(doc, p.assistant.el) : null, composer: !!adapter.composer(doc) };
    },
    // Still generating? true if stop button, or the last assistant reply isn't done.
    isStreaming(doc) {
      if (first(doc, S.stop)) return true;
      const p = adapter.lastPair(doc);
      return !!(p && !adapter.isReplyDone(doc, p.assistant.el));
    },
    lastPair(doc) {
      const t = adapter.turns(doc);
      for (let i = t.length - 1; i >= 0; i--) {
        if (t[i].role !== "assistant") continue;
        for (let j = i - 1; j >= 0; j--) if (t[j].role === "user") return { user: t[j], assistant: t[i] };
        return { user: null, assistant: t[i] };
      }
      return null;
    },
    composer(doc) { return first(doc, S.composer); },
    composerText(doc) {
      const c = adapter.composer(doc);
      if (!c) return "";
      return (c.tagName === "TEXTAREA" ? c.value : txt(c)).trim();
    },
    // Replace composer text. ProseMirror: execCommand('insertText') + input event so editor state updates.
    setComposerText(doc, text) {
      const c = adapter.composer(doc);
      if (!c) return false;
      c.focus();
      if (c.tagName === "TEXTAREA") {
        c.value = text;
        c.dispatchEvent(new Event("input", { bubbles: true }));
        return true;
      }
      let ok = false;
      try {
        const sel = doc.getSelection && doc.getSelection();
        if (sel) { const r = doc.createRange(); r.selectNodeContents(c); sel.removeAllRanges(); sel.addRange(r); }
        ok = doc.execCommand && doc.execCommand("insertText", false, text);
      } catch (e) { ok = false; }
      if (!ok) { // fallback: rewrite paragraphs directly
        c.innerHTML = "";
        text.split("\n").forEach((line) => { const p = doc.createElement("p"); p.textContent = line; c.appendChild(p); });
      }
      const IE = (doc.defaultView && doc.defaultView.InputEvent) || Event;
      c.dispatchEvent(new IE("input", { bubbles: true, inputType: "insertText", data: text }));
      return true;
    }
  };
  root.SKVAdapters = (root.SKVAdapters || []).concat([adapter]);
  if (typeof module !== "undefined") module.exports = adapter;
})(typeof self !== "undefined" ? self : globalThis);
