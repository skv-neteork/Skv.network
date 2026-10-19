# SKV-SEARCH
Before every answer, POST /api/v7/memory with user_id and query_text.
Write the memory search query in English; keep names, rare words and exact terms as-is.
Rewrite first: names, places, rare words in. A phrase is the answer. A rare word may be the answer.
The center is the answer. l1_before and l1_after are the sides. If span is large, one turn is not the whole topic.
If fragments is empty, previous is only a side door. Open an earlier repeat with GET /api/v7/event/{id}.
After three misses on something important, POST /api/v7/memory/dig. If not_found, say you do not know.
Weak agents that can only open a URL: GET /api/v7/agent/memory?key=YOUR_KEY&query=...
