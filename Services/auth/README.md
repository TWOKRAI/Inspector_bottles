# Services/auth — Аутентификация и RBAC

## Назначение

Модуль аутентификации и управления правами доступа для системы инспекции брака.
Обеспечивает хеширование паролей (bcrypt), хранение пользователей и ролей (YAML),
блокировку при неудачных попытках входа (in-memory), реестр permissions и
Protocol-контракты для dependency injection.

Модуль не содержит Qt-зависимостей и не импортирует `multiprocess_prototype.*`.

## Импорты

```python
from Services.auth import (
    # Исключения
    AuthError, InvalidCredentials, WeakPassword, AccountLocked,
    # Модели
    User, Role, AuthConfig,
    # Политики
    PasswordPolicy, LockoutPolicy,
    # Инфраструктура
    BcryptHasher, LockoutTracker, YamlUserStorage,
    PermissionsRegistry, PermissionDescriptor,
    # Interfaces (Protocol)
    IAuthManager, IUserStorage, IPasswordHasher,
)
```

## Точки входа

| Класс | Метод | Описание |
|-------|-------|----------|
| `BcryptHasher` | `hash(password)` | Хешировать пароль |
| `BcryptHasher` | `verify(password, hashed)` | Проверить пароль |
| `LockoutTracker` | `record_failure(username)` | Зафиксировать неудачу |
| `LockoutTracker` | `record_success(username)` | Зафиксировать успех |
| `LockoutTracker` | `is_locked(username)` | `(locked: bool, wait_sec: int)` |
| `YamlUserStorage` | `load() / save(users)` | CRUD пользователей |
| `YamlUserStorage` | `load_roles() / save_roles(roles)` | CRUD ролей |
| `PasswordPolicy` | `validate(password)` | Проверить пароль по политике |
| `PermissionsRegistry` | `register(name, description)` | Зарегистрировать permission |
| `PermissionsRegistry` | `list_all()` | Все permissions |

## Зависимости

- **Зависит от:** `data_schema_module` (SchemaBase, FieldMeta, register_schema), `bcrypt>=4.1`, `PyYAML>=6.0`
- **Используется в:** `multiprocess_prototype` (через AuthManager, Группа B), `frontend_module` (AccessContext, PR1+)
- **НЕ зависит от:** PySide6, multiprocess_prototype, frontend_module

## Примеры

### Хеширование паролей

```python
from Services.auth import BcryptHasher

hasher = BcryptHasher(rounds=12)  # prod
test_hasher = BcryptHasher(rounds=4)  # тесты

hashed = hasher.hash("MySecret@1")
assert hasher.verify("MySecret@1", hashed) is True
assert hasher.verify("WrongPass", hashed) is False
```

### Политика паролей

```python
from Services.auth import PasswordPolicy
from Services.auth.exceptions import WeakPassword

policy = PasswordPolicy()  # min=8, require_classes=3, max=72
try:
    policy.validate("weakpass")
except WeakPassword as exc:
    print(exc.code)  # AUTH-006
```

### Хранилище пользователей

```python
from Services.auth import YamlUserStorage, User
from datetime import datetime, timezone

storage = YamlUserStorage("/data/auth/users.yaml")
user = User(
    user_id="uid-001",
    username="alice",
    password_hash="$2b$12$...",
    role_name="admin",
    created_at=datetime.now(timezone.utc),
)
storage.save({"alice": user})

users = storage.load()
print(users["alice"].username)  # alice
```

### Блокировка при неудачах

```python
from Services.auth import LockoutTracker, LockoutPolicy

policy = LockoutPolicy(failed_threshold=5, delays_sec=[30, 60, 120, 240, 480])
tracker = LockoutTracker(policy)

# При неудачах
tracker.record_failure("alice")
locked, wait_sec = tracker.is_locked("alice")
if locked:
    raise AccountLocked(f"Подождите {wait_sec} сек", delay_sec=wait_sec)

# При успехе
tracker.record_success("alice")
```

### Реестр permissions

```python
from Services.auth import PermissionsRegistry

registry = PermissionsRegistry()
registry.register("tabs.recipes.view", "Просмотр вкладки Рецепты")
registry.register("tabs.recipes.edit", "Редактирование рецептов")

for perm in registry.list_all():
    print(f"{perm.name}: {perm.description}")
```

## Связь с другими модулями

```
Services/auth
    │
    ├── использует → data_schema_module (SchemaBase, register_schema)
    ├── использует → bcrypt (внешняя зависимость)
    ├── использует → PyYAML (внешняя зависимость)
    │
    └── используется в → multiprocess_prototype (AuthManager, Группа B)
    └── используется в → frontend_module (AccessContext, PR1)
```

## Структура модуля

```
Services/auth/
├── __init__.py            # Фасадный экспорт публичного API (единственный канал)
├── interfaces.py          # IAuthManager, IUserStorage, IPasswordHasher (Protocol)
├── exceptions.py          # AUTH-001..012
├── models.py              # User, Role, AuthConfig (SchemaBase + @register_schema)
├── crypto/
│   ├── __init__.py        # BcryptHasher, PasswordPolicy, LockoutPolicy
│   ├── hasher.py          # BcryptHasher
│   └── policies.py        # PasswordPolicy, LockoutPolicy (SchemaBase)
├── storage/
│   ├── __init__.py        # YamlUserStorage
│   └── yaml_users.py      # YamlUserStorage (atomic write)
├── security/
│   ├── __init__.py        # LockoutTracker, PermissionsRegistry, PermissionDescriptor
│   ├── lockout.py         # In-memory LockoutTracker (thread-safe)
│   └── permissions.py     # PermissionsRegistry (thread-safe)
├── DECISIONS.md           # Auth-001..005
├── README.md              # (этот файл)
├── STATUS.md
└── tests/
    ├── __init__.py
    ├── test_hasher.py      # 12 тестов
    ├── test_policies.py    # 14 тестов
    ├── test_lockout.py     # 15 тестов
    └── test_storage_users.py # 21 тест
```

## Public API

Импортируйте **ТОЛЬКО** через фасад:

```python
from Services.auth import BcryptHasher, PasswordPolicy, ...
```

Внутренние пути (`Services.auth.crypto.*`, `Services.auth.storage.*`,
`Services.auth.security.*`) — приватные и могут меняться между версиями.

## Примечания

- `AuthManager` реализован (коммит f9e9ed6): `AuthManager(config).initialize()` → `login/logout`, CRUD пользователей (`create_user`, `delete_user`, `update_user_role`, `reset_password`, `list_users`) и ролей (`create_role`, `update_role_permissions`, `delete_role`, `list_roles`). Все методы принимают/возвращают `dict` (Dict at Boundary).
- `bootstrap.py` реализован: CLI для первичного заполнения хранилища через `python -m Services.auth.bootstrap`.
- `password_hash` помечен `FieldMeta(hidden=True)` и исключён из `__repr__` модели User.
- `LockoutTracker` — in-memory: перезапуск сбрасывает счётчики (намеренно, см. Auth-004).
- Atomic write в `YamlUserStorage`: `tempfile.mkstemp` → `os.replace` (POSIX и Windows).

## Dict at Boundary (чеклист)

- [x] `YamlUserStorage.load()` возвращает `dict[str, User]` — Pydantic-объекты внутри хранилища.
- [x] `IAuthManager` методы принимают/возвращают `dict` (Dict at Boundary при IPC).
- [x] `User`, `Role`, `AuthConfig` — только внутри процесса; через IPC — `model_dump()`.

## DECISIONS.md модуля

- Auth-001..004 — `Services/auth/DECISIONS.md`
- Глобальный индекс — `multiprocess_framework/DECISIONS.md`
