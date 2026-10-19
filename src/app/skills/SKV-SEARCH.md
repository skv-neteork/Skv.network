# SKV-SEARCH
Before every answer, POST /api/v7/memory with user_id and query_text.
Write the memory search query in English; keep names, rare words and exact terms as-is.
Rewrite first: names, places, rare words in. A phrase is the answer. A rare word may be the answer.
The center is the answer. l1_before and l1_after are the sides. If span is large, one turn is not the whole topic.
If fragments is empty, previous is only a side door. Open an earlier repeat with GET /api/v7/event/{id}.
After three misses on something important, POST /api/v7/memory/dig. If not_found, say you do not know.
Weak agents that can only open a URL: GET /api/v7/agent/memory?key=YOUR_KEY&query=...

## Memory v2 (agent view, opt-in)
Send view=agent and a stable session_id. The first call of a conversation returns memory_map (who, projects, topics), windows (raw -> L1 -> L2, no overlap), critical and the compact constitution. Later calls return hits and lens only.
Send interact=true on the first memory call of each user turn; extra lookups in the same turn use probe=true (no step, no duty).
hits[0] is the center. lens.clusters are separate episodes: the first is full (before, after, L1, L2), the rest are brief. Expand one with POST /api/v7/memory/lens {"focus_event_id": "..."}; page with lens_offset=more_cursor.
Budgets: budget_raw, budget_l1, budget_l2, budget_map, budget_hits, budget_lens (tokens; the server caps them).
GET-only agents: GET /api/v7/memory/start?key=YOUR_KEY&session_id=... then GET /api/v7/agent/memory?key=YOUR_KEY&query=...&view=agent
