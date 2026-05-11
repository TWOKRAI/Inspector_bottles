# Services — STATUS.md

Прикладной слой между framework и `multiprocess_prototype/`. Сервисы — реализации, специфичные для приложения «Inspector_bottles», но переиспользуемые между его процессами. Источник истины по конкретному сервису — `Services/{name}/STATUS.md`.

**Слои:** `multiprocess_framework → Services → Plugins → multiprocess_prototype`.

**Обновлено:** 2026-05-10 — приведение к стандарту валидации (`__init__.py`, `interfaces.py`, `STATUS.md`, `README.md`, `tests/`).

| Сервис | Готовность | Комментарий | ADR |
|--------|-----------|-------------|-----|
| `sql` | production | SQLManager + Repository + UoW + QuerySet; выехал из `multiprocess_framework/modules/sql_module/` | ADR-121 |
| `hikvision_camera` | production | Плагин-обёртка над HikSDK + core/sdk_app; выехал из плагинов | ADR-122 |
| `auth` | foundation | User/Role storage + RBAC API (PR1) | ADR-Auth-001..004 |
| `Operation_crop` | utility | Утилита для нарезки кадров | — |
| `Region_processors` | utility | Регион-процессоры (заготовки для пайплайнов) | — |

## Правила слоя

1. Сервис **не импортирует** `multiprocess_prototype.*` (enforced через `.sentrux/rules.toml`).
2. У каждого сервиса: `__init__.py` с публичным API, `interfaces.py` с Protocol-контрактами, `STATUS.md`, `README.md`, `tests/`.
3. Зависимости — только `multiprocess_framework.*` и сторонние библиотеки (SQLAlchemy, HikSDK и т.п.).
4. Plugins используют сервисы через их публичный API; framework — нет.

## Связанные документы

- [`multiprocess_framework/DECISIONS.md`](../multiprocess_framework/DECISIONS.md) — ADR-121 (carve-out sql), ADR-122 (carve-out hikvision)
- [`.sentrux/rules.toml`](../.sentrux/rules.toml) — boundaries
- [`CLAUDE.md`](../CLAUDE.md) — корневой контекст проекта
