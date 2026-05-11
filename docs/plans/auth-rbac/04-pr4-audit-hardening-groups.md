# PR4 — Группы задач: Audit Trail + Editable Matrix + Hardening

> **Положение в roadmap:** PR4 из 4 (финальный). Зависит от [PR3](03-pr3-permissions-rollout.md).
> Высокоуровневые цели и DoD — в [04-pr4-audit-hardening.md](04-pr4-audit-hardening.md).
> Метаплан, контракты, запреты — в [00-metaplan.md](00-metaplan.md).

---

## Порядок выполнения

```
Group A (бэкенд: модели + хранилище)
  └─► Group B (менеджеры: AuditWriter + SessionTracker + интеграция в AuthManager)
        └─► Group C (UI read-only: SessionsPanel + AuditLogPanel)
              └─► Group D (Editable PermissionMatrix + ActionBus integration)
                    └─► Group E (StatsManager + тесты + DoD + sentrux baseline)
```

---

## Group A — Модели домена и хранилище SQLite

**Сложность:** M  
**Зависит от:** —

### Цель

Добавить `SessionEntry` и `AuditEntry` в `models.py`, создать `SqliteAuditStorage`
поверх `Services/sql.GenericRepository`, обеспечить append-only инвариант.

### Файлы

| Файл | Действие |
|------|----------|
| `Services/auth/models.py` | добавить `SessionEntry`, `AuditEntry` |
| `Services/auth/storage/audit_storage.py` | создать |
| `Services/auth/storage/__init__.py` | экспортировать `SqliteAuditStorage` |
| `Services/auth/tests/test_audit_storage.py` | создать |

### Задачи

1. **`SessionEntry(SchemaBase)`** — `@register_schema("auth_session")`:
   - Поля: `session_id: str` (UUID4), `user_id: str`, `username: str`,
     `login_at: datetime`, `logout_at: Optional[datetime]`, `host: str` (default `"localhost"`).
   - `SQLMeta.table_name = "auth_sessions"`, `SQLMeta.primary_key = ["session_id"]`.
   - Индекс: `(user_id, login_at)`.

2. **`AuditEntry(SchemaBase)`** — `@register_schema("auth_audit")`:
   - Поля: `entry_id: str` (UUID4), `ts: datetime`, `user_id: str`, `username: str`,
     `action_type: str`, `resource: Optional[str]`,
     `before_json: Optional[str]`, `after_json: Optional[str]`,
     `comment: str` (default `""`).
   - `SQLMeta.table_name = "audit_log"`, `SQLMeta.primary_key = ["entry_id"]`.
   - Индекс: `(user_id, ts)`, `(resource, ts)`.
   - `before_json`/`after_json` > 10 KB — усекать, добавлять суффикс `"<truncated>"`.
     Метод-фабрика `AuditEntry.with_truncation(...)` реализует логику.

3. **`SqliteAuditStorage`** — обёртка двух `GenericRepository[T]` (`AuditEntry` + `SessionEntry`):
   - `__init__(db_path: str)` — создаёт SQLAlchemy engine через `Services/sql.EngineFactory`
     (SQLite, `check_same_thread=False`), DDL через `Services/sql.DDLBuilder`.
   - `ensure_schema()` — идемпотентный `CREATE TABLE IF NOT EXISTS` для обеих таблиц
     с индексами.
   - `append_audit(entry: AuditEntry) -> None` — вызывает `repo.insert(entry)`.
   - `append_session(entry: SessionEntry) -> None` — вызывает `repo.insert(entry)`.
   - `close_session(session_id: str, logout_at: datetime) -> None` —
     вызывает `repo.update(session_id, ...)` **только** для поля `logout_at`.
   - `list_sessions(user_id: str, limit: int = 50) -> list[SessionEntry]`.
   - `list_audit(*, user_id: str | None, resource: str | None,
     from_dt: datetime | None, to_dt: datetime | None,
     limit: int = 100, offset: int = 0) -> list[AuditEntry]`.
   - **Override `_AuditEntryRepo.update` и `_AuditEntryRepo.delete`** — raise
     `AuditImmutableError` с кодом `AUTH-007`. `SessionRepository` — без ограничений
     (logout пишет `logout_at`).

4. **`AuthConfig`** — добавить поле `audit_db_path: str = ""` (env `INSPECTOR_AUTH_DB_PATH`).

### Acceptance criteria

- [ ] `SessionEntry` и `AuditEntry` сериализуются через `to_dict()` / `model_validate()` без потерь.
- [ ] `SqliteAuditStorage.append_audit()` → INSERT в `audit_log`; повторный `update()`/`delete()` → `AuditImmutableError`.
- [ ] `ensure_schema()` идемпотентна — повторный вызов не ломает существующую схему.
- [ ] `list_audit` с фильтрами по `user_id` и датам возвращает правильное подмножество.
- [ ] Тесты используют in-memory SQLite (`sqlite:///:memory:`).

### Тесты (Group A)

- `test_audit_storage.py`:
  - `test_append_audit_and_list` — insert + фильтрация.
  - `test_audit_immutable_update` — `AuditImmutableError`.
  - `test_audit_immutable_delete` — `AuditImmutableError`.
  - `test_session_open_close` — insert + update `logout_at`.
  - `test_list_sessions_by_user` — фильтр по `user_id`.
  - `test_ensure_schema_idempotent` — двойной вызов без ошибок.
  - `test_truncation` — `before_json` > 10 KB усекается с суффиксом.

---

## Group B — AuditWriter, SessionTracker, интеграция AuthManager

**Сложность:** M+  
**Зависит от:** Group A

### Цель

Реализовать `AuditWriter` (поток + очередь + JSONL fallback), `SessionTracker`,
подключить их в `AuthManager.login` / `logout`. Добавить `AuditMiddleware` в `ActionBus`.

### Файлы

| Файл | Действие |
|------|----------|
| `Services/auth/audit_writer.py` | создать |
| `Services/auth/session_tracker.py` | создать |
| `Services/auth/interfaces.py` | добавить `IAuditWriter`, `ISessionTracker` |
| `Services/auth/manager.py` | интегрировать `SessionTracker` в `login`/`logout` |
| `Services/auth/__init__.py` | экспортировать новые классы |
| `Services/auth/DECISIONS.md` | добавить Auth-005..Auth-007 |
| `multiprocess_prototype/frontend/actions/middleware/audit_middleware.py` | создать |
| `multiprocess_prototype/frontend/actions/middleware/__init__.py` | экспортировать |
| `multiprocess_prototype/frontend/actions/bus_factory.py` | регистрация `AuditMiddleware` |
| `Services/auth/tests/test_audit_writer.py` | создать |
| `multiprocess_prototype/frontend/actions/middleware/tests/test_audit_middleware.py` | создать |

### Задачи

1. **`AuditWriter(BaseManager, ObservableMixin)`** — `Services/auth/audit_writer.py`:
   - `__init__(storage: SqliteAuditStorage, fallback_path: str)`.
   - Внутренний `queue.Queue[AuditEntry | None]` — None = sentinel stop.
   - Фоновый `threading.Thread` (daemon=True), запускается в `start()`.
   - Воркер: `while True: entry = q.get(); if entry is None: break; _write(entry)`.
   - `_write(entry)`: сначала пишет в `storage.append_audit(entry)`;
     при `Exception` — пишет в `fallback_path` (JSONL, append-mode),
     вызывает `_log_error("auth.audit.write_failed", ...)`.
   - `log(entry: AuditEntry) -> None` — помещает в очередь (non-blocking).
   - `stop()` — помещает `None` в очередь, `thread.join(timeout=5)`.
   - **Batching mitigation:** коммит каждые 100 мс или 50 записей — реализовать
     через `queue.get(timeout=0.1)` + накопление batch + `executemany`.
     _Детальная реализация batch — на усмотрение Developer'а при сохранении контракта._
   - `recover_fallback() -> int` — если `fallback_path` существует: читает JSONL построчно,
     вставляет в storage, архивирует файл (`fallback_path + ".migrated.<ts>"`),
     возвращает количество восстановленных записей. Вызывается из `start()`.

2. **`SessionTracker`** — `Services/auth/session_tracker.py`:
   - `__init__(storage: SqliteAuditStorage)`.
   - `open_session(user_id: str, username: str) -> str` — создаёт `SessionEntry`,
     вызывает `storage.append_session(entry)`, возвращает `session_id`.
   - `close_session(session_id: str) -> None` — `storage.close_session(session_id, datetime.now(utc))`.
   - `current_session_id: str | None` — in-memory (не персистируется между рестартами).
   - Хранить только `current_session_id`; активные сессии не ведутся в памяти
     (для StatsManager — отдельный механизм в Group E).

3. **Интеграция `AuthManager`**:
   - Добавить `_session_tracker: SessionTracker | None = None`,
     `_audit_writer: AuditWriter | None = None`.
   - `set_audit_writer(writer: AuditWriter) -> None` — инжекция извне (DI).
   - `set_session_tracker(tracker: SessionTracker) -> None` — инжекция извне.
   - В `login()` после успеха: `self._session_tracker?.open_session(user_id, username)`.
   - В `logout()`: `self._session_tracker?.close_session(self._current_session_id)`.
   - Сохранить `_current_session_id: str | None` для передачи в `logout`.

4. **`IAuditWriter` и `ISessionTracker`** в `interfaces.py`:
   - `IAuditWriter.log(entry: AuditEntry) -> None`
   - `ISessionTracker.open_session(...) -> str`
   - `ISessionTracker.close_session(session_id: str) -> None`

5. **`AuditMiddleware`** — `multiprocess_prototype/frontend/actions/middleware/audit_middleware.py`:
   - `__init__(audit_writer: IAuditWriter, state_store: Any)`.
   - Метод `__call__(action: Action, result: Any) -> None` — post-execute callback.
   - Извлекает `user_id` и `username` из `state_store.get("auth/current_user")` (dict).
   - Если `user_id is None` — пропускает (pre-auth действий нет из-за PreAuthGuard).
   - Формирует `AuditEntry(ts=datetime.now(utc), user_id=..., username=...,
     action_type=action.action_type, resource=action.register_name или action.field_name,
     before_json=json.dumps(action.backward_patch), after_json=json.dumps(action.forward_patch))`.
   - Вызывает `audit_writer.log(entry)`.

6. **`bus_factory.py`** — добавить опциональный параметр `audit_writer: IAuditWriter | None = None`:
   - При наличии: `bus.add_post_execute_listener(AuditMiddleware(audit_writer, state_store))`.
   - Проверить: `ActionBus` имеет `_log_writer` и `set_log_writer` — это другой механизм
     (для `IActionLogWriter`). Нужен отдельный `add_post_execute_listener` или
     использовать `_change_callbacks` — **Developer выбирает наименее инвазивный способ**
     (предпочтительно новый метод `bus.add_post_execute_callback(cb)` в `ActionBus`).

7. **Auth-005..007 в `Services/auth/DECISIONS.md`** — дописать три ADR согласно Appendix C метаплана.

### Acceptance criteria

- [ ] `AuditWriter.log()` в потоке не блокирует UI-thread (non-blocking queue put).
- [ ] При симуляции падения SQLite (patch storage.append_audit → raise) — `AuditWriter`
  пишет в JSONL, вызывает `log_error`; данные не теряются.
- [ ] `recover_fallback()` мигрирует записи из JSONL в SQLite, архивирует файл.
- [ ] `SessionTracker.open_session` → `SessionEntry` в БД; `close_session` → `logout_at` проставлен.
- [ ] `AuthManager.login()` создаёт сессию; `AuthManager.logout()` закрывает.
- [ ] `AuditMiddleware.__call__` → `AuditEntry` в очереди writer'а.
- [ ] Тест concurrent writes: 5 потоков, по 20 записей каждый → все 100 в БД.

### Тесты (Group B)

- `test_audit_writer.py`:
  - `test_log_and_flush` — записи попадают в storage.
  - `test_fallback_on_storage_error` — JSONL при сбое SQLite.
  - `test_recover_fallback` — миграция JSONL обратно.
  - `test_concurrent_writes` — 5 потоков × 20 записей, нет потерь.
  - `test_stop_flush` — после `stop()` все записи из очереди записаны.
- `test_audit_middleware.py`:
  - `test_middleware_logs_action` — `action` → `AuditEntry` в writer.
  - `test_middleware_skips_no_user` — user_id=None → ничего не пишет.

---

## Group C — UI: SessionsPanel + AuditLogPanel (read-only)

**Сложность:** M  
**Зависит от:** Group B

### Цель

Создать две read-only UI-панели для вкладки «Администрация».
Добавить подсекции «Сессии» и «Audit log» в `AdministrationSection`.

### Файлы

| Файл | Действие |
|------|----------|
| `multiprocess_prototype/frontend/widgets/tabs/settings/administration/sessions_panel.py` | создать |
| `multiprocess_prototype/frontend/widgets/tabs/settings/administration/audit_log_panel.py` | создать |
| `multiprocess_prototype/frontend/widgets/tabs/settings/administration/section.py` | добавить подсекции |
| `multiprocess_prototype/frontend/widgets/tabs/settings/administration/tests/test_sessions_panel.py` | создать |
| `multiprocess_prototype/frontend/widgets/tabs/settings/administration/tests/test_audit_log_panel.py` | создать |

### Задачи

1. **`SessionsPanel(QWidget)`**:
   - Конструктор `__init__(ctx: AppContext, parent=None)`.
   - `QTableWidget` с колонками: «Пользователь», «Вход», «Выход», «Длительность», «Хост».
   - Данные загружаются через `ctx.audit_storage().list_sessions(user_id=..., limit=50)`.
   - Если текущий пользователь — `admin` или `dev` (wildcard) — показывает сессии всех
     пользователей (передаёт `user_id=None`). Иначе — только своего `user_id`.
   - Кнопка «Обновить» — перезагружает таблицу.
   - `_format_duration(login_at, logout_at) -> str` — «1ч 23мин» или «активна».

2. **`AuditLogPanel(QWidget)`**:
   - `QTableWidget` с колонками: «Время», «Пользователь», «Тип действия», «Ресурс».
   - Панель фильтров (горизонтально):
     - `QComboBox` «Пользователь» (наполняется из `auth_manager.list_users()`, первый пункт «Все»).
     - `QDateEdit` «С» / «По» (по умолчанию — сегодня).
     - `QLineEdit` «Ресурс» (text-search, wildcard-фильтр на стороне storage).
   - Кнопка «Применить» — вызывает `_load(offset=0)`.
   - Пагинация: кнопки «←» / «→» меняют `_offset` на ±100.
   - `_load(offset: int)` → `storage.list_audit(...)` с текущими фильтрами.
   - Двойной клик по строке → `QDialog` с полным содержимым
     (`before_json` / `after_json` в `QTextEdit` read-only).

3. **`AdministrationSection._build_sidenav`** — добавить подсекции:
   - `«Сессии»` (permission `users.view` — видит только свои сессии; `admin/dev` — все).
   - `«Audit log»` (permission `roles.view` — исторически логично для admin/dev).
   - Порядок в SideNav: «Пользователи» → «Роли» → «Сессии» → «Audit log».
   - `_rebuild()` расширяется: `has_sessions = has_users`, `has_audit = has_roles`.

### Acceptance criteria

- [ ] `SessionsPanel` отображает записи из `SqliteAuditStorage` (mock через DI).
- [ ] `AuditLogPanel` фильтрует по пользователю и дате через `storage.list_audit`.
- [ ] Пагинация: при нажатии «→» offset увеличивается на 100.
- [ ] `AdministrationSection._rebuild()` с `has_users=True, has_roles=True` добавляет
  все 4 пункта SideNav.
- [ ] Тесты без Qt-окружения не запускают `QApplication`.

### Тесты (Group C)

- `test_sessions_panel.py` — unit (pytest-qt): `test_panel_loads_sessions`,
  `test_panel_refresh_button`, `test_duration_format`.
- `test_audit_log_panel.py` — unit (pytest-qt): `test_panel_loads_audit`,
  `test_filter_applies`, `test_pagination_next`, `test_detail_dialog_opens`.

---

## Group D — Editable PermissionMatrix + ActionBus integration

**Сложность:** M+  
**Зависит от:** Group B, Group C

### Цель

Сделать `PermissionMatrix` редактируемой для ролей без `hidden_in_ui=True`.
Все изменения идут через `ActionBus` → `AuditMiddleware` → `audit_log`.
Добавить action-type `ROLE_UPDATE` и handler в `bus_factory`.

### Файлы

| Файл | Действие |
|------|----------|
| `multiprocess_prototype/frontend/actions/action_types.py` | добавить `ROLE_UPDATE` |
| `multiprocess_prototype/frontend/actions/builder.py` | добавить `V2ActionBuilder.role_update(...)` |
| `multiprocess_prototype/frontend/actions/handlers/role_update_handler.py` | создать |
| `multiprocess_prototype/frontend/actions/handlers/__init__.py` | экспортировать |
| `multiprocess_prototype/frontend/actions/bus_factory.py` | регистрация `RoleUpdateHandler` |
| `multiprocess_prototype/frontend/widgets/tabs/settings/administration/permission_matrix.py` | read-only → editable |
| `multiprocess_prototype/frontend/widgets/tabs/settings/administration/roles_panel.py` | подключить action bus, активировать кнопки |
| `Services/auth/predefined_roles.py` | нет изменений (только читается) |
| `Services/auth/tests/test_role_update_handler.py` | создать |
| `multiprocess_prototype/frontend/widgets/tabs/settings/administration/tests/test_permission_matrix_editable.py` | создать |

### Задачи

1. **`ROLE_UPDATE = "role_update"`** в `action_types.py`.

2. **`V2ActionBuilder.role_update`** в `builder.py`:
   ```python
   @staticmethod
   def role_update(
       role_name: str,
       old_permissions: list[str],
       new_permissions: list[str],
   ) -> Action:
   ```
   - `action_type=ROLE_UPDATE`, `undoable=True`,
     `forward_patch={"role_name": role_name, "permissions": new_permissions}`,
     `backward_patch={"role_name": role_name, "permissions": old_permissions}`,
     `resource=f"roles.{role_name}"`.

3. **`RoleUpdateHandler`** — `handlers/role_update_handler.py`:
   - `apply(action, rm)` → `auth_manager.update_role_permissions(role_name, new_permissions)`.
   - `revert(action, rm)` → `auth_manager.update_role_permissions(role_name, old_permissions)`.
   - `auth_manager` передаётся в конструктор.

4. **`PermissionMatrix`** — читать `Action.resource` и добавить режим `editable`:
   - Новый параметр `__init__(editable: bool = False, ...)`.
   - В `editable=True` режиме: чекбоксы активны; сигнал `permissions_changed(role_name: str,
     old_perms: list[str], new_perms: list[str])`.
   - При клике на чекбокс «Edit»: если `edit=True` → авто-set `view=True` (coherence);
     если `view=False` → авто-снять `edit` (coherence).
   - Внутри: `_pending_permissions: set[str]` — накапливает изменения; кнопка «Сохранить»
     испускает сигнал `permissions_changed`.
   - Системные роли (`hidden_in_ui=True`): `editable=False` всегда,
     даже если `PermissionMatrix(editable=True)` — определяется по полю `role_dict["hidden_in_ui"]`
     в `set_role()`.
   - Кнопка «Сбросить» — откат к исходному состоянию без `permissions_changed`.

5. **`RolesPanel`**:
   - Добавить конструктору `bus: ActionBus | None = None` (передаётся через `ctx.action_bus()`).
   - При `ctx.access_context.has_permission("roles.edit")`:
     - `PermissionMatrix(editable=True)`.
     - Активировать кнопки «Создать роль», «Изменить права», «Удалить роль»
       (с `roles.create`, `roles.edit`, `roles.delete` permissions соответственно).
   - Подключить `matrix.permissions_changed` →
     `bus.execute(V2ActionBuilder.role_update(role_name, old_perms, new_perms))`.
   - Кнопка «Удалить роль»: `QMessageBox.warning` confirm →
     вызов `auth_manager.delete_role(name)` (без ActionBus — не undoable; зафиксировать в docstring).
   - `roles.create` и `roles.delete` — **доступны только роли `dev`**
     (wildcard `*`). `roles.edit` — `admin` тоже может.

6. **`permissions.py`** — добавить `roles.create`, `roles.edit`, `roles.delete`
   в `register_all_permissions()`. В `predefined_roles.py` — `admin` получает `roles.edit`;
   `dev` уже имеет `*`.

7. **`AdministrationSection._rebuild`** — расширить: при `has_roles and has_roles_edit`
   (`roles.edit` permission) передать `editable_matrix=True` в `RolesPanel`.
   Иначе — read-only (текущее поведение PR2).

### Acceptance criteria

- [ ] `admin` → «Изменить права» активна; изменение чекбокса → `role_update` в `audit_log`.
- [ ] Coherence: снять `view` → автоматически снимается `edit`.
- [ ] Coherence: поставить `edit` → автоматически ставится `view`.
- [ ] Системная роль `dev` (`hidden_in_ui=True`) — матрица read-only,
  кнопки «Изменить»/«Удалить» disabled.
- [ ] Undo: `bus.undo()` → `update_role_permissions` откатывает к старым правам.
- [ ] `viewer` → кнопки «Изменить»/«Удалить» disabled.

### Тесты (Group D)

- `test_permission_matrix_editable.py`:
  - `test_editable_mode_checkboxes_active` — чекбоксы enabled при `editable=True`.
  - `test_coherence_edit_sets_view` — клик edit → view тоже checked.
  - `test_coherence_unset_view_clears_edit` — снять view → edit снят.
  - `test_hidden_role_readonly` — `hidden_in_ui=True` → disabled даже при `editable=True`.
  - `test_save_emits_signal` — кнопка «Сохранить» испускает `permissions_changed`.
  - `test_reset_discards_changes` — кнопка «Сбросить» → исходные чекбоксы.
- `test_role_update_handler.py`:
  - `test_apply_calls_update_permissions`.
  - `test_revert_restores_old_permissions`.

---

## Group E — StatsManager + финальные тесты + DoD + sentrux

**Сложность:** S  
**Зависит от:** Group B, Group C, Group D

### Цель

Подключить `StatsManager` (три метрики), собрать финальный smoke-test для всего PR4,
проверить `/sentrux-diff` без деградации, закрыть DoD чеклист.

### Файлы

| Файл | Действие |
|------|----------|
| `Services/auth/manager.py` | добавить `observe_stat` вызовы |
| `Services/auth/audit_writer.py` | добавить `observe_stat("auth.sessions.active", ...)` |
| `Services/auth/tests/test_stats_integration.py` | создать |
| `multiprocess_prototype/frontend/widgets/tabs/settings/administration/tests/test_pr4_smoke.py` | создать |
| `Services/auth/DECISIONS.md` | финализировать Auth-005..007 |

### Задачи

1. **StatsManager интеграция** в `AuthManager` (через `ObservableMixin.observe_stat`):
   - `auth.login.attempts.per_hour` — инкрементируется при каждом вызове `login()`
     (успешном или нет). Счётчик — скользящее окно 1 час (реализовать через
     `deque` с timestamp'ами; `observe_stat` вызывается с текущим значением).
   - `auth.login.failed_ratio` — float: `failed / total` за последний час.
   - `auth.sessions.active` — int: обновляется в `open_session` (+1) и
     `close_session` (-1). Хранить `_active_sessions_count: int` в `AuditWriter`
     или в `SessionTracker` — на усмотрение Developer'а.
   - Вызовы `observe_stat` через `ObservableMixin` — не инлайн `StatsManager.instance()`.

2. **Smoke-test `test_pr4_smoke.py`**:
   - E2E сценарий без Qt: `AuthManager.login()` → `SessionTracker.open_session()` →
     `AuditWriter.log(entry)` → `SqliteAuditStorage.list_audit()` → запись есть.
   - `AuthManager.logout()` → `SessionTracker.close_session()` → `logout_at` проставлен.
   - `AuditWriter` с broken storage → JSONL существует → `recover_fallback()` → записи в БД.
   - Все тесты используют `sqlite:///:memory:` и `tmp_path`.

3. **DoD финальная верификация**:
   - `python scripts/run_framework_tests.py` — зелёный.
   - `/sentrux-diff` — без деградации относительно PR3-baseline.
   - Все пункты DoD из `04-pr4-audit-hardening.md` отмечены `[x]`.

### Acceptance criteria

- [ ] `observe_stat("auth.login.attempts.per_hour", N)` вызывается при каждом `login()`.
- [ ] `observe_stat("auth.login.failed_ratio", r)` вызывается при каждом `login()`.
- [ ] `observe_stat("auth.sessions.active", N)` обновляется синхронно с open/close.
- [ ] E2E smoke-тест зелёный (in-memory SQLite).
- [ ] `run_framework_tests.py` зелёный.

### Тесты (Group E)

- `test_stats_integration.py`:
  - `test_attempts_increments_on_login` — после 3 login (2 fail + 1 success): attempts=3, failed_ratio≈0.67.
  - `test_active_sessions_counter` — open × 3 → active=3; close × 1 → active=2.
- `test_pr4_smoke.py` — см. п. 2 выше.

---

## Сводная таблица зависимостей

| Group | Зависит от | Сложность | Файлов создать | Файлов изменить |
|-------|-----------|-----------|----------------|-----------------|
| A | — | M | 3 | 3 |
| B | A | M+ | 5 | 4 |
| C | B | M | 4 | 1 |
| D | B, C | M+ | 4 | 4 |
| E | B, C, D | S | 3 | 2 |

**Итого:** ~19 новых файлов, ~14 изменяемых.

---

## Ключевые риски

| Риск | Митигация |
|------|-----------|
| `ActionBus` не имеет post-execute callback (только `_change_callbacks`) | Developer выбирает наименее инвазивный путь: новый `add_post_execute_callback` в FW-шине или повесить на `_change_callbacks` (если они вызываются после apply) |
| Blocking SQLite в AuditWriter при batch | Весь SQLite-IO в отдельном потоке; UI-thread никогда не ждёт |
| `audit_db_path` не передаётся в `SqliteAuditStorage` на этапе сборки приложения | Group B: проверить, что `app.py` / `AppContext` создаёт `SqliteAuditStorage` с путём из `AuthConfig.audit_db_path` (env `INSPECTOR_AUTH_DB_PATH`) |
| `RolesPanel` получает `bus` — возникает циклическая зависимость через `AppContext` | `ctx.action_bus()` — ленивый accessor через `AppContext`; нет прямого импорта bus_factory в roles_panel |
| Coherence-инвариант в матрице сложен при пакетном set_role | Unit-тест `test_coherence_*` покрывает оба направления явно |

---

## Антипаттерны (из метаплана, актуальны для PR4)

- Никакого SQLite-IO в UI-thread — только через `AuditWriter`.
- `AuditEntry.update()` / `AuditEntry.delete()` → всегда `AuditImmutableError`.
- `before_json` / `after_json` с `sensitive=True` полями — поля пароля не попадают в `forward_patch`/`backward_patch` у `role_update` action (пароли не хранятся в Role).
- PySide6 не импортируется в `Services/auth/`.
- `Services/auth/` не импортирует `multiprocess_prototype.*`.
