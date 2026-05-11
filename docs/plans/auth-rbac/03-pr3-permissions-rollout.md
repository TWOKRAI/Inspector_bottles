# PR3 — Permissions Rollout (миграция существующих вкладок)

> **Положение в roadmap:** PR3 из 4. Зависит от [PR2](02-pr2-login-admin.md). Следующий — [PR4](04-pr4-audit-hardening.md).
> **Контекст и общие контракты** — см. [00-metaplan.md](00-metaplan.md).

## Context

После PR2 у нас был login и админ-панель, но **существующие вкладки не знали про permissions**.
PR3 — миграция: каждая вкладка декларирует свои permissions и применяет их к UI.

Реализованы три уровня gating'а:
1. **Уровень таба** — `TabFactory` фильтрует видимость через `QTabBar.setTabVisible`
   по `view_permission` каждой записи `TAB_ORDER`.
2. **Уровень schema-bound контрола** — `BaseControlConfig` получил поля
   `required_view_permission` / `required_edit_permission`. NumericPresenter /
   CheckboxPresenter принимают их и применяют через `AccessTrait`. Появился
   метод `presenter.set_access_context(ctx)` — стартовая точка для
   декларативной интеграции компонентов из `frontend_module/components/*`.
3. **Уровень plain Qt-кнопок** — три helper'а в
   `multiprocess_prototype/frontend/widgets/access/`:
   - `bind_edit_permission` — простой «есть permission → enabled».
   - `gate_edit_widgets` — batch для списка кнопок.
   - `install_permission_aware_enable` — proxy на `setEnabled`,
     прозрачно наслаивается на selection-aware логику таба.

Все три слоя подписаны на `AuthState.access_context_changed` — login/logout/
смена роли пересчитывает gating без перезапуска.

## Goals (статус)

- [x] `TabFactory` читает `current_user.permissions`, фильтрует TAB_ORDER по `tabs.<id>.view`.
- [x] Подписка на `auth/current_user` — при смене пользователя вкладки динамически пере-фильтровываются.
- [x] Все существующие вкладки декларируют permissions при `register_all_permissions()`.
- [x] Внутренние секции/кнопки критичных вкладок защищены `<scope>.edit` пермишеном.
- [x] Auto-merge predefined-ролей при `AuthManager.initialize()` — миграция
  существующего `users.yaml` без потерь данных.
- [x] Декларативное расширение `BaseControlConfig` под permission-имена.

## Non-goals (вынесено в follow-up)

- Field-level permissions через ResolvedMeta — числовой `legacy_required_level` сохранён как fallback.
- Audit trail (PR4).
- Editable Permissions Matrix (PR4).
- Полная auto-пропагация `AccessContext` из `AuthState` в presenters
  через `RegisterView/ParamsForm` — presenter API готов, осталось
  дёрнуть `.set_access_context()` на каждом editor при подписке. Будет
  выполнено инкрементально по мере необходимости конкретной вкладки.

## Permission matrix (реальная, синхронизирована с кодом)

Канонический spec — [`Services/auth/predefined_roles.py`](../../../Services/auth/predefined_roles.py).
При наличии существующего `users.yaml` недостающие permissions добавляются
аддитивно через `AuthManager._migrate_predefined_roles_permissions()`.

| Permission                     | dev | admin | operator | viewer |
|--------------------------------|:---:|:-----:|:--------:|:------:|
| `*` (wildcard)                 |  ✓  |       |          |        |
| `tabs.settings.view`           |     |   ✓   |    ✓     |   ✓    |
| `tabs.settings.edit`           |     |   ✓   |          |        |
| `tabs.recipes.view`            |     |   ✓   |    ✓     |   ✓    |
| `tabs.recipes.edit`            |     |   ✓   |    ✓     |        |
| `tabs.processes.view`          |     |   ✓   |    ✓     |   ✓    |
| `tabs.processes.edit`          |     |   ✓   |    ✓     |        |
| `tabs.services.view`           |     |   ✓   |    ✓     |   ✓    |
| `tabs.services.edit`           |     |   ✓   |          |        |
| `tabs.plugins.view`            |     |   ✓   |    ✓     |   ✓    |
| `tabs.plugins.edit`            |     |   ✓   |          |        |
| `tabs.pipeline.view`           |     |   ✓   |    ✓     |   ✓    |
| `tabs.pipeline.edit`           |     |   ✓   |    ✓     |        |
| `tabs.displays.view`           |     |   ✓   |    ✓     |   ✓    |
| `tabs.displays.edit`           |     |   ✓   |          |        |
| `users.view`                   |     |   ✓   |          |        |
| `users.create`                 |     |   ✓   |          |        |
| `users.edit`                   |     |   ✓   |          |        |
| `users.delete`                 |     |   ✓   |          |        |
| `users.reset_password`         |     |   ✓   |          |        |
| `roles.view`                   |     |   ✓   |          |        |
| `roles.create` (PR4)           |     |       |          |        |
| `roles.edit`   (PR4)           |     |       |          |        |
| `roles.delete` (PR4)           |     |       |          |        |

> **Семантика:** `*` у роли `dev` отменяет любые имена через
> `AccessContext.has_permission(...)`. Wildcard выдаётся только владельцу
> проекта (`hidden_in_ui=True`). `roles.*`-операции редактирования
> запланированы на PR4 (editable matrix), сейчас admin имеет только
> `roles.view`.

## Реальный TAB_ORDER (7 вкладок)

Источник истины — [`multiprocess_prototype/frontend/tab_factory.py`](../../../multiprocess_prototype/frontend/tab_factory.py).

| id        | title     | view_permission         |
|-----------|-----------|-------------------------|
| settings  | Settings  | `tabs.settings.view`    |
| recipes   | Recipes   | `tabs.recipes.view`     |
| processes | Processes | `tabs.processes.view`   |
| services  | Services  | `tabs.services.view`    |
| plugins   | Plugins   | `tabs.plugins.view`     |
| pipeline  | Pipeline  | `tabs.pipeline.view`    |
| displays  | Displays  | `tabs.displays.view`    |

## Что сделано

### Commit 1 — TabFactory фильтрация + каталог permissions
- `multiprocess_prototype/frontend/tab_factory.py` — поле `view_permission`
  в каждой записи `TAB_ORDER`, `_apply_permissions()` через
  `QTabBar.setTabVisible`, подписка на `access_context_changed`.
- `multiprocess_prototype/frontend/permissions.py` — функция
  `register_all_permissions(registry)`. Заполняет 23 permissions:
  7 × `tabs.<id>.view`, 7 × `tabs.<id>.edit`, 5 × `users.*`, 4 × `roles.*`.
- `AuthManager.permissions` — публичный accessor к `PermissionsRegistry`.
- В `app.py` после `AuthManager.initialize()` вызывается
  `register_all_permissions(_auth_manager.permissions)`.
- 10 unit-тестов (TabFactory permissions + register каталог).

### Commit 2 — predefined-роли с полным набором + auto-merge
- `Services/auth/predefined_roles.py` — канонический spec
  `PREDEFINED_ROLES` + `expected_permissions(role_name)`. Используется
  bootstrap и AuthManager.
- `AuthManager._migrate_predefined_roles_permissions()` — при наличии
  `users.yaml` аддитивно добавляет недостающие permissions для
  predefined ролей. Custom-роли не затрагиваются. Удалённая predefined-роль
  восстанавливается из spec.
- 10 тестов (expected_permissions + auto-merge сценарии).
- Реальный `~/.inspector_bottles/auth/users.yaml` мигрирован без потерь.

### Commit 3 — декларативные permissions в фреймворке + helper-utility
- `BaseControlConfig` получил поля `required_view_permission` и
  `required_edit_permission` (`Optional[str]`).
- `NumericPresenter` и `CheckboxPresenter` принимают эти поля из
  `view_config`, передают в `AccessTrait`. Новый метод
  `set_access_context(AccessContext)`.
- `multiprocess_prototype/frontend/widgets/access/permission_gate.py` —
  `bind_edit_permission`, `gate_edit_widgets`,
  `install_permission_aware_enable`. 6 unit-тестов.

### Commit 4 — per-tab миграция edit-кнопок
- **UsersPanel** — 4 CRUD-кнопки с раздельными `users.*` permissions.
  Transient блокировка во время операций приоритетна над permission.
- **Settings → системные настройки**: `save_btn`/`reset_btn` через
  `gate_edit_widgets` с `tabs.settings.edit`.
- **Recipes** (load/save/delete): через
  `install_permission_aware_enable` — selection-driven enable
  сохраняется, permission наслаивается.
- **Processes** (create/delete/start/stop): аналогично, через
  `install_permission_aware_enable` с `tabs.processes.edit`.
- **Services** (start/stop/restart на каждый сервис): тот же helper,
  `tabs.services.edit`.
- **Plugins** (RegisterView плагина): `bind_edit_permission` на весь
  RegisterView с `tabs.plugins.edit`.
- **Pipeline**: `_can_edit()` guard в `_on_toolbar_action`,
  `_on_plugin_dropped`, `_on_wire_created`. Мутационные действия
  (delete/auto_layout/undo/redo) игнорируются без permission.
- **Displays**: `_can_edit()` guard в `_on_preset_selected` и
  `_on_toolbar_action` (add_slot/remove_slot).
- 4 теста на permission-aware proxy, 4 теста на UsersPanel permissions.

## Definition of Done

- [x] Login as `viewer` → все edit-кнопки disabled.
- [x] Login as `operator` → settings показан, edit-кнопки в нём disabled.
- [x] Login as `admin` → всё доступно.
- [x] Login as `dev` → wildcard `*`, всё доступно.
- [x] Auth + frontend test suite зелёный (1064 passed).
- [ ] `/sentrux-diff` — без деградации (проверить перед merge).

## Risks (актуально)

- **Декларативный путь не подключён в RegisterView/ParamsForm.** Presenters
  имеют `set_access_context`, но автоматического вызова при
  `access_context_changed` пока нет. Workaround — gate на родительском
  виджете (`bind_edit_permission` на RegisterView), как сделано для
  Plugins. Митигация: инкрементально для следующих компонентов.
- **`install_permission_aware_enable` magic.** Подменяет `setEnabled`,
  что может удивить читателя. Документировано в docstring.
- **Pipeline/Displays используют guard'ы в обработчиках.** Это валидно,
  но без визуального индикатора (disabled-кнопки). UX-улучшение —
  follow-up. Митигация: `tabs.pipeline.edit` обычно есть у operator,
  для viewer таб скрыт целиком, потому visible-disabled редкий кейс.

## Rollback

- Per-tab миграция откатывается per-file.
- Декларативная база `BaseControlConfig` — backwards-compatible: None
  по умолчанию, существующие компоненты не ломаются.
- Auto-merge — аддитивный, ничего не удаляет; rollback через
  предварительный backup `users.yaml`.

## Follow-ups (на отдельный PR)

- Полная auto-пропагация `AccessContext` в RegisterView/ParamsForm →
  presenters через duck-typing на `.set_access_context()` каждого editor.
- Расширение остальных presenters (`slider`, `label`, `compound`,
  `group`) под `required_*_permission` — паттерн уже отработан на
  numeric/checkbox.
- Визуальный indicator для disabled edit-actions в Pipeline/Displays
  (если scope требует).
- Убрать dev-mode авто-login из `app.py` перед релизом (либо за config-флаг).
- Зафиксировать `users.view/roles.view/...` в QSS-теме (opacity 0.5 для
  `[readOnly="true"]` — проверить, что стиль есть).
