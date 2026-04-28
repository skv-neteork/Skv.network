# SKV v1.8 - AI Protocol Enforced

## 🤖 Why this version exists

Previous versions failed because AIs didn't know **how** to submit data correctly (forgot links, forgot privacy).

## 🔐 The Strict Protocol

Any AI accessing `/api/v1/info` receives this instruction:

1.  **Ask Privacy:** "Save anonymously or under name?"
2.  **Include Fields:** `submission_url` and `attribution` MUST be in the root of the JSON.
3.  **Provide Link:** Explicitly give the user the URL to open.

## 📦 Example JSON Structure

```json
{
  "skv_version": "1.0",
  "submission_url": "http://localhost:8000/api/v1/entries",
  "attribution": {"mode": "anonymous"},
  "user_fields": { ... }
}
```

This ensures that the JSON is **self-contained** and **self-routing**.