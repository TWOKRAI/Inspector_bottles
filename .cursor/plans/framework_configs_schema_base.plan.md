---
name: ""
overview: ""
todos: []
isProject: false
---

# Унификация конфигов: SchemaBase во всех модулях

## Зафиксированное решение (итерация плана)

- **Единый принцип**: во фреймворке (`Inspector_prototype/multiprocess_framework/modules`) конфигурационные модели везде на базе `**SchemaBase`** (из `data_schema_module`), без параллельных dataclass-моделей «для совместимости».
- **Обратная совместимость не цель**: старые пути (`LogConfig` dataclass и т.п.) **не сохраняем ради совместимости**; последующая переделка прототипа и вызывающего кода под новую структуру ожидаема. Технический долг от «двух миров» намеренно **не** накапливаем.
- **Следствие**: миграция — это **ломающее изменение**: обновляются менеджеры, тесты, прототип v2, примеры; `model_dump()` / явные адаптеры на границе `dict` по правилам Dict at Boundary.

### Зафиксировано (формат configs / «и так везде»)

- **Канонический файл в модуле** — стиль как `[error_module/configs/error_manager_config.py](Inspector_prototype/multiprocess_framework/modules/error_module/configs/error_manager_config.py)`: плоская `SchemaBase`, только поля + `FieldMeta` + `register_schema`, **без** методов `build()` и без ручной сборки вложенных dict/«списков» внутри конфига.
- **Удалить** `[error_module/configs/error_config.py](Inspector_prototype/multiprocess_framework/modules/error_module/configs/error_config.py)`: там `ChannelRoutingConfig` + кастомный `build()` (ручной merge severity-каналов) — этот паттерн **не используем**.
- **Один публичный класс конфига** на модуль (например переименовать `ErrorManagerSchema` → `ErrorManagerConfig` в том же файле, что остаётся), экспорт из `[error_module/__init__.py](Inspector_prototype/multiprocess_framework/modules/error_module/__init__.py)` только оттуда.
- **Поведение**, которое раньше давал `error_config.build()` (merge `critical_file` / `errors_file` / `warnings_file` с `channels`), переносится в **рантайм**: `[ErrorManager](Inspector_prototype/multiprocess_framework/modules/error_module/core/error_manager.py)` и/или `[normalize_config](Inspector_prototype/multiprocess_framework/modules/channel_routing_module/core/config_normalizer.py)`, чтобы на границе по-прежнему уходил полный `dict` с ключом `channels`, совместимый с текущим менеджером.
- **Тот же принцип по всем модулям**: где есть второй файл «с логикой сборки» в `configs/` — убрать дубликат, оставить плоский `SchemaBase`; любую неизбежную сборку — в `core/` (менеджер, нормализатор), не в схеме.

## Контекст (из предыдущей оценки)

- Опорный паттерн для **полей** в `configs/`: [error_manager_config.py](Inspector_prototype/multiprocess_framework/modules/error_module/configs/error_manager_config.py) (не [error_config.py](Inspector_prototype/multiprocess_framework/modules/error_module/configs/error_config.py) — подлежит удалению). Для каналов см. также [console_process_config](Inspector_prototype/multiprocess_framework/modules/console_module/configs/console_process_config.py).
- Logger сейчас — исключение: [log_config.py](Inspector_prototype/multiprocess_framework/modules/logger_module/core/log_config.py) на dataclass; это **первичная цель** унификации.
- Корневая сборка `proc_dict['managers']` остаётся композицией секций из модулей; прототип наследует/тонко расширяет схемы фреймворка.

## Область работ (модули)

По мере внедрения — в каждом затронутом модуле:

- `configs/` (или согласованное имя; привести к одному стилю где разбросано `config/` vs `configs/`) с публичными схемами на `SchemaBase`.
- Менеджеры принимают `dict` на границе; внутри — парсинг в Pydantic-схему модуля (уже в духе существующих правил).
- Убрать дубли: наследование от `ChannelRoutingConfig` там, где это менеджеры с каналами (см. ADR-016).

**Приоритет миграции**: `logger_module` → остальные модули с «легаси» конфиг-типами → корневая схема сборки `managers` (например в `process_module` или согласованном месте) → `multiprocess_prototype_v2` (наследники вроде `*ConfigLite`).

## Документация и контроль качества

- Запись в [DECISIONS.md](Inspector_prototype/multiprocess_framework/DECISIONS.md) (новое ADR: единый SchemaBase для конфигов модулей, breaking migration).
- Обновление `STATUS.md` затронутых модулей.
- `python scripts/validate.py` после изменений.

## Todos

- **error_module (эталон итерации)**: удалить `error_config.py`; оставить/доработать `error_manager_config.py` как единственный `ErrorManagerConfig`; перенести merge severity-каналов в `ErrorManager` / `normalize_config`; обновить тесты и импорты.
- Специфицировать целевые классы для logger (плоский `SchemaBase` в `configs/` по тому же принципу) и поля channels/scopes/modules; убрать dataclass `LogConfig` где мешает; обновить `LoggerManager`, тесты.
- Пройтись по модулям: в каждом **один** плоский конфиг в `configs/` без дублирующих «сборщиков»; унифицировать `configs/` vs старые пути.
- Ввести/обновить корневую схему сборки `managers` на импортах из модулей.
- Обновить `multiprocess_prototype_v2` (например `managers_schema_lite.py`, YAML) под новые типы.
- DECISIONS + STATUS + validate.

