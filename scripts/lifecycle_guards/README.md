# lifecycle_guards — статические стражи жизненного цикла (G2, G6, G10)

План: `plans/2026-10-03_lifecycle-owner-scope/plan.md`, задача 0.5a. Только stdlib.

```
python -m scripts.lifecycle_guards check [--root PATH] [--only g2,g6,g10]
```

Строка на finding: `<guard> <rule> <path>:<line> — <message>`; итог:
`lifecycle-guards: N findings (G2 a, G6 b, G10 c); G2 pending: P; allowlist: E entries`.
Код 0 при N = 0, иначе 1. В гейт подключено: `scripts/validate.py` → `check_lifecycle_guards()`.

## Что стережёт

| страж | правило | что ловит |
|---|---|---|
| G2 | `signature` | строка `migrated`: `owner` не ключевой, с умолчанием или аннотация не ровно `IScope` (сравнивается текст) |
| G2 | `table-row` | «гнилая строка таблицы»: метода `путь::Класс.метод` нет в файле |
| G2 | `census` | `unlisted publisher`: производственное определение `subscribe`, `add_callback`, `add_change_callback`, `add_post_execute_callback`, `add_push_listener`, `add_tap`, `register_message_handler`, `register_handler` вне таблицы |
| G6 | `R1` | `Thread(`, `Timer(`, `ThreadPoolExecutor(` — только в `Plugins/` и `Services/` |
| G6 | `R2` | `QTimer(...)` без родителя (нет позиционных и `parent=`, либо первый — `None`) |
| G6 | `R3` | `.join(<число>)` или `.join(timeout=<число>)` |
| G6 | `R4` | `.terminate()` / `.kill()` без аргументов вне `child_process_stop.py` |
| G6 | `R5` | строка `"shutdown_timeout"` вне `stop_budget.py` |
| G6 | `R6` | `.deleteLater(...)` вне `qt_lifetime.py` |
| G6 | `R7` | импорт `base_manager.core.lifetime` вне `base_manager/` |
| G6 | `R8` | `lifetime.py` импортирует что-то кроме литерального списка task-0.2 |
| G10 | `shim` | маркер `lifecycle-shim:` в комментарии вне `SHIMS` или сверх разрешённого; сумма `SHIMS` > 1 |

Правила R1–R6 — только вызовы-методы/имена из AST: `kill()` как локальное имя (так `lifetime.py`
зовёт `res.kill` через `getattr`) не считается; строки в комментариях не считаются.

## Храповик G6

`ALLOWLIST` в `tables.py`: `(правило, путь) -> AllowEntry(count, reason)`. Больше `count` —
«новое нарушение»; меньше — «запись устарела, уменьши count»; путь исчез — «запись гнилая»;
`reason` короче 10 знаков — finding. Запись только уменьшается или удаляется; новая запись —
решение владельца. Таблицы — литералы; пути с `/`.

## Что считается производственным кодом

Все `.py`, кроме тех, у кого в пути на любом уровне каталог из `tests`, `testing`, `scripts`,
`.claude`, `docs`, `plans`, `workspace`, `examples`, или путь начинается с `backend_ctl/probes/`,
`robot/`, `tools/` (каталоги `tools/` внутри модулей — производственные), и кроме `test_*.py`,
`conftest.py`. Перечень: `git ls-files` (в worktree `.git` — файл, проверяется `exists()`),
вне git — `rglob` без `.venv`, `__pycache__`, `node_modules`.

## Пределы

- Обёртка совместимости без маркера `lifecycle-shim:` не видна G10.
- Файл, не отслеживаемый git (новый, ещё не `git add`), в перечень не попадает.
- Табличные записи G2/G6 описывают наше дерево: на корне без `multiprocess_framework/modules`
  (`--root` чужого каталога) таблицы пусты, иначе каждая строка была бы «гнилой».
- Это статика: поведение (abort-проба, плагин pytest) — задача 0.5b.
