# Контролы (components) — архитектура и расширение

## Зачем отдельный слой

Пакеты контролов (`base`, `checkbox`, `examples`, …) лежат непосредственно под `frontend_module.components`
(раньше — вложенный `control_v2/`). Legacy `controls/` и shim-импорты удалены.

Составной UI приложения — `frontend_module.widgets`.

## Универсальные слои (как добавить компонент)

1. **Контракты** (`base/interfaces.py`): при необходимости расширить протоколы `IControlView[T]`, `INumericView` или ввести новый порт под тип значения.
2. **View**: чистый Qt (или другой UI), методы `setup`, `set_value` / `set_value_silent`, `get_value`, сигналы через `on_changed` / `on_finished`.
3. **Presenter**: композиция traits (`SyncTrait`, `SchemaTrait`, `AccessTrait`, …), `BindingConfig` + `RegisterAdapter`; опционально `ControlHooks`.
4. **Config**: `dataclass` с `merge_config` / defaults в `defaults.py`.
5. **Facade**: статический `create(parent, registers_manager, binding, …)` — собирает View + Presenter, подписки, `LegacySyncContext` при необходимости.

Числовые контролы переиспользуют `group/labeled_numeric_factory.create_labeled_numeric_view`, чтобы не тянуть циклические импорты между `slider`, `spinbox` и `group.view`.

## Примеры для приложения

Подкаталоги `examples/<имя>/` повторяют шаблон **ADR-066**:

- `schemas.py` — `SchemaBase` для UI и для регистра, константы `BINDING_*` на классе регистра;
- `adapter.py` — только преобразование схем во `BindingConfig` / `*ViewConfig` и вызов фасада в `components` (slider, checkbox, …);
- `__init__.py` — публичный экспорт для тестов и копипасты в приложение.

В `examples/` общий модуль не используется: каждый адаптер дублирует короткий `coerce_ui` и явный `BindingConfig`.

## Связанные документы

- `README.md` — обзор дерева и диаграммы;
- `base/README.md` — порты, traits, инфраструктура;
- `DECISIONS.md` в корне refactored — ADR по hooks, фабрике групп, примерам.
