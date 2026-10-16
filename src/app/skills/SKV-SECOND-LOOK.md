# SKV-SECOND-LOOK
This is a step, not a reminder. Call it before the user sees the answer.
POST /api/v7/agent/second-look with user_id, draft, event_id, span.
Four checks:
constitution: the turn is saved
critical: a wide topic is not treated as one turn
creative: offer one other reading, do not add a fact
hallucination: the draft cites the opened event
If status is fail, fix and call again. If pass, put the seal and output.
