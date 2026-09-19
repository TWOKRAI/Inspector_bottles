---
description: Run the Docs-Writer agent (Haiku) — write/update documentation
---

Launch the **docs-writer** agent (subagent_type: "docs-writer", model: haiku).

Give it:
1. Which files to document
2. What exactly: docstrings, README, STATUS.md, DECISIONS.md
3. Context: "Read CLAUDE.md for the language rules"

After it finishes:
- Briefly check the documentation quality
- Show the user what was updated

What to document: $ARGUMENTS
