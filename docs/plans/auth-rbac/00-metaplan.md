# Метаплан: Auth/RBAC система для Inspector_bottles

> Один документ-зонтик и четыре PR-плана в отдельных файлах.
> Метаплан описывает целевую архитектуру, контракты, общие политики и порядок исполнения.
> Каждый PR-план — самодостаточный: цели, файлы, шаги, DoD, риски, rollback.

**Файлы:**
- [01-pr1-foundation.md](01-pr1-foundation.md) — Auth Backend + RBAC во frontend_module
- [02-pr2-login-admin.md](02-pr2-login-admin.md) — Login Flow + Administration UI (basic)
- [03-pr3-permissions-rollout.md](03-pr3-permissions-rollout.md) — Permissions Rollout
- [04-pr4-audit-hardening.md](04-pr4-audit-hardening.md) — Audit Trail + Editable Matrix + Hardening

---

## 1. Видение

Промышленный инспектор брака требует:
- управляемого доступа (несколько ролей с разными правами),
- неприступности к чужим паролям (даже у админа),
- следа изменений (кто/когда/что менял — audit),
- интеграции без переписывания фреймворка (расширение, не революция).

Решаем эту задачу **минимально-инвазивно**: расширяем существующий `frontend_module`
(`AccessContext`/`AccessTrait`) до RBAC, выносим всю auth-логику в новый пакет
`Services/auth/`, оставаясь в архитектурных рамках проекта.

## 2. Целевая архитектура (после всех PR)

```
┌──────────────────────────────────────────────────────────────────────┐
│              multiprocess_prototype (UI process)                     │
│                                                                      │
│   ┌────────────────┐    ┌────────────────────────────────────────┐   │
│   │ chrome/        │    │ tabs/settings/administration/          │   │
│   │ LoginButton ───┼───▶│ UsersPanel │ RolesPanel │ AuditPanel*  │   │
│   └────────┬───────┘    └────────┬───────────────────────────────┘   │
│            │                     │                                   │
│            ▼                     ▼                                   │
│   ┌────────────────────────────────────────────────────────────┐    │
│   │ AppContext.auth: IAuthManager                              │    │
│   │ AppContext.state_store: auth/current_user (in-memory)      │    │
│   │ ActionBus + AuditMiddleware* ──▶ AuditWriter*              │    │
│   └────────────────────────┬───────────────────────────────────┘    │
│                            │                                        │
└────────────────────────────┼────────────────────────────────────────┘
                             │ DI
                             ▼
┌──────────────────────────────────────────────────────────────────────┐
│  Services/auth  (новый пакет, no Qt, no prototype imports)          │
│                                                                      │
│   AuthManager (BaseManager + ObservableMixin)                        │
│     ├── PermissionsRegistry  (декларативный каталог)                 │
│     ├── BcryptHasher                                                 │
│     ├── YamlUserStorage      (atomic writes, FileStorage)            │
│     ├── LockoutTracker       (in-memory, exponential backoff)        │
│     └── SessionTracker*                                              │
│                                                                      │
│   AuditWriter* (BaseManager + ObservableMixin)                       │
│     ├── append-only queue   (threading + fallback JSONL)             │
│     └── SqliteAuditStorage  (Services/sql.GenericRepository)         │
│                                                                      │
│   models.py: User/Role/SessionEntry*/AuditEntry*/AuthConfig          │
│              — Pydantic SchemaBase + @register_schema + FieldMeta    │
└──────────────────────────────────────────────────────────────────────┘
                             ▲
                             │ uses
┌────────────────────────────┴────────────────────────────────────────┐
│  multiprocess_framework/modules/frontend_module (расширенный)       │
│                                                                      │
│   AccessContext  +permissions:frozenset, +role_name                  │
│       has_permission(name) -> bool                                   │
│   AccessTrait    +required_view_permission, +required_edit_permission│
│       can_view()  /  can_modify()                                    │
│   BaseConfigurableWidget                                             │
│       can_view==False  -> setVisible(False)                          │
│       can_view & !can_modify -> setEnabled(False)+[readOnly="true"]  │
│   WindowManager.set_access_context(ctx)                              │
└──────────────────────────────────────────────────────────────────────┘

(*) — компоненты только из PR4 (audit-фаза). PR1–PR3 их не строят.
```

## 3. Roadmap: 4 PR

| PR | Цель | Объём | Зависит от |
|----|------|-------|------------|
| **PR1 — Foundation** | `Services/auth` backend без UI + RBAC во `frontend_module` | ~4–5 дней | — |
| **PR2 — Login & Administration UI (basic)** | Глобальный login + админ-панель «Пользователи»/«Роли» (роли read-only/preset) | ~3–4 дня | PR1 |
| **PR3 — Permissions Rollout** | Применить permissions ко всем существующим вкладкам, инкрементально | ~2–3 дня | PR2 |
| **PR4 — Audit Trail & Hardening** | AuditWriter + sessions + log-panel + редактируемая permission matrix + security policies | ~5–7 дней | PR3 |

**Принципы sequencing'а:**
- Каждый PR заканчивается зелёным `validate.py`, `run_framework_tests.py`, `sentrux-check`, и **merge в main**.
- Следующий PR начинается с свежего `main` после merge предыдущего.
- Если PR4 откладывается — у нас уже **рабочая** auth-система (после PR3).

## 4. Общие инварианты и контракты

**Безопасность:**
- Plain-text паролей **нигде** не хранится. Только `bcrypt` хеши (rounds=12 prod, 4 test).
- `update`/`delete` на `audit_log` **запрещены** на уровне репозитория (raise `AuditImmutableError`).
- Last-admin invariant: нельзя удалить/деактивировать последнего активного пользователя с ролью `admin`.
- Хардкод `admin/admin` **запрещён**: bootstrap через env var `INSPECTOR_DEV_PASSWORD` или интерактивный prompt при первом запуске (если `users.yaml` отсутствует).

**Контракты данных:**
- Между процессами — `dict` (через `to_dict`/`from_dict` SchemaBase).
- `AccessContext.permissions: frozenset[str]` сериализуется в `list[str]` (sorted), десериализуется обратно во frozenset.
- В state_store `auth/current_user` — dict-форма, не Pydantic. Persistence для этой ветки **отключена**.

**Контракты UI:**
- `can_view==False` → `setVisible(False)`.
- `can_view==True and can_modify==False` → `setEnabled(False)` + QSS-класс `[readOnly="true"]` (opacity 0.5).
- Coherence: `edit ⇒ view` (storage и UI matrix enforced).
- До login — UI разрешает **только** read-only вкладки (`requires_auth=False`). Любая мутация → диалог «Требуется вход».

**Permission namespace:** `<scope>.<resource>.<action>` (kebab-case в scope), пример: `tabs.recipes.view`.

**Predefined роли (создаются bootstrap'ом, нельзя удалить):**
- `dev` — `hidden_in_ui=True`, все permissions, `level=10`. Только владелец проекта.
- `admin` — управление users/roles, все вкладки visible. Не может править системные роли (только dev).
- `operator` — работа с pipeline (view+edit), settings — view-only.
- `viewer` — view-only везде.

## 5. Соответствие паттернам проекта (must-reuse)

Все новые сущности — **только** на существующих базовых классах. Дублирование инфраструктуры — антипаттерн.

| Что строим | На чём базируется | Где пример |
|---|---|---|
| `AuthManager`, `AuditWriter` | `BaseManager` + `ObservableMixin` | [multiprocess_framework/modules/base_manager/](../../../multiprocess_framework/modules/base_manager/) |
| `User`, `Role`, `AuthConfig`, … | `SchemaBase` + `@register_schema` + `FieldMeta` | [data_schema_module/docs/examples/](../../../multiprocess_framework/modules/data_schema_module/docs/examples/) |
| `YamlUserStorage` | `FileStorage` | [data_schema_module/serialization/file_storage.py](../../../multiprocess_framework/modules/data_schema_module/serialization/file_storage.py) |
| `AuditRepository`, `SessionRepository` | `GenericRepository` + `SQLAlchemyUnitOfWork` | [Services/sql/core/](../../../Services/sql/core/) |
| `AuthConfig` загрузка | `ConfigStore` / `ConfigManager` | [multiprocess_framework/modules/config_module/](../../../multiprocess_framework/modules/config_module/) |
| Ошибки auth | `ErrorManager` + `ErrorPolicy` | [multiprocess_framework/modules/error_module/](../../../multiprocess_framework/modules/error_module/) |
| Логи auth/audit | `LoggerManager` через `channel_routing_module` | [multiprocess_framework/modules/logger_module/](../../../multiprocess_framework/modules/logger_module/) |
| Интерфейсы | Protocol в `interfaces.py` модуля | [data_schema_module/interfaces/](../../../multiprocess_framework/modules/data_schema_module/interfaces/) |
| Структура модуля `Services/auth/` | README.md + STATUS.md + DECISIONS.md + tests/ + interfaces.py + фасадный `__init__.py` | `data_schema_module` (после полировки 4/N), `Services/sql/` |
| UI таблицы | `StructuredTableWidget` | [frontend_module/widgets/tables/structured_table.py](../../../multiprocess_framework/modules/frontend_module/widgets/tables/structured_table.py) |
| UI формы | `ParamsForm` (по Pydantic) | [frontend_module/widgets/entity_editor/params_form.py](../../../multiprocess_framework/modules/frontend_module/widgets/entity_editor/params_form.py) |
| Cards/Table | `ViewModeToggle` | [multiprocess_prototype/frontend/forms/view_mode_toggle.py](../../../multiprocess_prototype/frontend/forms/view_mode_toggle.py) |
| Layout | `SideNavLayout` | [multiprocess_prototype/frontend/widgets/primitives/side_nav_layout.py](../../../multiprocess_prototype/frontend/widgets/primitives/side_nav_layout.py) |
| Виджеты на правах | `BaseConfigurableWidget` + `AccessTrait` | [frontend_module/core/base_configurable_widget.py](../../../multiprocess_framework/modules/frontend_module/core/base_configurable_widget.py) |
| Мутации в UI | `ActionBus` + `V2ActionBuilder` | [multiprocess_prototype/frontend/actions/bus_factory.py](../../../multiprocess_prototype/frontend/actions/bus_factory.py) |
| Подписка на `auth/current_user` | `state_store.subscribe` | [state_store_module/persistence/persistence_manager.py](../../../multiprocess_framework/modules/state_store_module/persistence/persistence_manager.py) |

**`BaseManager + ObservableMixin` даёт бесплатно:**

```python
class AuthManager(BaseManager, ObservableMixin):
    # из BaseManager:    start/stop/is_running, реестр менеджеров, process_status_unified
    # из ObservableMixin: log_info/log_warning/log_error/log_debug -> LoggerManager
    #                    report_error(code, context)              -> ErrorManager
    #                    observe_stat(name, value)                -> StatsManager (когда подключим)
    #                    сигналы менеджера
```

Свою lifecycle/logger/error обвязку **не пишем** — это явный антипаттерн в проекте.

## 6. Antipattern checklist (запреты)

- ❌ Singleton/глобальная `current_user` — только через `state_store.auth/current_user`.
- ❌ Блокирующая SQLite-запись в UI-thread — только через `AuditWriter` (поток+очередь).
- ❌ `print()`/прямой `raise` в managers — `ObservableMixin.log_*` + `ErrorPolicy`.
- ❌ Хардкод путей — все через `AuthConfig` + env (`INSPECTOR_AUTH_USERS_PATH`, `INSPECTOR_AUTH_DB_PATH`).
- ❌ Свой SQLAlchemy boilerplate в `Services/auth/` — через `Services/sql`.
- ❌ PySide6/Qt imports в `Services/auth/` — только domain.
- ❌ Передача Pydantic между процессами — только `to_dict()`.
- ❌ Дублирование `AccessTrait` в каждом виджете — наследование от `BaseConfigurableWidget`.
- ❌ Хардкод `admin/admin` — bootstrap только через env var или интерактивный prompt.
- ❌ `UPDATE`/`DELETE` на `audit_log` — raise `AuditImmutableError`.
- ❌ Plain-text паролей в логах, db, snapshot'ах, debug-выводе.

## 7. Безопасность: явные policies

**Password policy** (`AuthConfig.password_policy`):
- min length: 8
- требование: ≥3 из 4 классов (lower/upper/digit/symbol)
- bcrypt rounds: 12 (prod), 4 (test fixture)
- max length: 72 (ограничение bcrypt)

**Lockout policy** (`AuthConfig.lockout_policy`):
- `failed_threshold`: 5
- `delays_sec`: [30, 60, 120, 240, 480] (экспонента, cap 8 мин)
- `reset_after_sec`: 1800 (30 мин неактивности → счётчик обнуляется)
- in-memory (`LockoutTracker`), без persistence — restart сбрасывает.

**Atomic writes:**
- `YamlUserStorage.save()` → `tempfile.NamedTemporaryFile` в той же директории + `os.replace`.
- `FileStorage` уже это умеет — проверить и переиспользовать, иначе обернуть.

**Audit fallback (PR4):**
- Если SQLite недоступен — `AuditWriter` пишет в `audit_fallback.jsonl` рядом.
- При следующем успешном connect — миграция fallback в SQLite, файл архивируется.
- Compliance: записи **никогда** не теряются.

**Last-admin invariant:**
- `AuthManager.delete_user` / `update_user_role` → проверка «остался ≥1 активный admin».
- Нарушение → `AUTH-011 LastAdminError`.

## 8. Глоссарий

- **Permission** — строка `<scope>.<resource>.<action>` (`tabs.recipes.edit`).
- **Role** — именованный набор permissions + числовой `level` (legacy fallback) + флаги.
- **AccessContext** — frozen dataclass с текущими правами пользователя, пропагируется через `WindowManager`.
- **`requires_auth=False`** — флаг вкладки, разрешающий просмотр до login (read-only).

---

# Appendix A — Логи (через LoggerManager / ObservableMixin)

| Уровень | Событие | Полезная нагрузка |
|---|---|---|
| `INFO` | `auth.login.success` | username, role_name, session_id |
| `INFO` | `auth.logout` | username, session_id, duration_sec |
| `INFO` | `auth.user.created` | username, role_name, created_by |
| `INFO` | `auth.user.deleted` | username, deleted_by |
| `INFO` | `auth.role.updated` | role_name, permissions_added/removed, changed_by |
| `INFO` | `auth.password.reset` | username, reset_by (**не** password) |
| `WARNING` | `auth.login.failed` | username, reason (**не** password) |
| `WARNING` | `auth.permission.denied` | username, permission, resource |
| `WARNING` | `auth.lockout.engaged` | username, delay_sec, failures |
| `WARNING` | `auth.dev_password.missing` | bootstrap без env var |
| `ERROR` | `auth.storage.corrupted` | path, exception |
| `ERROR` | `auth.audit.write_failed` | queue_size, fallback_engaged |

**Никогда не логировать:** plain-text пароли, password_hash, `before/after` для `sensitive=True` полей.

# Appendix B — Коды ошибок (через ErrorManager / ErrorPolicy)

| Код | Класс | Severity | UI message |
|---|---|---|---|
| `AUTH-001` | `InvalidCredentials` | warning | «Неверный логин или пароль» |
| `AUTH-002` | `UserNotFound` | warning | «Пользователь не найден» |
| `AUTH-003` | `UserAlreadyExists` | warning | «Пользователь уже существует» |
| `AUTH-004` | `RoleNotFound` | warning | «Роль не найдена» |
| `AUTH-005` | `PermissionDenied` | warning | «Недостаточно прав для этого действия» |
| `AUTH-006` | `WeakPassword` | warning | «Пароль не соответствует требованиям» |
| `AUTH-007` | `AuditImmutableError` | error | «Audit log защищён от изменений» |
| `AUTH-008` | `DevPasswordRequired` | error | «Не задан INSPECTOR_DEV_PASSWORD» (setup-режим) |
| `AUTH-009` | `StorageCorrupted` | error | «Ошибка чтения хранилища пользователей» |
| `AUTH-010` | `SessionExpired` | warning | «Сессия истекла, войдите снова» |
| `AUTH-011` | `LastAdminError` | warning | «Нельзя удалить последнего администратора» |
| `AUTH-012` | `AccountLocked` | warning | «Учётная запись временно заблокирована (попыток: N, ждать: Ms)» |

# Appendix C — ADR catalog

**`Services/auth/DECISIONS.md`** (создаётся в PR1, расширяется в PR4):
- Auth-001: Двухосевая модель прав (view + edit).
- Auth-002: bcrypt с rounds=12 (prod) / 4 (test). Не argon2 — bcrypt зрелее.
- Auth-003: YAML для users/roles, SQLite для audit/sessions. Раздельные хранилища.
- Auth-004: dev-роль через env var + интерактивный bootstrap, без hardcoded admin/admin.
- Auth-005 (PR4): Audit append-only, UPDATE/DELETE запрещены на уровне репозитория.
- Auth-006 (PR4): Audit fallback на JSONL при недоступности SQLite.
- Auth-007 (PR4): Editable PermissionMatrix — все изменения через ActionBus, audit-logged.

**`multiprocess_framework/modules/frontend_module/DECISIONS.md`** (PR1):
- FE-XXX: Расширение `AccessContext` под named permissions с fallback на legacy level.
- FE-XXX+1: AccessTrait двухосевая модель (view/edit).
- FE-XXX+2: Централизация applying access policy в `BaseConfigurableWidget`.

# Appendix D — Pre-flight checklist для запуска работ

**Перед PR1:**
1. Перейти на `main`, sync с origin.
2. Закоммитить uncommitted-изменения текущей ветки `chore/mlx-embeddings-migration` (13 файлов).
3. Merge `chore/mlx-embeddings-migration` → `main` через `--no-ff`. Push **только с явного подтверждения**.
4. `/sentrux-baseline` — зафиксировать baseline качества.
5. `git checkout -b feature/auth-pr1-foundation`.

**Между PR'ами:**
- Каждый PR заканчивается merge в `main` (после ревью).
- Новая ветка `feature/auth-pr<N>-<name>` от свежего `main`.
- `/sentrux-baseline` обновляется только перед PR1.

---

## Резюме (для быстрого скана)

- **4 PR**, ~15 рабочих дней совокупно. Можно остановиться после PR3 — получаем рабочую auth без audit.
- **Без переписывания фреймворка** — расширяем `AccessContext`/`AccessTrait` с 100% обратной совместимости.
- **Без хардкода `admin/admin`** — bootstrap через env var или интерактивный CLI.
- **Bcrypt + atomic YAML + lockout** — security baseline с первого PR.
- **Audit append-only** через `Services/sql.GenericRepository`, fallback на JSONL.
- **Двухосевая модель UI**: нет view → скрыт; есть view, нет edit → disabled+opacity.
- **Все managers — на `BaseManager + ObservableMixin`**, никаких самопальных logger/error/lifecycle.
- **Все Pydantic — на `SchemaBase + @register_schema + FieldMeta`**, никаких сырых dataclass'ов.
