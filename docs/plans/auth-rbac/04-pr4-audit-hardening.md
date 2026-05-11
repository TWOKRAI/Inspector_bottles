# PR4 — Audit Trail + Editable Matrix + Security Hardening

> **Положение в roadmap:** PR4 из 4 (финальный). Зависит от [PR3](03-pr3-permissions-rollout.md).
> **Контекст и общие контракты** — см. [00-metaplan.md](00-metaplan.md).

## Context

Финальный PR. Добавляет полный audit (sessions + actions), сделает матрицу пермишенов
редактируемой (через те же audit-механизмы), и закрывает все security-hardening пункты
(lockout уже из PR1, atomic-writes уже из PR1, здесь — audit fallback, recovery, statistics).

## Goals

- `AuditWriter` + `SqliteAuditStorage` через `Services/sql.GenericRepository`.
- `AuditMiddleware` на `ActionBus` — все мутации логируются.
- `SessionTracker` — login/logout пишут `SessionEntry`.
- UI: `SessionsPanel` (история входов пользователя), `AuditLogPanel` (глобальный лог с фильтрами).
- `PermissionMatrix` становится **редактируемым** (все изменения через ActionBus → audit).
- Audit fallback на JSONL при недоступности SQLite.
- `StatsManager` интеграция (login attempts/h, active sessions, failed/success ratio).

## Non-goals

- LDAP/OIDC интеграция (отдельный future PR).
- Multi-user в одном процессе (desktop-app).

## Files

**Создать:**
- `Services/auth/audit_writer.py`, `session_tracker.py`, `storage_audit.py`.
- `Services/auth/models.py` — добавить `SessionEntry`, `AuditEntry`.
- `Services/auth/tests/test_audit_*.py`.
- `multiprocess_prototype/frontend/widgets/tabs/settings/administration/sessions_panel.py`, `audit_log_panel.py`.
- `multiprocess_prototype/frontend/actions/middleware/audit_middleware.py`.

**Изменить:**
- [multiprocess_prototype/frontend/actions/bus_factory.py](../../../multiprocess_prototype/frontend/actions/bus_factory.py) — регистрация `AuditMiddleware`.
- `multiprocess_prototype/frontend/widgets/tabs/settings/administration/permission_matrix.py` — read-only → editable.
- `multiprocess_prototype/frontend/widgets/tabs/settings/administration/section.py` — добавить sections «Сессии», «Audit log».
- `Services/auth/auth_manager.py` — интеграция SessionTracker, StatsManager hooks.
- `Services/auth/DECISIONS.md` — добавить Auth-005..007.

## Steps

1. **SQLite schema** через `Services/sql.SchemaBaseMapper`:
   ```
   sessions(id, user_id, login_at, logout_at, host)
   audit_log(id, ts, user_id, action_type, resource, before_json, after_json, comment)
   ```
   Индексы: `(user_id, ts)`, `(resource, ts)`.
2. **`SqliteAuditStorage`** — `GenericRepository[AuditEntry]` + `[SessionEntry]`.
   Append-only enforcement: override `update`/`delete` → raise `AuditImmutableError`.
3. **`AuditWriter(BaseManager, ObservableMixin)`** — поток + `queue.Queue`.
   API: `log(entry)`. На stop — flush очередь, закрытие потока.
   Fallback: при exception в SQLite — `audit_fallback.jsonl` (append-only file).
   При следующем успешном write — миграция fallback'а.
4. **`SessionTracker`** — `open_session(user) -> session_id`, `close_session(session_id)`.
   Вызывается из `AuthManager.login`/`logout`.
5. **`AuditMiddleware`** — listener `ActionBus.on_action_executed`:
   ```python
   def __call__(self, action, result):
       user_id = state_store.get("auth/current_user/user_id")
       if user_id is None: return  # pre-auth действий не бывает (PR2 блокирует)
       self.writer.log(AuditEntry(
           ts=now(), user_id=user_id,
           action_type=action.type, resource=action.resource,
           before_json=json(action.before), after_json=json(action.after),
       ))
   ```
6. **`SessionsPanel`** — таблица сессий пользователя (login_at, logout_at, duration, host).
7. **`AuditLogPanel`** — глобальная таблица audit_log с фильтрами:
   - по пользователю (combobox)
   - по дате (date-range)
   - по resource (text-search)
   Пагинация по 100 записей.
8. **Editable `PermissionMatrix`:**
   - Чекбоксы становятся active.
   - Изменения через `ActionBus`:
     ```
     V2ActionBuilder.role_update(role_name, permissions_added, permissions_removed)
     ```
   - Coherence: `edit=True` авто-set `view=True`; `view=False` авто-снимает `edit`.
   - Запись в audit_log: `action_type="role.update"`, `before=old_perms`, `after=new_perms`.
   - Системные роли (`hidden_in_ui=True`) — редактирует только `dev`.
9. **`StatsManager` интеграция:**
   - `auth.login.attempts.per_hour`
   - `auth.login.failed_ratio`
   - `auth.sessions.active`
10. **Тесты audit:**
    - Append-only invariant (попытка update/delete → exception).
    - Concurrent writes (5 потоков пишут параллельно — нет потерь).
    - SQLite недоступен → fallback в JSONL.
    - Восстановление SQLite → миграция fallback.

## Definition of Done

- [ ] Изменение поля любого виджета (через ActionBus) появляется в audit_log с правильным user_id.
- [ ] SessionsPanel показывает корректную историю login/logout.
- [ ] AuditLogPanel — фильтры работают, пагинация работает.
- [ ] Editable PermissionMatrix — изменения сохраняются, проходят audit.
- [ ] Coherence-инвариант UI: `edit ⇒ view` enforced.
- [ ] Append-only тесты — зелёные.
- [ ] Fallback-тест — SQLite симуляция падения, JSONL пишется, recovery работает.
- [ ] `python scripts/run_framework_tests.py` зелёный.

## Risks

- **Performance:** audit на каждый ActionBus event. Митигация: batching в `AuditWriter` (commit'ы каждые 100мс или 50 записей).
- **SQLite locking:** один writer-thread, нет contention.
- **Disk space:** audit_log растёт. Митигация: документировать ручную ротацию (cron). Auto-rotation вынести в follow-up.
- **JSON serialization больших before/after:** truncate >10KB, помечать `<truncated>`.

## Rollback

- Откатить commit'ы PR4. Backend audit бесполезен без middleware → можно оставить без отката.
- `audit.sqlite` сохраняется на диске — следующий раз продолжит писать (append-only).
