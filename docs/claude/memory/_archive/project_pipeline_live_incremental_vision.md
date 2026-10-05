---
name: project-pipeline-live-incremental-vision
description: Видение владельца на live-применение Pipeline — инкрементально per-process, НЕ full-replace
metadata:
  type: project
---

**Видение владельца на Этап 2/3 pipeline-live-control (2026-05-31, зафиксировано перед новым чатом):**

Live-применение правок графа должно быть **инкрементальным per-process**, НЕ перезапуском всей цепочки:

1. **Изменение параметра плагина:** правка внизу графа → сообщение в RouterManager с иерархическим АДРЕСОМ (процесс → воркер → плагин) + ключ + значение. Адрес известен из привязки ноды. Reuse: `SetPluginConfig` live-путь (app.py:476-490), дорастить до worker+plugin.

2. **Добавление ноды:** слать процессу команду «создать воркер» / «добавить плагин в воркер» (по последовательности). **Процесс применяет на следующей итерации.** Соседние процессы НЕ перезапускаются.

**Почему это правильнее:** мой вариант «replace_blueprint целиком, debounced» надёжен, но моргает всей цепочкой на каждую правку. Владелец явно выбрал инкрементальный путь.

**Тупик, которого избегать:** `apply_topology_diff` / `build_hot_add_process` несут только ОДИН plugin_name → не собирают многоплагинную ноду. НЕ использовать для добавления.

**Уже готово (reuse):** per-process команды `worker.create/remove/update/restart/stop` в `process_module/commands/builtin_commands.py` (процесс мутирует воркеры без рестарта себя) — основа «добавить ноду = создать воркер». Плюс SetPluginConfig для параметров.

Полный контекст: `plans/2026-05-31_pipeline-live-control/HANDOFF_etap2.md`. Связано: [[project_pipeline_live_control_stage1]], [[project_hierarchical_addressing]], [[project_workers_architecture]], [[project_transport_router_hub]] (P3 = транспортная сторона).
