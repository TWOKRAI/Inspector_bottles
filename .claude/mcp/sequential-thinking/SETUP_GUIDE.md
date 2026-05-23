# sequential-thinking — Setup Guide

Minimal install — one npm package, one MCP config block, no project state. ~2 minutes.

> Source: <https://github.com/modelcontextprotocol/servers/tree/main/src/sequentialthinking>

---

## Prerequisites

- **Node.js 18+** on PATH. Verify: `node --version`.
- No browser binaries, no database, no language servers — pure reasoning tool.

> If your machine has no Node yet — see Playwright's SETUP_GUIDE prerequisites; same instructions.

---

## 1. Wire the MCP server (zero-install recommended)

Append the snippet from [`templates/mcp-config.json.snippet`](templates/mcp-config.json.snippet)
to project's `.mcp.json` under `mcpServers`:

```json
{
  "sequential-thinking": {
    "command": "npx",
    "args": ["-y", "@modelcontextprotocol/server-sequential-thinking"]
  }
}
```

Zero-install — `npx -y` downloads on first run, caches afterwards. No global package needed.

If you prefer global install:

```bash
npm install -g @modelcontextprotocol/server-sequential-thinking
```

```json
{
  "sequential-thinking": {
    "command": "mcp-server-sequential-thinking"
  }
}
```

---

## 2. Restart Claude Code and smoke-test

1. Reload Claude Code window.
2. `/mcp` shows `sequential-thinking` as connected.
3. Smoke test — give the agent a problem that benefits from structured reasoning:

   ```
   I have a flaky test that fails ~30% of the time. The test asserts that
   process_request() returns 200 within 2 seconds. The function makes an HTTP
   call to an internal service. Use sequential-thinking to enumerate possible
   root causes and rank them.
   ```

   Expected: agent calls `sequentialthinking` multiple times — thought 1/N "could be timing",
   thought 2/N "could be flaky upstream", revision of thought 1 etc. If agent skips the tool
   and goes straight to a guess — re-pin tool routing (see § 3).

---

## 3. Pin routing in agent .md (already done in seed)

`investigator.md` and `teamlead.md` are pre-configured with conditional routing:

> "Если sequential-thinking подключён + гипотеза >3 этапов → sequentialthinking для
> externalization цепочки."

You don't need to edit them after install — the routing block reads `.mcp.json` conditionally.

---

## 4. Cost awareness

`sequentialthinking` calls expand the conversation. Rough estimate for an investigator session:

- Without seq-thinking: ~50-80 tool calls (read/grep/qex), ~30k tokens.
- With seq-thinking on a hard bug: +10-20 tool calls explicit thoughts, +5-10k tokens.

This is a deliberate trade-off — externalized reasoning is auditable and revisable, but it
costs. Don't enable it project-wide if your typical task is routine.

---

## Troubleshooting

### `/mcp` shows sequential-thinking as failed

Almost always a Node / npx PATH issue (the package is trivial; problems are environmental):

```bash
node --version       # need 18+
npx --version
which npx           # is it on PATH that Claude Code sees?
```

### Tool ignored even when relevant

Routing wasn't pinned, or the task description didn't trigger conditional. Workaround:
in the user message, explicitly ask: "use sequentialthinking to think this through".

---

## Uninstall

```bash
# If installed globally:
npm uninstall -g @modelcontextprotocol/server-sequential-thinking

# Zero-install version: nothing to uninstall (it's just an npx cache)
```

Remove the `sequential-thinking` block from `.mcp.json` and restart Claude Code.

---

## Security notes

- No file system access, no network, no execution — `sequentialthinking` is pure reasoning
  scaffolding. Safe by default.
- The thought sequence persists only in the current conversation context, no on-disk state.
