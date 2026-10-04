---
name: feedback_mcp_tool_api_drift
description: routing-правила/агенты могут описывать устаревший API MCP-сервера — проверять реальный tool-set перед доверием ROUTING.md
metadata:
  type: feedback
---

Перед тем как доверять `ROUTING.md`/routing-блокам агентов про конкретный MCP — **проверить реальный tool-API живого сервера** (вызвать tool или посмотреть список инструментов сессии). Правила и установленный пакет дрейфуют независимо.

**Why:** codegraph в проекте — это `@colbymchenry/codegraph` v0.4.x с ОДНИМ tool `codegraph_explore` (verbatim source + call path + blast-radius за вызов), а ROUTING.md и все 8 dev-агентов описывали устаревший 8-тульный API (`callers`/`callees`/`impact`/`context`/`files`/`search`/`node`/`status` от другого пакета). Агент, звавший `codegraph:impact`, падал бы на несуществующий tool → откат на дорогую Grep-петлю. «Правильный подход» был прописан, но недостижим.

**How to apply:** при работе с MCP-роутингом — сверять canonical refs в ROUTING.md с фактическими именами tools сервера; `lint_routing.py` ловит только `mcp:server:tool`-форму, прозаичные `server:tool` в агентах он НЕ проверяет, поэтому дрейф молча живёт. Fix жил в `.claude/plugins/core/mcp/ROUTING.md` + `plugins/dev/agents/*` (+ composed `agents/dev/*`) + `mcp-codegraph/README|SETUP_GUIDE`. Дубль-write в devseed: правит `src/claude_kit_claude/template/…` (applied `.claude/` там gitignored). Связано с [[feedback_use_graph_semantic_tools]].
