# Recon P4 — актуализация call-sites на текущем коде (2026-06-05)

> Investigation-first перед декомпозицией P4 (read-only). Источник: investigator-агент,
> сверка на коде после P0–P3.1. **Главный вывод: P4 значительно легче манифеста —
> 3 из 5 пунктов уже закрыты предыдущими фазами / comm-system §11.**

## Сводка по пунктам

| Пункт | Манифест | Реальность 2026-06-05 | Объём | Риск |
|---|---|---|---|---|
| **P4.1** CommandSender ручной dict | «убрать третий способ» | **УЖЕ ЗАКРЫТ** — `CommandSender` делегирует в `message_module/builders/command_envelopes.py` (`build_command_message`/`build_system_command_message`). `RoutedCommandSender` — 0 callers → P5 | 0 | — |
| **P4.2** heartbeat/broadcasts | «→ router.send» | heartbeat УЖЕ через `send_message`→`router.send` (P1.3). Осталось 2 broadcast в `ProcessMonitor` (`broadcast_full_status:538`, `_broadcast_status_change:610`) → идут мимо хаба через `queue_registry.broadcast_message`. **Потребителей 0** → кандидат на УДАЛЕНИЕ (P5.0 gate), не миграцию | 2 | LOW |
| **P4.3** queue_registry/SHM приватные | «вне channels запретить» | Живой «вне channels» путь — только broadcast (см. P4.2). SHM вне middleware: RingBufferWriter/Reader, MemoryHandle (0 callers), ProcessIO (1 legacy caller). ~~Нужно sentrux-правило с whitelist `router_module/middleware/`~~ → **DONE: `scripts/transport_boundary/`** (см. ниже) | 2-3 | LOW |

> **КОРРЕКТИРОВКА P4.3 (реализация 2026-06-05):** sentrux НЕ годится — его правила это
> import-boundaries между путями, а транспорт зовут через атрибут
> `router_manager.queue_registry.send_to_queue(...)` без импорта (call-site, не импорт).
> Реализовано как AST call-site-чекер `scripts/transport_boundary/` + `ci.py`. Whitelist
> шире, чем тут предполагалось: легитим — `router_module/**` (хаб `_deliver_by_targets:322`
> + frame-middleware) И `shared_resources_module/**` (библиотека очередей/SHM), а не
> «channels/+middleware/». ProcessIO к этому правилу не относится — зовёт `send_message`
> (после P1.3 идёт через хаб), прямого SHM/queue не делает. Ратчет: broadcast B7 → `[[debt]]`.
| **P4.4** двойная диспетчеризация | «handler напрямую в message_dispatcher» | **ЖИВАЯ, главная работа P4.** `process_lifecycle.py:104-154 register_commands_with_router` → `_make_command_handler` closure → `cm.handle_command` → `cm.dispatcher.dispatch` (второй dispatch по тому же `msg["command"]`). ~20 команд/процесс | ~20 cmd | **MEDIUM** |
| **P4.5a** один ring-buffer | «слить 2» | FrameShmMiddleware слит в P3.1.1 (`4f4dbb28`). `RingBufferWriter`/`Reader` — отдельный мёртвый класс (0 callers) → P5 изоляция | 0 | — |
| **P4.5b** удалить top-level `frontend/bridge.py` | «затенённый дубль» | **Файла НЕ существует** (ни framework, ни prototype). `bridge/__init__.py` ре-экспортит живой `bridge_impl.DataReceiverBridge`. Закрыто | 0 | — |
| **P4.5c** один набор `state.*` handler | «не дважды» | Предотвращена runtime-guard `auto_register_ipc=False` (`orchestrator.py:76-114`): RAW-handler'ы НЕ регистрируются, wrapped-путь (с `reply_to_request`) занимает ключи первым. Код RAW жив в SSM → чистка в P5. **НЕ ТРОГАТЬ без необходимости** | 0 | — |

## Data-plane кадров (НЕ ТРОГАТЬ)

Горячий путь после P3.1.2: `SourceProducer._send_item:136` → `send_to_process:182` (снимает vestigial `channel:"data"`) → **`FrameShmMiddleware.strip_data_frame_on_send:205`** (SHM-strip, guard `type=="data"+data.frame`) → `_deliver_by_targets:322` (`qr.send_to_queue`) → `DataReceiver:116` → `FrameShmMiddleware.restore_frame:94` → `PipelineExecutor:171` → forward (тот же путь).

Пересечения P4 с горячим путём: только **P4.3** (sentrux-правило обязано whitelist'ить `router_module/middleware/`; `_deliver_by_targets:322` — живой выход кадров). P4.1/P4.2/P4.4/P4.5 — control-plane, кадров не касаются.

## Рекомендованный порядок и rollback

1. **P4.1, P4.5a, P4.5b, P4.5c — закрыты** (отметить в plan.md DONE/переадресовать в P5).
2. **P4.2** (LOW) — broadcast: 0 потребителей → вынести решение «удалить vs оставить» на P5.0 gate (правило владельца). Rollback: один revert `process_monitor.py`.
3. **P4.3** (LOW) — sentrux-правило «нет `send_to_queue`/SHM вне `channels/`+`middleware/`» + приватизация мёртвых SHM-символов (P5). Rollback: revert `rules.toml` + per-symbol.
4. **P4.4** (MEDIUM, главная работа) — убрать двойную диспетчеризацию. Требует: (а) прямая регистрация handler в `message_dispatcher`; (б) **сохранить `reply_to_request` wrapper** (иначе request/response ломается, в т.ч. state.*); (в) решить судьбу `CommandManager` (оставить metadata/tags/timing как реестр или выродить в thin). Regression scope: ВСЕ IPC-команды → integration-тесты + qt-smoke обязательны. Rollback: revert `process_lifecycle.py` (+ `process_module.py`).

## Расхождения с plan.md P4-манифестом

Манифест писался 2026-05-31 до P1–P3.1 и comm-system §11. Половина пунктов закрыта попутно. Реальный P4 = **P4.4 (MEDIUM) + P4.2/P4.3 (LOW)**; остальное — переадресация в P5 (изоляция мёртвого кода после обсуждения с владельцем, правило P5.0).

> **Вход в реализацию P4** (следующая сессия): начать с P4.2/P4.3 (LOW, разогрев + sentrux-инвариант), затем P4.4 (MEDIUM) на чистом контексте. qt-smoke (FPS 21.0) после каждого шага; для P4.4 — полный integration-прогон IPC-команд.
