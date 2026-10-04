---
description: Create the memory directory skeleton (MEMORY.md) for a new project. Owner-run, once per project.
disable-model-invocation: true
---

**Memory dir** (`<memory_dir>` below): the `memory_dir` key in the ini block of `.claude/modes/_stack.md`; absent → `.claude/memory`. Read it first; never assume `.claude/memory/`.

One-time initialization of the long-term memory structure. Run **once** for a new project created via `claude-kit new` (or manually).

## Idempotency

If `<memory_dir>/MEMORY.md` already exists — **do nothing**, report "memory already initialized" and show `/core:memory:status`.

## Steps

1. Create the `<memory_dir>/` folder if it doesn't exist.
2. Create `<memory_dir>/MEMORY.md` — **copy the content from the bundled
   seed template** (single source of truth). Don't type the skeleton by hand,
   to avoid drifting from the canonical version.
   - A new project created via `claude-kit new` already gets `<memory_dir>/MEMORY.md`
     automatically (bootstrap materializes the skeleton from the plugin) — this step is
     only needed for manual bootstrap or an existing project without `<memory_dir>/`.
   - Copy the whole file from the canonical plugin skeleton:
     `cp <claude-kit>/src/claude_kit_claude/template/plugins/core/memory/MEMORY.md <memory_dir>/MEMORY.md`
     (the canonical plugin path; the old monolith `claude_kit` path is deprecated).
3. If `<memory_dir>/` contains only `.gitkeep` — delete it (the folder is no longer empty).
4. Suggest the next step:
   - `/core:memory:status` — check the state.
   - The first entries will be added **automatically** per the "auto memory" rules from the system prompt: each entry is a separate `.md` file with frontmatter, plus a line in the `MEMORY.md` index in the format `- [Title](file.md) — hook`.

## Don't

- Don't copy other projects' memory entries.
- Don't create example entries — let memory fill in organically.
