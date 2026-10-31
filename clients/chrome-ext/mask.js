// Client-side secret masking. Runs before anything leaves the page and again in the background.
(function (root) {
  const RULES = [
    [/\bsk_[A-Za-z0-9_\-]{8,}/g, "[SECRET]"],
    [/\b(?:pza|skint)_[A-Za-z0-9_\-]{8,}/g, "[SECRET]"],
    [/\bxai-[A-Za-z0-9_\-]{16,}/g, "[SECRET]"],
    [/\bAIza[0-9A-Za-z_\-]{30,}/g, "[SECRET]"],
    [/\bxox[abprs]-[A-Za-z0-9\-]{10,}/g, "[SECRET]"],
    [/\b(Bearer\s+)[A-Za-z0-9._~+\/\-]{12,}=*/gi, "$1[SECRET]"],
    [/\bsk-[A-Za-z0-9_\-]{16,}/g, "[SECRET]"],
    [/\b(gh[pousr]_[A-Za-z0-9]{20,})\b/g, "[SECRET]"],
    [/\bAKIA[0-9A-Z]{16}\b/g, "[SECRET]"],
    [/\beyJ[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{10,}/g, "[SECRET]"],
    [/-----BEGIN [A-Z ]*PRIVATE KEY-----[\s\S]*?-----END [A-Z ]*PRIVATE KEY-----/g, "[SECRET]"],
    [/((?:password|passwd|pwd|token|secret|api[_-]?key|пароль)\s*[:=]\s*)\S+/gi, "$1[SECRET]"],
    [/\b(?:\d[ -]?){13,19}\b/g, "[SECRET]"]
  ];
  function maskSecrets(s) {
    if (typeof s !== "string") return s;
    for (const [rx, rep] of RULES) s = s.replace(rx, rep);
    return s;
  }
  root.SKVMask = { maskSecrets };
  if (typeof module !== "undefined") module.exports = { maskSecrets };
})(typeof self !== "undefined" ? self : globalThis);
