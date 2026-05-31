---
name: project-backend-control-mcp
description: План MCP-driver параллельно GUI — общение с бэкендом ТОЛЬКО через RouterManager
metadata:
  type: project
---

План `plans/2026-05-31_backend-control-mcp/plan.md` (зона infra/tooling, ветку `feat/backend-control-mcp` создать при старте P1). Замысел владельца: MCP-сервер параллельно GUI — отрабатывать бэкенд напрямую через MCP (целиться/слать/читать), не сражаясь с qt-mcp; отлаживать фронт и бэк раздельно, не гадать «где проблема».

**P0 recon ✅ DONE (2026-05-31).** 4/5 допущений зелёные; request-response жёлтый (prerequisite): ответ `_handle_process_command` шлётся без `targets` (process_manager_process.py:876) → теряется. Источники интроспекции (command_manager.get_commands / message_dispatcher.get_all_handlers / registers_manager.model_dump_all / get_all_processes_status) уже есть — P1 тонкая обёртка.

**ПЕРЕСМОТР ТРАНСПОРТА (решение владельца 2026-05-31):** НЕ driver-процесс-в-графе, а **`SocketChannel(MessageChannel)` в RouterManager** (сиблинг QueueChannel, by-design `register_channel` — router_manager.py:458) + тонкий ВНЕШНИЙ driver-модуль, который подключается к сокету и шлёт те же Message/dict, что GUI по queue. Хост канала — ProcessManager (accept-loop в WorkerManager-потоке), НЕ новый сиблинг-процесс. JSON wire (кадры/SHM не гоняем). Совпадает с transport-router-hub P3 (ещё один IMessageChannel), не плодит второй транспорт.

**Фазы (обновлено):** P0.5 prerequisite request-response (framework, ~130 строк) · P1 generic `introspect.handlers/registers/status` (паттерн worker.*) · P2 **SocketChannel + внешний driver** (вместо driver-в-графе) · P3 MCP-обёртка. Handoff: `plans/2026-05-31_backend-control-mcp/HANDOFF.md`.

Мотивация: диагностика Этапа 2 = ~30 шагов qt-mcp, а `introspect.handlers` показал бы блокер мгновенно. НО продукт (live-параметры) уже работает БЕЗ тулинга (resize-ретрофит 4327ccf8) → driver = ускорение отладки, не критический путь, держать тонким. Dev-гейт `BACKEND_CTL=1` + localhost.

Связано: [[project-transport-router-hub]] (транспорт, на котором ездит driver; P0-P2 на ветке), [[project-pipeline-live-control-stage2]] (фича, которую driver'ом быстрее добить), [[feedback-constructor-modularity]].
