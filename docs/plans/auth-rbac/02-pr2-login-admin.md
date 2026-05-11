# PR2 — Login Flow + Administration UI (basic)

> **Положение в roadmap:** PR2 из 4. Зависит от [PR1](01-pr1-foundation.md). Следующий — [PR3](03-pr3-permissions-rollout.md).
> **Контекст и общие контракты** — см. [00-metaplan.md](00-metaplan.md).

## Context

После PR1 backend готов. В PR2 строим UI: глобальный login в `chrome/toolbar`,
подвкладку `Settings → Администрация` с двумя панелями («Пользователи» и «Роли»),
интеграцию с `state_store.auth/current_user`.

**Важно:** в PR2 матрица пермишенов **read-only** (показывает предустановленные роли,
не редактируется). Редактируемая matrix — в PR4 после audit'а (изменение прав требует
аудита для compliance).

## Goals

- `LoginButton` в chrome/toolbar — кнопка «Войти» / «<имя> ▾» с меню (Logout, Сменить пароль).
- `LoginDialog`, `ConfirmWithPasswordDialog`.
- Подвкладка `Settings → Администрация` — `AdministrationSection` с `SideNavLayout`:
  «Пользователи» / «Роли».
- `UsersPanel`: список + таблица + кнопки + inline `UserForm` (создание/редактирование).
- `RolesPanel`: список ролей + **read-only** `PermissionMatrix`.
- Интеграция `state_store.auth/current_user` ↔ `WindowManager.update_access_context`.
- До login — мутации заблокированы UI-диалогом «Требуется вход».

## Non-goals

- Audit log / sessions panel (PR4).
- Editable PermissionMatrix (PR4).
- Применение permissions к существующим вкладкам (PR3).

## Files

**Создать:**
- `multiprocess_prototype/frontend/widgets/chrome/login_button.py`
- `multiprocess_prototype/frontend/widgets/dialogs/login_dialog.py`
- `multiprocess_prototype/frontend/widgets/dialogs/confirm_with_password.py`
- `multiprocess_prototype/frontend/widgets/tabs/settings/administration/`:
  - `__init__.py`, `section.py`, `users_panel.py`, `user_form.py`, `roles_panel.py`, `permission_matrix.py`
- `multiprocess_prototype/registers/user_register.py`, `role_register.py` (опционально — даёт интеграцию с RegisterView).
- `multiprocess_prototype/frontend/actions/middleware/pre_auth_guard.py` — middleware для блокировки мутаций до login.

**Изменить:**
- [multiprocess_prototype/frontend/widgets/tabs/settings/tab.py](../../../multiprocess_prototype/frontend/widgets/tabs/settings/tab.py) — заменить `_build_placeholder("administration")` на `AdministrationSection`.
- [multiprocess_prototype/frontend/app_context.py](../../../multiprocess_prototype/frontend/app_context.py) — внедрить `IAuthManager`.
- [multiprocess_prototype/run.py](../../../multiprocess_prototype/run.py) — инициализация `AuthManager`, проверка bootstrap.
- `multiprocess_prototype/frontend/theme/` — QSS правило `*[readOnly="true"] { opacity: 0.5; }`.
- [multiprocess_prototype/frontend/actions/bus_factory.py](../../../multiprocess_prototype/frontend/actions/bus_factory.py) — регистрация `PreAuthGuard` middleware.

## Steps

1. **`LoginButton`** (MVP: View+Presenter):
   - View: QPushButton с текстом «Войти» / «<имя> ▾» + popup-меню.
   - Presenter: подписан на `state_store.subscribe("auth/current_user", ...)`, обновляет view.
2. **`LoginDialog`** — QDialog с `QLineEdit` (username) + `QLineEdit(echoMode=Password)` + OK/Cancel.
   - При OK → `auth_manager.login(...)`. Ошибка → диалог через `ErrorManager`.
   - Success → state_store обновляется → `WindowManager.update_access_context(...)` → все окна перерисовываются.
3. **`ConfirmWithPasswordDialog`** — для destructive действий. Если current_user не admin, требует ввод admin-пароля (`auth_manager.verify_admin_password`).
4. **`AdministrationSection`** (root subtab):
   - `SideNavLayout` с двумя секциями: «Пользователи», «Роли».
   - Permissions check: `users.view` / `roles.view`.
5. **`UsersPanel`** (по образцу `RecipesTab`):
   - Layout: `QListWidget` (logins) | `QStackedWidget` (Cards/Table view) | панель кнопок справа.
   - Таблица колонки: `Логин | Роль | Создан | Последний вход | Кол-во входов | Активен`.
   - Кнопки: «Добавить», «Удалить», «Сбросить пароль», «Изменить роль», `ViewModeToggle`.
   - «Добавить» → раскрывается inline `UserForm` ниже таблицы.
   - «Удалить» → `ConfirmWithPasswordDialog`.
   - «Сбросить пароль» → подтверждение → `auth_manager.reset_password` → показ нового пароля в alert'е (одноразово, копируется в clipboard).
6. **`UserForm`** — генерируется через `ParamsForm` по `User`-схеме (SchemaBase + FieldMeta).
   Поля: username, password (validate по `PasswordPolicy`), role_name (Combo из существующих ролей), is_active.
7. **`RolesPanel`:**
   - Layout аналогичный.
   - Read-only список ролей + read-only `PermissionMatrix` (две колонки чекбоксов: View / Edit).
   - Кнопки disabled в PR2 (включаются в PR4).
8. **Pre-auth блокировка мутаций (`PreAuthGuard` middleware):**
   - В `ActionBus`: до login любой `WriteAction` → блокируется, показ диалога «Требуется вход».
   - Read actions (`FieldGet`/`StateRead`) пропускаются.
   - Каждая вкладка декларирует `requires_auth: bool` (default True). До login видны только вкладки с `requires_auth=False`.
9. **CLI bootstrap** (`python -m Services.auth.bootstrap` уже создан в PR1) — проверить интеграцию в `run.py`: если `users.yaml` отсутствует и нет `INSPECTOR_DEV_PASSWORD`, при старте показать сообщение в UI «Запустите python -m Services.auth.bootstrap».
10. **UI auto-тесты на pytest-qt:** UsersPanel CRUD, LoginDialog success/fail, ConfirmDialog logic.

## Definition of Done

- [ ] `/run-proto` запускается, видна кнопка «Войти» в toolbar.
- [ ] Login → редактируемые контролы появляются; logout → блокируются.
- [ ] Создание/удаление пользователя через UI работает; YAML на диске обновлён атомарно.
- [ ] До login — попытка мутации показывает «Требуется вход».
- [ ] Reset пароля показывает новое значение одноразово, копируется в clipboard.
- [ ] pytest-qt тесты — зелёные.
- [ ] `/sentrux-diff` — без деградации.
- [ ] PR-описание с скриншотами login/users/roles панелей.

## Risks

- **Многооконный режим:** если приложение имеет ≥1 окна, `WindowManager.update_access_context` должен пройти по всем. Проверить в smoke.
- **pytest-qt в CI:** может потребоваться `xvfb-run` на Linux-runner'ах.
- **bcrypt latency ~100мс:** login через UI thread → если заметно, обернуть в `QThread.run`.

## Rollback

- Восстановить заглушку `_build_placeholder("administration")` в settings/tab.py.
- Удалить новые виджеты, `LoginButton` из chrome.
- Backend в `Services/auth/` остаётся (без UI он безвреден).
