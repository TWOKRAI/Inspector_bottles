---
name: project-backend-control-mcp
description: План MCP-driver параллельно GUI — общение с бэкендом ТОЛЬКО через RouterManager
metadata:
  type: project
---

План `plans/2026-05-31_backend-control-mcp/plan.md` (зона infra/tooling, ветку `feat/backend-control-mcp` создать при старте P1). Замысел владельца: MCP-сервер параллельно GUI — отрабатывать бэкенд напрямую через MCP (целиться/слать/читать), не сражаясь с qt-mcp; отлаживать фронт и бэк раздельно, не гадать «где проблема».

**Решение владельца (2026-05-31):** общение driver↔бэкенд ТОЛЬКО через RouterManager, без сайд-каналов. Следствие архитектуры: RouterManager живёт по процессу + shared queue_registry → driver = **процесс-сиблинг GUI в графе** (спавнится ProcessManager). MCP-сокет = ТОЛЬКО граница Claude↔driver; request-response внутрь и обратно — через RouterManager (correlation_id).

**Фазы:** P0 recon+ADR (как driver крепится к RouterManager; заодно закрывает open-вопрос Этапа 2 — штатна ли доставка GUI→произвольный worker) · P1 generic `introspect.handlers/registers/status` в процессах (паттерн worker.* из process_module/commands/builtin_commands.py) · P2 driver-процесс + thin API (send_command/introspect_*/set_register) · P3 MCP-обёртка (инструменты против живого бэкенда).

Мотивация доказана: диагностика Этапа 2 заняла ~30 шагов qt-mcp, а `introspect.handlers(preprocessor)` показал бы блокер (нет приёмника register_update) мгновенно. Reuse CommandSender/ProcessManagerProxy/RouterManager — не изобретать. Dev-гейт `BACKEND_CTL=1`.

Связано: [[project-transport-router-hub]] (транспорт, на котором ездит driver; P0-P2 на ветке), [[project-pipeline-live-control-stage2]] (фича, которую driver'ом быстрее добить), [[feedback-constructor-modularity]].
