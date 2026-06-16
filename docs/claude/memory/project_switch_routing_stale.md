---
name: project_switch_routing_stale
description: После switch рецепта параметры молча не доходят — стейл-PSR GUI (старые очереди); фикс через PM-хаб
metadata:
  type: project
---

**Root cause (HIGH, 2026-06-16):** живой тюнинг параметров молча перестаёт работать ПОСЛЕ горячего переключения рецепта (помогает только перезапуск приложения). Причина: каждый процесс держит pickle-КОПИЮ `ProcessStateRegistry` (PSR) с объектами `multiprocessing.Queue`. GUI **protected, не пересоздаётся** при switch; PM создаёт пересозданным процессам НОВЫЕ очереди, а PSR GUI остаётся со СТАРЫМИ (мёртвыми). `register_update` идёт GUI→процесс напрямую через стейл-PSR GUI (`QueueRegistry.send_to_queue` → `get_queue("vision")` → старая очередь → `put_nowait` → мёртвый pipe → `return True`) → **тихая потеря**. Сырой `mp.Queue` НЕЛЬЗЯ переслать через работающую очередь → «дослать очереди в GUI» невозможно.

**Это НЕ коллизия set_config** (та гипотеза опровергнута состязательной проверкой воркфлоу: legacy set_config-путь в проде мёртв, warning'и `Handler 'set_config' already exists` — безобидный boot-шум). Живой путь правки РОВНО ОДИН: domain SetPluginConfig → PluginConfigChanged → app.py → `register_update` → `PluginOrchestrator._on_register_update` (адресация по plugin_name, без коллизий).

**Why:** lifecycle-команды (`process.start/stop`) уже ходят через PM (`send_system_command`→`_handle_process_command`) и работают после switch — PM держит свежие очереди. А live field-write обходит PM напрямую → ломается.

**How to apply:** фикс — маршрутизировать GUI-исходящие live-команды (register_update + action-команды плагинов) ЧЕРЕЗ PM-хаб (GUI→PM→target по свежему PSR PM), reuse `reply_to_request` (ADR-COMM-005, видимая ошибка вместо тихого дропа). НЕ костыли: не «переиспользовать очереди» (небезопасно при terminate — залоченный rlock), не «требовать перезапуск». Доработка существующего транспортного хаба. Полный диагноз: docs/audits/2026-06-16_switch-routing-stale.md.

Связано: [[project_graceful_stop_debt]] (отдельная проблема — лаг switch; стейл-PSR возникает и при чистом стопе), [[project_recipe_hotswap]], [[project_command_result_bridge]], [[feedback_fix_framework_forward]].
