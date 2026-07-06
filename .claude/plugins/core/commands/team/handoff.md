---
description: Create a session handoff document for cross-machine context transfer.
---

Create a session handoff document for cross-machine context transfer.

## What to do

Write a structured handoff file to `docs/handoffs/` with today's date and topic.

**Filename:** `docs/handoffs/YYYY-MM-DD_{topic-slug}.md`

**Template:**

```markdown
---
date: YYYY-MM-DD
topic: {short description}
machine: {Windows or macOS — detect from environment}
branch: {current git branch}
---

## Session goal
{What was the user trying to accomplish}

## Done
- {Achievement 1}
- {Achievement 2}

## What did NOT work
- {Dead end 1 — why it failed}
- {Dead end 2 — why it failed}

## Key decisions made
- {Decision 1 — rationale}

## Next step
{Single clear action for the next session}

## Files changed
{List of files modified in this session — from git status}
```

## Algorithm

1. Run `git status` and `git diff --stat` to see what changed
2. Review the conversation history — summarize goal, achievements, dead ends
3. Detect current machine (check for `/Users/` = macOS, `C:\Users\` = Windows)
4. Create `docs/handoffs/` directory if it doesn't exist
5. Write the handoff file
6. Tell the user: "Handoff saved. On the other machine, run: `git pull` then start a new session."

## Important

- The "What did NOT work" section is MORE valuable than "Done" — it prevents re-exploring dead ends
- Be specific about dead ends: what was tried, why it failed, what error occurred
- The "Next step" must be a single unambiguous action, not a list
- $ARGUMENTS can optionally specify the topic slug
