"""Shared feature names, try-it prompts, the step_zero offer, and suggest-when hints.

The same sentences are used by the public /features page, Profile “My features”,
and the agent help block. Status is computed elsewhere; this module has no I/O.
"""

TRY = {
    "memory": (
        "Remember that I take oat milk in coffee, nothing else. "
        "Then in a new chat: What do I take in coffee? Cite the event id and show the seal you received — do not draw a seal yourself."
    ),
    "import": "What did we decide in the imported chat? Cite an event id.",
    "lines": "Search all my memory lines for oat milk. Which agent or line wrote it?",
    "recall": "Run a deeper delayed recall for my coffee preference, wait for the result, and cite any event ids. Only then say you don’t know.",
    "seal": "Save this: my timezone is Europe/London. Then show the exact seal the server returned, and the event id for that fact. Do not draw a seal yourself.",
    "constitution": "Is the SKV constitution installed? If not, explain what I would be agreeing to, and wait for my yes — do not install it yet.",
    "vault": "Save a test name, then tell your agent: Do not print that secret’s value.",
    "cubes": "Search shared cubes for MCP memory. If one looks relevant, tell me the id and ask before installing anything.",
    "chrome": "Install, add your key in Options, send one ChatGPT message, confirm a server seal appears.",
}

IMPORT_EXAMPLE = "User: We decided oat milk only.\nAssistant: Noted. Oat milk, nothing else."

CHROME_NOTE = "Load unpacked. ChatGPT is the verified site. Other sites are unverified. This is not a Chrome Web Store listing."
CHROME_URL = "https://skv.network/downloads/skv-guard2-chrome.zip"
DEMO_URL = "https://skv.network/mcp/k/demo/"

# id, public name, anchor, benefit, try key, client action
FEATURES = (
    ("memory", "Memory across chats", "memory-across-chats",
     "A fact saved in one chat is searchable in another chat that uses the same key.", "memory", "copy"),
    ("chrome", "Chrome extension (beta)", "chrome-extension",
     "A beta extension can save a ChatGPT web chat into the same memory.", "chrome", "download"),
    ("import", "Import a past chat", "import-a-past-chat",
     "Paste an old transcript, or upload a ChatGPT or Claude export, so a new agent can use it.", "import", "import"),
    ("lines", "Search across memory lines", "search-across-memory-lines",
     "Search the other keys on this account, and keep named agents on one key apart.", "lines", "copy"),
    ("recall", "Deeper delayed recall", "deeper-delayed-recall",
     "When a normal search misses, a background search can return evidence with event ids.", "recall", "copy"),
    ("seal", "Server seal and event ids", "server-seal",
     "Each saved turn returns a server seal and an event id. The seal means the steps ran.", "seal", "copy"),
    ("constitution", "Constitution", "constitution",
     "The constitution is installed only after you say yes. Only you can switch it off, and only completely.", "constitution", "copy"),
    ("vault", "Vault", "vault",
     "Store a secret by name. Agents can use the name and never receive the value.", "vault", "vault"),
    ("cubes", "Experience cubes", "experience-cubes",
     "Search shared methods other agents published. Installing one waits for your yes.", "cubes", "copy"),
    ("demo", "Public demo", "public-demo",
     "A shared demo for a disposable try. It is wiped daily. Put nothing private there.", "", "link"),
)

OFFER = """SKV — offer only these; do not invent functions.

WHEN a new chat, a model switch, or “do you remember”: same key; search; answer with [ev:id] and the server seal (never draw one). Try: “What do I take in coffee? Cite the event id and show the seal you received — do not draw a seal yourself.”

WHEN old ChatGPT/Claude chats, an export, or import: call memory_import_text with the pasted chat (User:/Assistant: labels help). A conversations export can also be uploaded at https://skv.network/profile (Import a chat). Then ask what was decided, with an event id.

WHEN several agents/keys, or “what did another agent do”: identify(name), search lines=all, label [ev:id@agent] vs my [ev:id].

WHEN a search misses, or “you forgot”: memory_recall_later, poll memory_recall_status, answer from the evidence; only then say you don’t know.

WHEN asked about rules: constitution installs only after explicit yes; only the user can switch SKV off, and only completely.

WHEN passwords, API keys, or “don’t store this”: Profile → Vault. I may vault_inject; never print the value.

WHEN a reusable method may already exist: cube_search, give the id, ask before cube_install, then offer a vote.

WHEN no key: demo https://skv.network/mcp/k/demo/ (shared, wiped daily, nothing private)."""

# Final sentence on the public description and in skv://help.
# Kept short: tools/list is near the 12 KB channel cap, so each hint is one clause.
SUGGEST = {
    "turn": "Suggest when: every user message, once SKV is on.",
    "memory_search": "Suggest when: the user asks what was said, or about another agent; pass lines=all.",
    "memory_recall_later": "Suggest when: search missed; wait for memory_recall_status before saying you don’t know.",
    "memory_recall_status": "Suggest when: you have a job_id; poll until done, then answer from the evidence.",
    "identify": "Suggest when: this key has no name, or several agents share it.",
    "constitution_install": "Suggest when: the user has just said yes; never call it silent.",
    "constitution_status": "Suggest when: the user asks if the rules are on.",
    "vault_inject": "Suggest when: a stored secret is needed; never print the value. Store or reveal it only on Profile → Vault.",
    "cube_search": "Suggest when: another agent may already have a method for this.",
    "cube_install": "Suggest when: the user has said yes to this cube in this turn.",
    "cube_vote": "Suggest when: you used a cube that is not your own.",
    "cube_create": "Suggest when: you learned a reusable method and consent status is allowed.",
    "cube_consent": "Suggest when: you learned a reusable method; publish only if status is allowed.",
    "drive_connect": "Suggest when: the user mentions Google Drive, or a file over 1 MB is refused.",
    "memory_import_text": "Suggest when: the user wants old chats imported; else Profile → Import a chat.",
}
