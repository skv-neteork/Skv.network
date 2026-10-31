// Toolbar popup: on/off switch and status. Never reads or shows the key itself, only whether one is set.
(function () {
  const $ = (id) => document.getElementById(id);
  function paint(on, hasKey) {
    $("enabled").checked = on;
    $("state").textContent = on ? "ON: turns are saved" : "OFF: nothing is sent";
    $("state").className = on ? "on" : "off";
    $("key").textContent = hasKey ? "set" : "not set (open Settings)";
  }
  function refresh() {
    chrome.runtime.sendMessage({ type: "diag" }, (d) => {
      void chrome.runtime.lastError;
      d = d || {};
      paint(d.enabled !== false, !!d.hasKey);
      $("diag").textContent = "last ok: " + (d.lastOk || "-") + "\nlast err: " + (d.lastErr || "-");
    });
  }
  $("enabled").addEventListener("change", async () => {
    const on = $("enabled").checked;
    await chrome.storage.local.set({ enabled: on });
    refresh();
  });
  $("opts").addEventListener("click", (e) => { e.preventDefault(); chrome.runtime.openOptionsPage(); });
  refresh();
  if (typeof module !== "undefined") module.exports = { paint, refresh };
})();
