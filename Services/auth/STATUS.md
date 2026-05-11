# Services/auth — STATUS.md

**Готовность:** Foundation / Group A complete + Sub-package reorg (Auth-005)

**Обновлено:** 2026-05-11

## Текущее состояние

| Компонент | Статус | Комментарий |
|-----------|--------|-------------|
| `exceptions.py` | ✓ готово | AUTH-001..012, базовый AuthError |
| `models.py` | ✓ готово | User/Role/AuthConfig на SchemaBase + @register_schema |
| `crypto/policies.py` | ✓ готово | PasswordPolicy + LockoutPolicy (SchemaBase) |
| `crypto/hasher.py` | ✓ готово | BcryptHasher (rounds=12 prod / 4 test) |
| `security/lockout.py` | ✓ готово | In-memory LockoutTracker, thread-safe |
| `storage/yaml_users.py` | ✓ готово | YamlUserStorage с atomic write |
| `security/permissions.py` | ✓ готово | PermissionsRegistry, thread-safe |
| `interfaces.py` | ✓ готово | IAuthManager / IUserStorage / IPasswordHasher (Protocol) |
| Sub-package reorg | ✓ готово | crypto/ + storage/ + security/; фасад __init__.py; Auth-005 |
| `manager.py` | ⏳ Группа B | AuthManager(BaseManager, ObservableMixin) |
| `bootstrap.py` | ⏳ Группа B | CLI bootstrap + env var INSPECTOR_DEV_PASSWORD |
| Тесты (Группа A) | ✓ 62/62 | hasher / policies / lockout / storage |
| Тесты auth_manager | ⏳ Группа B | login/logout/CRUD/last-admin invariant |

## ADR

- Auth-001: Двухосевая модель прав (view + edit) — реализация PR3.
- Auth-002: bcrypt rounds=12/4, не argon2.
- Auth-003: YAML users/roles, SQLite audit (PR4).
- Auth-004: Bootstrap через env var / интерактивный CLI.
- Auth-005: Sub-package декомпозиция (crypto/storage/security), фасадный импорт.

## Зависимости

- `multiprocess_framework.modules.data_schema_module` — SchemaBase, FieldMeta, register_schema
- `bcrypt>=4.1` — хеширование паролей
- `PyYAML>=6.0` — хранилище пользователей

## Следующий шаг

Группа B: `manager.py` (AuthManager) + `bootstrap.py` + тесты AuthManager.
