---
name: project_command_result_bridge
description: command-result-bridge DONE — GUI получает реальный результат дискретных команд (request/response); разблокирует lifecycle + pipeline-Этап3
metadata:
  type: project
---

**command-result-bridge ЗАВЕРШЁН** (2026-06-07). Keystone request/response GUI→PM: дискретные команды (активация рецепта, start/stop/restart, replace_blueprint) идут request/response — GUI узнаёт реальный результат; высокочастотный field-write остаётся fire-and-forget.

- **P1** `deae8b91` — `CommandSender.request_command/request_system_command` + `IRequestingProcess` + timeout 30s (framework).
- **P2** `e9e29f71` — `RequestRunner` (QThreadPool + Signal/AutoConnection, паттерн `DataReceiverBridge`) + `ProcessManagerProxy.*_async(on_result)` (prototype). Результат маршалится в main-thread сигналом.
- **P3** `c4894133` — presenter активации рецепта показывает success/error (non-modal); по ходу починен каскад крашей горячей замены.
- **P4** закрыт по существу: тяжёлый ADR признан дублем транспортного ADR-005 + auto-reply note; GUI-специфика зафиксирована в **frontend_module DECISIONS FE-004**; интеграция покрыта существующими тестами + `backend_ctl` (PM-сторона round-trip).

**Why:** GUI слал команды вслепую (активация рецепта молча падала/успевала). Один keystone request/response снял неведение и стал фундаментом для двух направлений.

**How to apply:** мост готов — [[project_pipeline_live_control_stage2]] Этап 3 (live-применение «применилось ли») и lifecycle-прогресс (TRH P4.4.4) строятся поверх того же канала (`request(on_progress=...)`). НЕ переводить field-write на request (блокировка hot-path). См. [[project_recipe_hotswap]].
