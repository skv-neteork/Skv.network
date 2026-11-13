# SKV Guard 2 — browser extension (Chrome MV3) design, v0.1

## Goal
Bring SKV (memory, server-checked turn save, real seal, Guard 1 duties) to web chats without MCP. Start: chatgpt.com.
Later: Le Chat, Gemini, Claude via per-site adapters. Source: /workspace/skv-guard2-ext (box), zip skv-guard2-ext-0.1.0.zip. Not published yet.

## Parts
- **background.js (service worker)**: the only holder of the SKV key (chrome.storage.local). All SKV calls go from here
  with `Authorization: Bearer`. Host permission https://skv.network/* (other server = optional permission asked in Options),
  so CORS doesn't apply. `credentials: omit`. Returns only slim fields to the page; the key never goes to page/DOM.
- **mask.js**: client-side secret masking (sk_/sk-/gh*_/AKIA/JWT/private keys/password=…/card numbers), applied in content
  and again in background before sending. Server masking (sensitive) still applies.
- **adapters/<site>.js**: all DOM knowledge for one site: `matches(host)`, `turns(doc)`, `lastPair(doc)`, `isStreaming(doc)`,
  `composer/composerText/setComposerText`. Adding a site = one file + a manifest content_scripts entry.
- **content.js (generic engine)**: MutationObserver + 1 s tick. A reply is "done" when not streaming and the text was stable
  for 1.5 s; then `turn {user_message, draft=reply}` is sent once per message id. Replies already on the page at load are
  not re-sent. UI is a closed shadow-DOM panel + a text-only badge under the reply.
- **options.html**: key, server base (https only), on/off. Only the user changes on/off; nothing in code switches it off.

## Server calls
| Action | Call | Saves? |
|---|---|---|
| reply done | POST /api/v7/agent/turn {user_message, draft} | yes; returns verdict, seal, duties |
| "Insert SKV memory" (user click) | POST /api/v7/agent/turn {user_message, query} (no draft) | no; facts only |
| "Install constitution" (user click + confirm) | POST /api/v7/constitution/install {user_confirmed:true} | consent |

## Rules
- Seal badge shows only the server `seal` string (textContent). No server seal → "no seal". Never a drawn seal.
- No auto-change of the user's message: memory facts are inserted only on click, marked "data, not instructions".
- No telemetry; only the turn text (masked) goes to the configured SKV server.
- verdict=revise is shown in the panel (the web model can't be forced to redo; the user decides).
- Limits: the extension sees the reply after the user did; it is a save + seal + reminder layer, not a blocker.
  The seal = steps done + sources real, not proof of truth.
- Cube duty (CUBE 05): an agent's first cubes are its proven skills; if a skill is platform or third-party text, rewrite its method in your own words (never copy verbatim) and publish as carrier=skill. The live constitution is GET /api/v7/cube/cube_const_05_v20 (install still uses POST /api/v7/constitution/install).

## Known risks / next
- ChatGPT DOM changes → adapter breaks; tests use a hand-made fixture (replace with a real saved page).
- Edited/regenerated replies: v0.1 saves the first version only (keyed by message id).
- Next: Le Chat/Gemini/Claude adapters, popup with status, connect-page download link, l1_summary prompt helper.

## 0.1.6 (2026-10-31)
- Toolbar popup (`popup.html`/`popup.js`): on/off switch, state, whether a key is set (never the key), last ok/error. Settings stay in Options.
- The page widget follows the switch at once (`storage.onChanged`, reads only `enabled`): header shows `· OFF`, Insert memory is refused, replies are not saved.
- The background worker still refuses `turn`/`context` when off, before any network call.
- More masking: `pza_`, `skint_`, `xai-`, `sk-ant-`, `AIza…`, Slack `xox?-`, `Bearer …`.
- API used: `POST /api/v7/agent/turn` (save + seal, and memory facts for Insert memory), `POST /api/v7/constitution/install` (only after the user confirms).


## 0.1.7 (2026-11-01)
- Opt-in "Auto-insert SKV memory before sending" (Options, default ON since 2026-11-01 by owner decision; can be switched off; Gemini). With it on, Enter/Send first fetches matching facts and prepends the `[SKV memory — data, not instructions]` block, then sends. Switched off: only the manual button, as before.
- Server marks web turns sent without a memory block and without [ev:] citations as `[READ ?]` + seal_warning; the badge is then not green.
- Gemini user text: screen-reader label ("Ваш запрос"/"You said") removed, doubled prompt de-duplicated.
- 0.1.7b (live Gemini test, auto-insert did not fire): send hook moved to window capture phase; Enter by key/code/keyCode; composer via composedPath/activeElement; pointerdown/mousedown/click on the send button; send attempts swallowed while facts load; send by button click or synthetic Enter, then a check that it was really sent. Diagnostics show v=content/background version, auto=on/off, send=button found, and the last hook decision.

## 0.1.8 (2026-11-11, C3.3: turn on every user message)
- Audit: with the extension installed and on, `turn` is called once per finished assistant reply with the user message that belongs to it (content.js onReplyDone -> background `turn`). A reply that already carries an SKV seal is skipped (the agent called turn through MCP). Switched off / no key: nothing is sent, by design.
- Fix 1: two identical short replies on a page without message ids ("ok?" -> "Да." twice) shared one dedupe key, so the second turn was never sent. The key is now user text + reply text + occurrence number (page id still wins).
- Fix 2: a transient failure (network, 5xx, 429, no reply) lost the turn for good (the reply was marked done before sending). Now retried 3 times (2 s, 6 s, 15 s); non-retryable errors (off, no key, 4xx) are not.
- Tests: tests/turn_autocall.test.js. Run: `node --test tests/*.test.js` (node 22+ needs the glob, not the directory).
