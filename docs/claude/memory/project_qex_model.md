---
name: qex-embedding-model-by-platform
description: "qex embedding per platform — macOS qwen3-embedding:8b-qex/4096 since 2026-09-13 (was 4b), Windows 0.6b/1024; independent indexes; Ollama silent-CPU trap"
metadata: 
  node_type: memory
  type: project
  originSessionId: 8e123388-1fab-41a2-84bc-01f9efc1477d
  modified: 2026-09-13T12:47:50.365Z
---

Each machine has its own `~/.qex/` index and its own model; no symmetry required (owner's choice 2026-05-10). Source of truth for the model: `.claude/plugins/mcp-qex/qex-launcher.py`; `reindex.py` and `reindex_progress.py` MUST match it (dim mismatch silently degrades hybrid search to BM25).

## macOS (M2 Max 32 GB)
- **Since 2026-09-13 (owner's decision):** `qwen3-embedding:8b-qex`, dim 4096, num_ctx 4096 — variant created from `templates/qwen3-embedding-8b-mac.Modelfile` via `setup-embedding-model.sh`. Reason: 500k+ LOC plus many Russian docs; 8b better on multilingual (MMTEB ~70.6 vs ~69.5), code gap <1%.
- History: 4b/2560 from 2026-07-05 (2x speed); before that LM Studio MLX 8B.
- Full rebuild 2026-09-13: 3431 files → 45982 chunks; ~4.6 s per Ollama request, estimated ~4 h.
- Throughput measured 2026-09-13 on GPU: 8b ~1.5 chunks/s (1200-char chunks), 4b ~1.7 under Low Power Mode. Low Power Mode on battery throttles the GPU — rebuild only on AC with `powermode 0`.

## Trap: Ollama.app silently on CPU
From 2026-08-21 to 2026-09-13 Ollama.app logged `failure during GPU discovery … timeout` at startup and ran every model on CPU (`offloaded 0/37 layers`, 4b at 0.4 chunks/s). Nothing errors. Check: `grep "inference compute" ~/.ollama/logs/server.log | tail -1` must say `library=Metal`. Fix: restart Ollama.app (quit via menu may prompt; `pkill -TERM` on the app + `open -a Ollama` works).

## Windows (RTX 3050 Laptop, 4 GB VRAM)
- `qwen3-embedding:0.6b`, dim 1024 since 2026-08-27 (4b did not fit VRAM).

**How to apply:** after changing the model, restart every Claude Code session (running qex MCP servers keep the old env) and do a full `reindex_progress.py --clear --force`.
