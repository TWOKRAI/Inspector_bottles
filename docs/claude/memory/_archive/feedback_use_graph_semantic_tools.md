---
name: feedback-use-graph-semantic-tools
description: "Владелец ожидает активного использования qex/codegraph/serena/graphify, не только через Explore-агентов"
metadata:
  node_type: memory
  type: feedback
  originSessionId: 82ad289c-65e8-4577-b5ec-2891866a2fd0
---

Владелец (2026-07-08) заметил, что я мало использую MCP-инструменты кода:
qex (семантический поиск), codegraph (граф символов), serena (LSP-символы),
graphify (граф знаний).

**Why:** проект специально настроил эти инструменты (qex-first / sentrux-first
правила в CLAUDE.md); они дают точнее и дешевле ответ «где используется X»,
«кто шлёт это сообщение», чем grep+read.

**How to apply:**
- В оркестраторском цикле для вопросов «где/кто использует» звать
  `mcp__qex__search_code` и `mcp__codegraph__codegraph_explore` НАПРЯМУЮ, а не
  только делегировать Explore-агентам (которые сами решают, чем искать).
- Для архитектуры/связей — `mcp__sentrux__dsm`/`check_rules` (sentrux я использую).
- **Ф4 (контракты сообщений) — идеальный кейс**: «кто шлёт command X / читает schema Y»
  = ровно запросы к qex/codegraph. Начинать контракт-маппинг с них.
- Оговорка: qex требует `ollama serve` (в начале сессии был DOWN — тогда недоступен;
  проверять статус в SessionStart-хуке).
- Связанная фидбэк-запись про стиль работы: [[feedback-auto-mode-preference]].
