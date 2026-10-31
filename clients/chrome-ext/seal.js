// Double-save guard: if the assistant reply already carries a server SKV seal (saved via native MCP,
// e.g. claude.ai connectors), the extension must not save the turn again.
(function (root) {
  const SEAL = /SKV\s*\|\s*#\d+/;
  // True state of a turn result -> badge text. Never claims "saved" when the server did not save.
  function badgeFor(r) {
    if (!r) return { text: "SKV: not saved (no reply) — no seal", ok: false };
    if (r.error) return { text: "SKV: not saved (" + (r.message || r.error) + ") — no seal", ok: false };
    if (!r.saved) {
      if (r.invalid_ids && r.invalid_ids.length) return { text: "SKV: not saved: unknown ev id " + r.invalid_ids.join(", ") + " — no seal", ok: false };
      if (r.profile_errors) return { text: "SKV: not saved: profile error — no seal", ok: false };
      return { text: "SKV: not saved (verdict " + (r.verdict || "?") + ") — no seal", ok: false };
    }
    if (!r.seal) return { text: "SKV: saved, no seal returned", ok: false };
    if (r.unknown_ids && r.unknown_ids.length) return { text: r.seal + " · unknown ev id: " + r.unknown_ids.join(", "), ok: false };
    return { text: r.seal, ok: true };
  }
  const api = { hasSeal: (t) => SEAL.test(t || ""), badgeFor };
  root.SKVSeal = api;
  if (typeof module !== "undefined") module.exports = api;
})(typeof self !== "undefined" ? self : globalThis);
