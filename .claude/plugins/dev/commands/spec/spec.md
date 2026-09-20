---
description: Create or update the living spec (docs/direction/) for the app — a product specification from the user's point of view
---

Launch the **spec-writer** agent (subagent_type: "spec-writer").

Determine the mode of operation:

### Mode 1: CREATE (no arguments, or a path to the application)
If an application path is given, or docs/direction/ doesn't exist — create from scratch.

Pass to the agent:
1. Application path
2. Mode: CREATE
3. Context: "Read CLAUDE.md, study all the application's files, create a complete set of docs/direction/ files"

### Mode 2: UPDATE (after code changes)
If docs/direction/ already exists and the code has changed — update it.

Pass to the agent:
1. Application path and docs/direction/
2. Mode: UPDATE
3. Which code files changed (from git diff or the conversation context)
4. Context: "Update only the affected sections of docs/direction/"

### Mode 3: SYNC (the user edited a direction file)
If the user says they edited a direction file — read it and output the code changes needed.

Pass to the agent:
1. Path to the changed direction file
2. Mode: SYNC
3. Context: "Compare the direction file with the code, output the list of code changes needed"

After completion:
- Show the user what was created/updated
- If SYNC mode — show the list of code changes and ask whether to apply them

Arguments: $ARGUMENTS
