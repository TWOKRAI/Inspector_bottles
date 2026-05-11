# PR1 — Foundation: Auth Backend + RBAC во frontend_module

> **Положение в roadmap:** PR1 из 4. Зависимостей нет. Следующий — [PR2](02-pr2-login-admin.md).
> **Контекст и общие контракты** — см. [00-metaplan.md](00-metaplan.md).

## Context

Подготовительный PR. Цель — дать «работающий контракт»: можно создать User, залогиниться,
получить `AccessContext` с permissions; виджеты фреймворка умеют его читать. UI ещё нет.

## Goals

- `Services/auth/` со стандартной структурой модуля и нулевым UI-кодом.
- `AccessContext` и `AccessTrait` поддерживают именованные permissions + двухосевую модель
  (view/edit) с fallback на числовой `legacy_required_level`.
- 100% обратная совместимость: существующие 2545 тестов фреймворка остаются зелёными.

## Non-goals

- UI логина и админ-панели (PR2).
- Audit log, sessions (PR4).
- Применение permissions к существующим вкладкам (PR3).

## Files

**Создать:**
- `Services/auth/` — полный пакет:
  ```
  Services/auth/
  ├── __init__.py            # фасадный экспорт публичного API
  ├── interfaces.py          # IAuthManager, IUserStorage, IPasswordHasher
  ├── models.py              # User, Role, AuthConfig (Pydantic SchemaBase)
  ├── hasher.py              # BcryptHasher
  ├── policies.py            # PasswordPolicy, LockoutPolicy
  ├── lockout_tracker.py     # in-memory LockoutTracker
  ├── storage_users.py       # YamlUserStorage (atomic writes на FileStorage)
  ├── permissions_registry.py
  ├── auth_manager.py        # AuthManager(BaseManager, ObservableMixin)
  ├── bootstrap.py           # CLI: python -m Services.auth.bootstrap
  ├── exceptions.py          # AUTH-001..011 коды
  ├── DECISIONS.md           # Auth-001..004
  ├── README.md
  ├── STATUS.md
  └── tests/                 # pytest без GUI
  ```
- Тесты: `Services/auth/tests/test_hasher.py`, `test_policies.py`, `test_lockout.py`, `test_storage_users.py`, `test_auth_manager.py`, `test_bootstrap.py`.

**Изменить:**
- [multiprocess_framework/modules/frontend_module/managers/access_context.py](../../../multiprocess_framework/modules/frontend_module/managers/access_context.py) — расширить dataclass.
- [multiprocess_framework/modules/frontend_module/components/base/traits/access_trait.py](../../../multiprocess_framework/modules/frontend_module/components/base/traits/access_trait.py) — двухосевая модель.
- [multiprocess_framework/modules/frontend_module/application/window_manager.py](../../../multiprocess_framework/modules/frontend_module/application/window_manager.py) — `set_access_context()`.
- [multiprocess_framework/modules/frontend_module/core/base_configurable_widget.py](../../../multiprocess_framework/modules/frontend_module/core/base_configurable_widget.py) — централизованное применение трейта.
- [multiprocess_framework/modules/frontend_module/tests/test_access_context.py](../../../multiprocess_framework/modules/frontend_module/tests/test_access_context.py) — новые кейсы.
- (новый файл) `multiprocess_framework/modules/frontend_module/tests/test_access_trait.py` — двухосевая модель.
- `multiprocess_framework/modules/frontend_module/DECISIONS.md` — ADR FE-XXX.
- `multiprocess_framework/DECISIONS.md` — индекс (через `python -m scripts.sync`).
- `pyproject.toml` — `bcrypt>=4.1`.
- `Services/STATUS.md` — добавить модуль `auth`.
- `.sentrux/rules.toml` — boundaries для `Services/auth` (запрет импорта `multiprocess_prototype.*` и Qt-зависимостей).

## Steps

1. **Pydantic-модели (`models.py`).** Все на `SchemaBase + @register_schema + FieldMeta`:
   - `User`(user_id, username, password_hash, role_name, created_at, last_login_at, login_count, is_active) — `@register_schema("auth_user")`
   - `Role`(name, level, permissions: list[str], hidden_in_ui, bypass_readonly, show_hidden) — `@register_schema("auth_role")`
   - `AuthConfig`(users_path, bcrypt_rounds, password_policy, lockout_policy) — `@register_schema("auth_config")`, регистрируется в `ConfigStore`.
2. **`BcryptHasher`** — `hash(password) -> str`, `verify(password, hash) -> bool`. Rounds из config.
3. **`PasswordPolicy.validate(password)`** — длина + классы символов. Возвращает `Result`/raise `WeakPassword`.
4. **`YamlUserStorage`** на `FileStorage` с **atomic write** (tempfile + os.replace).
5. **`LockoutTracker`** — in-memory dict `{username: (failures, next_allowed_ts)}`, методы `record_failure`/`record_success`/`is_locked`.
6. **`PermissionsRegistry`** — `register(name, description)`, `list_all() -> list[PermissionDescriptor]`, потокобезопасный (lock).
7. **`AuthManager(BaseManager, ObservableMixin)`** API:
   ```
   login(username, password) -> dict                  # обновляет last_login_at, login_count
   logout()                                           # очищает локальную сессию
   create_user(username, password, role_name)
   delete_user(username)                              # проверяет last-admin invariant
   update_user_role(username, role_name)              # проверяет last-admin invariant
   reset_password(username) -> str                    # возвращает новый сгенерированный пароль
   list_users() -> list[dict]
   list_roles() -> list[dict]
   create_role(name, permissions, level, ...)
   update_role_permissions(name, permissions)
   delete_role(name)                                  # запрет на predefined роли
   verify_admin_password(password) -> bool            # для confirm-диалогов
   ```
   Все ошибки — через `report_error(code, context)`, не raise.
8. **Расширить `AccessContext`:**
   ```python
   @dataclass(frozen=True)
   class AccessContext:
       level: int = 0                       # legacy
       permissions: frozenset[str] = frozenset()
       role_name: str = ""
       bypass_readonly: bool = False
       show_hidden: bool = False

       def has_permission(self, name: str) -> bool: ...

       @classmethod
       def from_dict(cls, data): ...        # permissions: list -> frozenset
       def to_dict(self): ...               # frozenset -> sorted list
   ```
9. **Расширить `AccessTrait`** (упрощённая модель — два пермишена + один legacy уровень):
   ```python
   class AccessTrait:
       def __init__(self,
                    legacy_required_level: int = 0,
                    required_view_permission: str | None = None,
                    required_edit_permission: str | None = None): ...
       def update(self, ctx: AccessContext) -> None: ...
       def can_view(self) -> bool:    # view-perm задан -> ctx.has_permission, иначе True
       def can_modify(self) -> bool:  # edit-perm задан -> ctx.has_permission, иначе ctx.level >= legacy
   ```
10. **`BaseConfigurableWidget`** — централизованное применение AccessTrait:
    ```python
    def _apply_access(self):
        if not self._trait.can_view():
            self.setVisible(False); return
        self.setVisible(True)
        self.setEnabled(self._trait.can_modify())
        self.setProperty("readOnly", not self._trait.can_modify())
        self.style().unpolish(self); self.style().polish(self)
    ```
11. **`WindowManager.set_access_context(ctx)`** + `update_access_context()` сигнал.
    Старый `set_access_level(int)` → обёртка с `warnings.warn(DeprecationWarning)`.
12. **Bootstrap (`bootstrap.py` + `python -m Services.auth.bootstrap`).** Если `users.yaml` отсутствует:
    - есть `INSPECTOR_DEV_PASSWORD` → создать predefined роли (dev/admin/operator/viewer) и dev-пользователя.
    - нет → log warning, требование запустить интерактивный `python -m Services.auth.bootstrap` (CLI-скрипт в пакете — единственный способ создать первого admin без `admin/admin`).
13. **Тесты Services/auth** (pytest, `tmp_path`, низкий bcrypt rounds=4):
    - bcrypt round-trip, weak password rejection
    - YamlUserStorage CRUD + atomic write (kill во время write не портит файл)
    - LockoutTracker последовательность задержек
    - AuthManager login/logout/reset_password/role CRUD
    - Last-admin invariant
    - Bootstrap из env var
14. **Тесты frontend_module:** расширить `test_access_context.py`, создать `test_access_trait.py`.
    Двухосевая модель + fallback + frozenset hashing/equality + сериализация.
15. **ADR-записи** в `Services/auth/DECISIONS.md` (Auth-001..004) и `frontend_module/DECISIONS.md` (FE-XXX).
    `python -m scripts.sync`.
16. **sentrux:** добавить boundary правила, `/sentrux-check` — pass.

## Definition of Done

- [ ] `python scripts/validate.py` — зелёный.
- [ ] `python scripts/run_framework_tests.py` — зелёный (все 2545 + новые тесты trait/context).
- [ ] `pytest Services/auth/tests/` — зелёный, coverage ≥80% по `auth_manager.py`/`storage.py`.
- [ ] `python -m scripts.sync` — без дрифта.
- [ ] `/sentrux-check` — pass.
- [ ] `/sentrux-diff` против baseline шага 0 — modularity/acyclicity без деградации.
- [ ] README.md + STATUS.md + DECISIONS.md в `Services/auth/`.
- [ ] PR-описание с диаграммой архитектуры и ссылками на ADR.

## Risks

- **Расширение `AccessTrait` может зацепить existing виджеты.** Митигация: legacy fallback + расширенные тесты.
- **`bcrypt` add-dep** — стандартная зависимость, низкий риск.
- **Atomic-write на Windows** — `os.replace` атомарен с Python 3.3+ кроссплатформенно.

## Rollback

- Откатить commit, удалить `Services/auth/`, восстановить `access_context.py`/`access_trait.py` из git.
- Нет внешних побочных эффектов (БД пустая, `users.yaml` создаётся только при первом запуске).
