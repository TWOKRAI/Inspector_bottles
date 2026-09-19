---
description: Cold start the environment — Ollama serve + venv check (cross-platform)
---

Prepare the project environment after a reboot or from scratch.

## Steps

### 1. Check Ollama (needed for qex embeddings, if qex is used)

```bash
curl -s --max-time 1 http://localhost:11434/ 2>/dev/null | grep -q running && echo "ollama: UP" || echo "ollama: DOWN"
```

If `DOWN`:
- **macOS:** launch `ollama serve` via the Bash tool with `run_in_background=true`
- **Linux:** same
- **Windows:** `ollama serve` via the Bash tool with `run_in_background=true` (Git Bash required)
- Wait 2-3 seconds and check again.

If `ollama` is not installed — print the install command for the platform:
- macOS: `brew install ollama`
- Linux: `curl -fsSL https://ollama.com/install.sh | sh`
- Windows: `winget install Ollama.Ollama` or https://ollama.com/download

### 2. Check the embedding model is present

Platform-dependent model (see `.claude/plugins/mcp-qex/qex-launcher.py`):
- macOS / Linux: `qwen3-embedding:8b` (4096 dim)
- Windows: `qwen3-embedding:4b` (2560 dim)

```bash
ollama list
```

If the needed model is missing — suggest `ollama pull qwen3-embedding:{8b|4b}`.

### 3. Check the venv

Search:
- macOS / Linux: `.venv/bin/python` or `venv/bin/python`
- Windows: `.venv\Scripts\python.exe` or `venv\Scripts\python.exe`

If found — show the activation command (but do NOT activate it yourself — Claude Code runs each Bash call in a fresh sub-shell):
- macOS / Linux: `source .venv/bin/activate`
- Windows (cmd): `.venv\Scripts\activate.bat`
- Windows (PowerShell): `.venv\Scripts\Activate.ps1`

If there's no venv — suggest `uv sync --group dev`.

### 4. Final summary

| Component | Status |
|-----------|--------|
| Ollama daemon | UP / DOWN / not installed |
| Embedding model | loaded / missing |
| venv | found / not found |
| qex MCP | working (if `mcp__qex__get_indexing_status` is available) |

If qex shows `indexed: false` or the index is older than 7 days — recommend `/mcp-qex:qex-reindex`.

## Project override

If `.claude/modes/_stack.md` has a "Cold start" section — follow it in addition (e.g. the project may need a DB, Redis cache, etc. started).

$ARGUMENTS
