---
description: "Run the docs-writer agent (Haiku) for simple docs: docstrings, README, STATUS. Call for routine documentation."
---

Launch the **docs-writer** agent (subagent_type: "docs-writer", model: haiku).

Give it:
1. Which files to document
2. What exactly: docstrings, README, STATUS.md (DECISIONS.md, ADR and ARCHITECTURE go to `tech-writer`, not here)
3. Context: "Language rules: project-rules §6"

After it finishes:
- Briefly check the documentation quality
- Show the user what was updated

What to document: $ARGUMENTS
