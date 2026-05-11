# Services/auth — Архитектурные решения (DECISIONS.md)

Локальные ADR для модуля `Services/auth/`. Глобальный индекс — в
[`multiprocess_framework/DECISIONS.md`](../../multiprocess_framework/DECISIONS.md).

---

## Auth-001: Двухосевая модель прав (view + edit)

**Статус:** Зафиксировано (PR1) / Реализация — PR3.

**Контекст:**
Традиционные числовые уровни доступа (level >= N) не позволяют описать
гибкий RBAC: один виджет может быть доступен для просмотра, но не для редактирования.
Это особенно важно для оператора: видит настройки алгоритма, но не может их менять.

**Решение:**
Двухосевая модель — два независимых permissions per resource:
- `<scope>.<resource>.view` — видимость виджета.
- `<scope>.<resource>.edit` — возможность изменить значение.

Fallback: если permission не задан, используется legacy `required_level`.
Coherence invariant: `edit ⇒ view` (enforced в AccessTrait.can_view).

**Альтернативы отклонены:**
- Единый числовой level — недостаточная гранулярность.
- Матрица роль×resource с булевыми ячейками — хорошо, но сложнее в хранении;
  используется в PR4 как Admin UI поверх двухосевой модели.

**Последствия:**
- `Role.permissions: list[str]` хранит все permissions пользователя.
- `AccessContext.permissions: frozenset[str]` — быстрая O(1) проверка.
- `AccessTrait(required_view_permission, required_edit_permission)`.

---

## Auth-002: bcrypt rounds=12 (prod) / 4 (test), не argon2

**Статус:** Принято.

**Контекст:**
Необходим безопасный алгоритм хеширования паролей.

**Решение:**
bcrypt с rounds=12 в production, rounds=4 в тестах.

**Почему bcrypt, не argon2:**
- bcrypt зрелее: активно используется с 1999, широко изучен.
- argon2 (Memory-Hard, winner PHC) лучше против GPU, но требует настройки
  memory/parallelism — дополнительная сложность без явной необходимости для
  desktop-приложения инспекции без внешних атак.
- Bcrypt 72-байтное ограничение хорошо документировано и обрабатывается.

**Последствия:**
- Зависимость `bcrypt>=4.1` в `pyproject.toml`.
- `BcryptHasher(rounds=12)` в AuthManager (prod), `rounds=4` в тестах.
- `PasswordPolicy.bcrypt_rounds_prod=12`, `bcrypt_rounds_test=4`.

---

## Auth-003: YAML для users/roles, SQLite для audit/sessions

**Статус:** Принято (YAML-часть реализована в PR1, SQLite — PR4).

**Контекст:**
Нужно хранилище для пользователей/ролей и отдельное для audit trail.

**Решение:**
- `users.yaml` — единый файл с секциями `users:` и `roles:`.
- SQLite через `Services/sql.GenericRepository` — для audit log (PR4).

**Почему YAML для users/roles:**
- Просто для ручного редактирования и backup.
- Нет JOIN-запросов: пользователи и роли — маленькие списки.
- Atomic write через tempfile + os.replace — безопасно.

**Почему НЕ SQLite для users/roles:**
- Избыточно для < 100 пользователей.
- YAML проще читать и восстанавливать вручную.

**Почему SQLite для audit:**
- Audit — append-only, нужны запросы по времени/пользователю.
- Services/sql уже предоставляет GenericRepository — повторное использование.

**Последствия:**
- `YamlUserStorage` оборачивает atomic write вместо FileStorage (FileStorage — JSON-only).
- Путь к файлу конфигурируется через `AuthConfig.users_path` или `INSPECTOR_AUTH_USERS_PATH`.

---

## Auth-004: dev-роль через env var + интерактивный bootstrap

**Статус:** Принято (инфраструктура PR1, bootstrap — Группа B).

**Контекст:**
Нельзя хардкодить `admin/admin` — security baseline требует безопасного начального состояния.

**Решение:**
- Если `users.yaml` отсутствует и задан `INSPECTOR_DEV_PASSWORD` — bootstrap
  автоматически создаёт predefined роли (dev/admin/operator/viewer) и dev-пользователя.
- Если переменная не задана → log warning, требование запустить
  `python -m Services.auth.bootstrap` интерактивно.
- Роль `dev` — скрыта в UI (`hidden_in_ui=True`), только для владельца проекта.
- Hardcoded `admin/admin` **запрещён** проверкой в bootstrap.

**Альтернативы отклонены:**
- Хардкод admin/admin — явная угроза безопасности.
- Первый запуск без пароля → open access — неприемлемо для промышленного оборудования.

**Последствия:**
- `bootstrap.py` реализуется в Группе B (следующий PR-этап).
- `LockoutTracker` — in-memory, restart сбрасывает счётчики (намеренно: простота,
  нет SQLite-зависимости для lockout).

---

## Auth-005: Sub-package декомпозиция по доменам (crypto/storage/security), фасадный импорт

**Статус:** Принято (Refactor 1, PR1-ветка).

**Контекст:**
Плоская структура `Services/auth/` с 8+ файлами в корне становится трудно
навигируемой. Аналогичная проблема решена в `data_schema_module` через
декомпозицию на sub-packages (ADR-DS-005, ADR-DS-006).

**Решение:**
Разбить `Services/auth/` на три доменных sub-package:
- `crypto/`   — `hasher.py` + `policies.py` (хеширование и политики безопасности)
- `storage/`  — `yaml_users.py` (переименование `storage_users.py`)
- `security/` — `lockout.py` (переименование `lockout_tracker.py`) + `permissions.py`
               (переименование `permissions_registry.py`)

Фасад `Services/auth/__init__.py` — единственный канал публичного API.
Внутренние пути sub-package (`Services.auth.crypto.*`, `Services.auth.storage.*`,
`Services.auth.security.*`) — приватные, не использовать в коде вне `Services/auth/`.

**Паттерн идентичен:**
- `data_schema_module` (ADR-DS-005: декомпозиция interfaces.py по sub-packages)
- `data_schema_module` (ADR-DS-006: фасадный импорт через `__init__.py`)

**Альтернативы отклонены:**
- Оставить плоскую структуру — нарастающий cognitive load при добавлении
  `manager.py`, `bootstrap.py` и будущих компонентов PR2–PR4.

**Последствия:**
- Тесты `Services/auth/tests/` импортируют только через фасад: `from Services.auth import ...`.
- Внешние потребители модуля не ломаются — API фасада не изменился.
- `models.py`, `exceptions.py`, `interfaces.py` остаются в корне
  (слишком маленькие для отдельного sub-package).

---

## Auth-006: Append-only инвариант для таблицы audit_log

**Статус:** Принято (PR4, Group A).

**Контекст:**
Аудит-лог должен быть неизменяемым: после записи событие нельзя изменить
или удалить. Это требование compliance и целостности данных.

**Решение:**
Переопределить `update()` и `delete()` в `_AppendOnlyAuditRepo(GenericRepository)`
так, чтобы они всегда выбрасывали `AuditImmutableError` с кодом `AUTH-007`.
`SessionRepository` — без ограничений (logout обновляет `logout_at`).

**Альтернативы отклонены:**
- Ограничение на уровне SQLite (триггеры) — зависимость от конкретной БД,
  сложнее тестировать.
- Ограничение в middleware — легко обойти напрямую через репозиторий.

**Последствия:**
- `AuditEntry.update()` / `AuditEntry.delete()` через `SqliteAuditStorage` → `AuditImmutableError`.
- Прямой SQL (обход ORM) не защищён — осознанное ограничение desktop-приложения.

---

## Auth-007: JSONL fallback при сбое SQLite + автовосстановление

**Статус:** Принято (PR4, Group B).

**Контекст:**
SQLite может быть недоступен (locked, disk full, IO error). Нельзя терять
записи аудита при сбоях хранилища.

**Решение:**
`AuditWriter._write_batch()` при `Exception` записывает каждый `AuditEntry`
в JSONL-файл (append-mode, одна строка = одна запись).
При следующем `AuditWriter.start()` вызывается `recover_fallback()`:
читает JSONL построчно, мигрирует в SQLite, архивирует файл как
`fallback.jsonl.migrated.<utc-isoformat>`.

**Формат fallback:** `AuditEntry.model_dump_json()` — стандартная Pydantic-сериализация.

**Альтернативы отклонены:**
- Буфер в памяти без персистентности — риск потери при крэше процесса.
- Отдельная SQLite-БД для fallback — излишняя сложность.

**Последствия:**
- Конфигурируемый `fallback_path` в `AuditWriter.__init__()`.
- `recover_fallback()` идемпотентен: повторный вызов с уже мигрированным файлом
  (архив переименован) — возвращает 0.
- Повреждённые строки JSONL пропускаются с предупреждением в stdout.

---

## Auth-008: Audit через ActionBus post-execute middleware

**Статус:** Принято (PR4, Group B).

**Контекст:**
Нужен централизованный перехват всех мутаций состояния для записи в аудит-лог.
Альтернативы: хуки в каждом CRUD-методе AuthManager, или в каждом Handler.

**Решение:**
Добавить `add_post_execute_callback(cb: Callable[[Action], None])` в `ActionBus`
(framework-уровень). Callback вызывается после успешного `handler.apply()` в `execute()`.
Undo/redo — не триггерят callback (они уже учтены в аудите при первом execute).

`AuditMiddleware` в `multiprocess_prototype/` реализует этот callback:
извлекает пользователя из StateStore, формирует `AuditEntry.with_truncation()`,
вызывает `audit_writer.log()` (non-blocking).

**Регистрация:** `bus_factory.create_action_bus(..., audit_writer=..., state_store=...)`.

**Альтернативы отклонены:**
- Хуки в каждом методе AuthManager — дублирование кода, легко забыть добавить.
- Переопределение `execute()` в подклассе ActionBus — нарушает принцип
  единственного экземпляра шины.
- Использование `_change_callbacks` (без аргумента Action) — недостаточно данных.

**Последствия:**
- `ActionBus` получает три новых метода: `add_post_execute_callback`,
  `remove_post_execute_callback`, `_notify_post_execute`.
- Framework не зависит от `Services.auth` — callback типизирован как
  `Callable[[Action], None]` без упоминания AuditEntry.
- Слоевая граница соблюдена: `AuditMiddleware` живёт в `multiprocess_prototype/`.
