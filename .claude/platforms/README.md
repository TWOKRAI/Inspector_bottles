# Platform-specific configs

Machine-specific configs that differ between macOS and Windows.
Active configs (`.claude/mcp.json`, `.claude/settings.local.json`) are gitignored.

## Setup

Copy the config for your platform:

**macOS:**
```bash
cp .claude/platforms/mcp.macos.json .mcp.json
cp .claude/platforms/settings.local.macos.json .claude/settings.local.json
```

**Windows (Git Bash):**
```bash
cp .claude/platforms/mcp.windows.json .mcp.json
```

> **Важно:** файл `.mcp.json` лежит в **корне проекта**, не в `.claude/`.

### Post-copy checklist
- [ ] Verify qex binary exists: `which qex` (macOS) or `ls ~/.cargo/bin/qex.exe` (Windows)
- [ ] Verify Ollama running: `curl -s http://localhost:11434/ | grep running`
- [ ] Test MCP: restart Claude Code, check status line shows no MCP errors

### Important
- Server name is `qex` on BOTH platforms (agents reference `mcp:qex:search_code`)
- WORKSPACE_PATH = project root (full vault, not just apps/)
- qex 0.0.2 (feature `vector`) — Docker/Qdrant не нужны, вектора хранятся в `~/.qex/`

## MCP zones (future, Phase 3)

Single `qex` server indexes full vault today. Planned zones to add later:
- `qex-projects` — `projects/` (all portable projects)
- `qex-knowledge` — `knowledge/wiki/`
- `qex-areas-work` — `areas/work/`
- `qex-areas-study` — `areas/study/`

Each zone = separate `mcpServers.*` entry with own `WORKSPACE_PATH`.

## Original locations

These files were extracted from:
- `mcp.json` → `.claude/mcp.json` (was tracked in git, now gitignored)
- `settings.local.json` → `.claude/settings.local.json` (was tracked in git, now gitignored)
