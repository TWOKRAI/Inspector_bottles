---
description: Create a new agent from the template — the "HR function"
---

Create a new agent for the development team.

1. Ask the user (or take from $ARGUMENTS):
   - **Name** of the agent (English, hyphenated: `api-specialist`)
   - **Role** — what it will do (1-2 sentences)
   - **Model:** alias — opus (architecture/review), sonnet (implementation/tests), haiku (documentation/simple), fable (short verdicts). A dated ID — only for a deliberate pin.
   - **Tools:** read-only (`Read, Glob, Grep`) or full (`Read, Write, Edit, Glob, Grep, Bash`); or omit `tools:` entirely (inheritance) — then a read-only role requires `disallowedTools:` with Write, Edit, NotebookEdit and the MCP mutators
   - **Constraints** — what it must NOT do

2. Read the template: `.claude/plugins/core/templates/agent.template.md`

3. Create the file `.claude/plugins/core/agents/<name>.md` from the template, filling in all fields
   (next to the seed agents; to survive an `upgrade` — add it directly to the canonical seed `plugins/<id>/`)

4. Optionally create a command `.claude/plugins/core/commands/<name>.md` for a quick `/name` call

5. Run the linter and rebuild the factory — a new file in `plugins/<id>/agents/`
   isn't visible to Claude Code until it's materialized:
   ```bash
   uv run --no-project python .claude/plugins/core/scripts/lint_agents.py .claude/plugins/core/agents --strict
   claude-kit-claude plugin sync .
   ```

6. Show the user the created agent and how to call it (materialized
   agents are picked up by a new session, not the current one)

Data for the new agent: $ARGUMENTS
