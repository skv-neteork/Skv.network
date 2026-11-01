const $ = (id) => document.getElementById(id);
chrome.storage.local.get(["key", "base", "enabled", "autoMemory"]).then((c) => {
  $("key").value = c.key || ""; $("base").value = c.base || "https://skv.network"; $("enabled").checked = c.enabled !== false; $("autoMemory").checked = !!c.autoMemory;
});
$("save").onclick = async () => {
  const key = $("key").value.trim(), base = $("base").value.trim().replace(/\/+$/, "");
  if (key && !/^sk_[A-Za-z0-9_\-]+$/.test(key)) return ($("msg").textContent = "Key must start with sk_");
  if (!/^https:\/\//.test(base)) return ($("msg").textContent = "Server must be https://");
  if (!base.startsWith("https://skv.network")) {
    const ok = await chrome.permissions.request({ origins: [base + "/*"] });
    if (!ok) return ($("msg").textContent = "Permission for that server was refused");
  }
  await chrome.storage.local.set({ key, base, enabled: $("enabled").checked, autoMemory: $("autoMemory").checked });
  $("msg").textContent = "Saved";
};
