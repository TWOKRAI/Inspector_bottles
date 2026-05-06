# multiprocess_prototype_2 — Мета-план

## Цель

Чистый config-driven прототип на базе фреймворка-конструктора.
Никаких хардкод-процессов — только GenericProcess + плагины + JSON topology.

## Принципы

1. **Инкрементально.** Каждый файл согласовываем перед созданием.
2. **Профессиональная оценка.** Оцениваем что было в прототипе v1 → улучшаем → best practices.
3. **Фреймворк — живой конструктор.** Если не хватает — предлагаем изменения во фреймворк.
4. **UI переносим с улучшением.** Верстку и UX сохраняем, внутренности рефакторим.

## Архитектурные решения

| Решение | Обоснование |
|---------|-------------|
| SchemaBase везде | Единый стандарт сериализации, UI-совместимость |
| YAML topology + config | Комментарии, человекочитаемость, единый формат |
| config/system.yaml = defaults | Одно место для всех базовых значений |
| topology/*.yaml = структура + overrides | Что запускать + отличия от defaults |
| bootstrap.py в main.py | Сборка без магии (без `__import__`, без динамических путей) |
| PluginRegistry.discover() | Автоскан плагинов по директории |
| Нет subprocess в run.py | Прямой вызов main.main() после venv-exec |

## Фазы

| Фаза | Статус | Описание |
|------|--------|----------|
| Phase 0 | ✅ DONE | Foundation — heartbeat plugin, proof of boot |
| Phase 1 | ✅ DONE | Camera — capture plugin, SHM, frame flow |
| Phase 2 | ✅ DONE | Processing — граф обработки, wire-совместимость |
| Phase 3 | ✅ DONE | Output — сохранение результатов (DB/файлы) |
| Phase 4 | ✅ DONE | GUI базовый — 3 таба (Camera, Controls, Topology) |
| Phase 5 | ✅ DONE | Data Pipeline — рефакторинг GenericProcess, region pipeline |

### >>> MASTER_PLAN.md — Фазы 6-14 (пересоздание v1 в v2 архитектуре)

> **v1 — АРХИВ (только чтение).** Все плагины и GUI пересоздаются в v2.

| Фаза | Статус | Описание | Задач |
|------|--------|----------|-------|
| Phase 6 | 🔲 TODO | **Plugin Migration** — пересоздание всех плагинов v1 в v2 | 10 |
| Phase 7 | 🔲 TODO | Registers v2 — автогенерация из plugin config_schema | 3 |
| Phase 8 | 🔲 TODO | StateStore + реактивность | 3 |
| Phase 9 | 🔲 TODO | GUI Foundations — MainWindow layout из v1 + DI + стили | 4 |
| Phase 10 | 🔲 TODO | GUI Tabs — Sources, Processing, Processes, Settings, Display | 6 |
| Phase 11 | 🔲 TODO | Recipes + Presets + Undo/Redo | 3 |
| Phase 12 | 🔲 TODO | TopologyBridge v2 — GUI ↔ Runtime синхронизация | 3 |
| Phase 13 | 🔲 TODO | Pipeline Editor — визуальный конструктор topology | 4 |
| Phase 14 | 🔲 TODO | Polish + Production Ready | 5 |
| | | **Итого** | **41** |

Детали: [`MASTER_PLAN.md`](MASTER_PLAN.md)

## Что вынести во фреймворк

| Компонент | Источник | Статус |
|-----------|----------|--------|
| SHM Cleanup утилита | prototype/backend/shm/cleanup.py | 🔲 |
| StateStore bootstrap-скелет | prototype/state_store/bootstrap.py | 🔲 |
| Frame throttle middleware | prototype/backend/routing/ | 🔲 проверить |

## Структура проекта

```
multiprocess_prototype_2/
├── run.py              # точка входа (venv-aware)
├── main.py             # bootstrap: config → plugins → topology → launcher
├── config/             # конфигурация (defaults)
│   ├── system.yaml     # глобальные defaults по секциям
│   └── schemas.py      # Pydantic-валидация SystemConfig
├── plans/              # планы по фазам
├── plugins/            # плагины приложения
│   ├── heartbeat/      # ✅ Phase 0
│   ├── capture/        # ✅ Phase 1 — cv2 → SHM → IPC
│   ├── frame_counter/  # ✅ Phase 1 — приёмник frame_ready
│   ├── grayscale/      # ✅ Phase 2 — BGR → Grayscale
│   ├── color_mask/     # ✅ Phase 2 — HSV маска
│   ├── database/       # ✅ Phase 3 — SQLite batch storage
│   └── frame_saver/    # ✅ Phase 3 — кадры на диск
├── topology/           # YAML-описания систем (структура + overrides)
│   ├── archive/               # архив ранних topology
│   ├── camera_grayscale.yaml  # ✅ Phase 2
│   ├── camera_color_mask.yaml # ✅ Phase 2
│   └── phase3_pipeline.yaml   # ✅ Phase 3 (fan-out)
└── (будущее: frontend/, registers/, services/)
```
