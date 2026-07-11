# fanin — корреляционные буферы DataReceiver (fan-in / join)

Доменные (vision-inspection) буферы, коррелирующие входящие items перед processing-цепочкой.
Переехали из `multiprocess_framework/modules/process_module/generic/` (C6 шаг b): это
уровень 2 «Платформа» (домен), а не уровень 1 «Механизм» — их словарь (`camera_id`,
`region_name`, `seq_id`, `data_type`) специфичен для инспекции, не для фреймворка.

## Публичный API

| Символ | Назначение |
|--------|-----------|
| `InspectorManager` | Буферизация items по `(camera_id, seq_id)` для region fan-in (trigger — `total_regions`). Без fan-in → немедленный pass-through. |
| `JoinInspectorManager` | Корреляция N именованных входов по `(seq_id, data_type)` (напр. `frame`+`overlay`). Left-join по primary + auto-passthrough неактивных входов. |
| `build_inspector(app_cfg, log_*)` | Фабрика: выбирает буфер по `app_cfg["inspector"]["mode"]` (`fanin` \| `join`). |

## Контракт (Protocol `ItemInspector`)

Оба класса реализуют структурный контракт
`process_module.generic.inspector_registry.ItemInspector`:

- `on_item(item: dict) -> None` — принять item; при готовности коллекции зовёт `_on_ready`.
- `check_timeouts() -> None` — периодический flush просроченных/неполных коллекций.
- `pending_count: int` — незавершённые коллекции в буфере (телеметрия).

`_on_ready` (доставка готовой коллекции) выставляется вызывающим извне —
`GenericProcess._init_data_pipeline` ставит `inspector._on_ready = receiver.on_items_ready`.

## DI-шов с framework

Framework (уровень 1) не импортирует этот модуль (правило слоёв). Связь — через реестр:
импорт пакета (`Plugins/__init__` → `Plugins._shared.fanin`) вызывает
`register_inspector_factory(build_inspector)`. `GenericProcess` получает буфер через
`inspector_registry.build_inspector(...)`. Без Plugins-слоя framework падает на безопасный
`PassThroughInspector` (без fan-in).

Любой процесс с processing-плагинами грузит плагин из `Plugins.*` → исполняет
`Plugins/__init__` → фабрика зарегистрирована ДО `_init_data_pipeline`.

## Тесты

`tests/` — юнит `InspectorManager`/`JoinInspectorManager` (характеризационные, перенесены
без правки ожиданий) + `test_factory.py` (parity выбора буфера + self-register в реестр).
