---
date: 2026-04-30
topic: GenericProcess + Plugin System (Phase 1-5)
machine: Windows
branch: refactor/flatten-structure
---

## Session goal

Эволюция от захардкоженных процессов к конфигурируемому конструктору. Вместо папки с 6 файлами на каждый процесс — плагины с контрактами, каталог, SchemaBase-чертёж системы.

## Done

- **Phase 1** (5492ab5): GenericProcess + ProcessModulePlugin + PluginContext + PluginConfig. 3 плагина (capture, color_mask, render) + demo_generic.py
- **Phase 2** (eb6c7aa): Port (SchemaBase, MIME-dtype + shape) + PluginRegistry + @register_plugin. Валидация совместимости портов, фильтр compatible_with()
- **Phase 3** (abc80c1): SystemBlueprint + ProcessConfig + Wire — всё SchemaBase. blueprint.check() валидирует порты и wire-связи до запуска. Auto-wiring внутри процесса
- **Phase 4** (f2c9ee4): State machine (IDLE→READY→RUNNING→PAUSED→STOPPED). Авторегистрация команд плагинов в CommandManager. GenericProcess = тонкий контейнер
- **Phase 5** (30548a0): PluginMetrics (автозамер lifecycle + команд). PluginTestBench (тестирование без ProcessModule)
- **Vision doc**: workspace/dev/vision_generic_process_constructor.md — полный план с индустриальными аналогами (GStreamer, NiFi, UE, Node-RED, ROS2)

## What did NOT work

- **Django-style SystemBlueprint** (class с Process-атрибутами) — красиво для глаз, но не SchemaBase = не сериализуемый, не редактируемый в UI. Заменён на SchemaBase-версию в Phase 3
- **model_dump() в blueprint** — PluginConfig-объекты терялись при сериализации в dict, теряя типы. Решено через _restore_plugin_configs() которая ищет config-модуль рядом с plugin
- **Имя метода validate()** конфликтовало с Pydantic BaseModel.validate() — переименован в check()

## Key decisions made

- **Единый интерфейс** для всех плагинов (source/processing/output) — различаются категорией, не API. Тяжёлые (capture) и лёгкие (blur) — один интерфейс, разная глубина lifecycle
- **SchemaBase насквозь** — всё SchemaBase: Port, PluginConfig, ProcessConfig, SystemBlueprint, Wire. Это главное конкурентное преимущество перед GStreamer/NiFi
- **Плагины в backend/plugins/** — единая папка для всех (source, processing, output)
- **ProcessingNode должен стать плагином** — два механизма для одного = франкенштейн. Plugin поглощает ProcessingNode
- **AppConfig → SystemBlueprint** — Blueprint заменяет, не дополняет

## Next step

Phase 6: UI-интеграция — каталог плагинов в SystemTopology, редактирование чертежа в таблицах, визуализация цепочки с портами. Начать с добавления секции "Plugins" в SystemTopology tab.

## Files changed

Framework (multiprocess_framework/modules/process_module/):
- plugins/__init__.py, base.py, port.py, registry.py, metrics.py, test_bench.py
- generic/__init__.py, generic_process.py, generic_process_config.py, blueprint.py
- __init__.py (lazy-экспорт)

Prototype (multiprocess_prototype/):
- backend/plugins/ — capture/, color_mask/, render/, blueprints/
- demo_generic.py

Docs:
- workspace/dev/vision_generic_process_constructor.md
