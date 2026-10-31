# SKV Guard 2 0.1.6: manual browser check (about 10 min)

Install: chrome://extensions → Developer mode → remove 0.1.5 → "Load unpacked" on the unzipped folder (or drag the zip in). Version must show 0.1.6.

1. Toolbar icon → a popup opens (not the settings page). It shows "SKV on", State, Key = "not set".
2. Popup "Settings" → Options. Paste your sk_ key, Save → "Saved". Reopen popup: Key = "set". The key text is shown nowhere.
3. Open chatgpt.com (reload the tab). Bottom-right widget "SKV Guard 2". Send a short message; after the reply a green seal line appears under it, widget says "verdict: … · saved".
4. Popup → untick "SKV on". State turns red "OFF". Without reloading, the widget header becomes "SKV Guard 2 · OFF".
5. While OFF, send a message: no seal line, widget says "SKV is off: this reply was not saved". "Insert SKV memory" says SKV is off.
6. Tick "SKV on" again: header loses "· OFF"; the next reply gets a seal.
7. Masking: type in the chat `my test password=Abc12345xyz and key pza_testtesttest123` (fake values), click "Insert SKV memory", then send. In SKV (search or MCP) the saved turn must show `[SECRET]` instead of both values.
8. Diagnostics (widget → diagnostics): key=true on=true, "last ok: /api/v7/agent/turn ok @HH:MM:SS MSK".
9. Optional: the same on claude.ai / gemini.google.com / chat.mistral.ai (adapters not verified on live pages yet).

Report anything that fails with the step number and a screenshot of the widget diagnostics.
