---
description: Slice the graphify graph at a module boundary — who depends on the module, what it depends on, and whether the snapshot is stale
---

A slice of the `graphify-out/graph.json` graph at a module boundary — before a refactor, so you
can see the blast radius without noise from homonyms in unrelated modules.

```bash
uv run --no-project python .claude/plugins/mcp-graphify/scripts/graph_slice.py --list                 # which modules the graph has
uv run --no-project python .claude/plugins/mcp-graphify/scripts/graph_slice.py <module>               # incoming / outgoing edges
uv run --no-project python .claude/plugins/mcp-graphify/scripts/graph_slice.py <module> --symbol .flush()
uv run --no-project python .claude/plugins/mcp-graphify/scripts/graph_slice.py <module> --format json
```

Reading rules:
- «КТО ЗАВИСИТ ОТ МОДУЛЯ» is the list of those you'll affect; an empty list for a **method** does not mean "nobody depends on it": the graph attaches calls to the owning class, and the script warns about this. <!-- lint-language: allow -->
- The slice checks `built_at_commit` against HEAD and the working tree: a `stale` line means the graph is outdated — run `graphify update .` first, then trust the output.
- Module containers default to `src/<X>`; a different layout — `--containers a,b` or the `GRAPH_SLICE_CONTAINERS` env var.

No graph → the script itself points you to `graphify build .`. The graphify MCP server is not needed: the JSON is read directly.

$ARGUMENTS
