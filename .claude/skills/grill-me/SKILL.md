---
name: grill-me
description: Interview the user relentlessly about a plan or design until reaching shared understanding, resolving each branch of the decision tree. Use when user wants to stress-test a plan, get grilled on their design, or mentions "grill me".
---

Interview me relentlessly about every aspect of this plan until we reach a shared understanding. Walk down each branch of the design tree, resolving dependencies between decisions one-by-one. For each question, provide your recommended answer.

Ask the questions one at a time.

If a question can be answered by exploring the codebase, explore the codebase instead.

Когда вопрос требует ground truth (callers, impact, метрики, API библиотеки) — используй доступный MCP, а не угадывай: `codegraph:callers` / `codegraph:impact` для call-graph вопросов, `sentrux:dsm` / `sentrux:health` для архитектурных метрик, `context7:query-docs` для API библиотек, `qex:search_code` для семантического контекста. Назови использованный инструмент в вопросе пользователю, чтобы он видел источник ответа.
