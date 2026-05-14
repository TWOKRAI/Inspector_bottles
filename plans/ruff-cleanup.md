# Plan: Системная чистка ruff — удаление костылей

- **Slug:** ruff-cleanup
- **Дата:** 2026-05-13
- **Статус:** DRAFT
- **Ветка:** refactor/ruff-cleanup

## Обзор

Удалить все `ignore` и `noqa` костыли из конфига ruff и кода. Привести проект к строгому линтингу:
0 ошибок ruff без глобальных ignore, минимум обоснованных per-file-ignores.
Текущее состояние: 55 `noqa` комментариев в 30 файлах, 7 глобальных ignore в `pyproject.toml`.

## Анализ текущих нарушений

| Категория | Количество | Решение |
|-----------|-----------|---------|
| `noqa: F401` в `__init__.py` с `__all__` | 8 (bridge `__init__.py`) | Убрать noqa — ruff не ругается при наличии `__all__` |
| `noqa: F401` re-export не в `__init__.py` | 5 (types.py, interfaces.py, data_schema_adapter.py, app_context.py) | Добавить `__all__` или заменить на per-file-ignores |
| `noqa: F401` yaml availability checks | 7 (tests + 1 prod) | Заменить `import yaml` на `importlib.util.find_spec("yaml")` |
| `noqa: F401` pytest_asyncio | 2 | Заменить на `importlib.util.find_spec("pytest_asyncio")` |
| `noqa: F821` forward references | 6 | Добавить `from __future__ import annotations` или `TYPE_CHECKING` блок |
| `noqa: N802` Qt method overrides | 11 | Оставить — легитимный Qt API; добавить `N802` в per-file-ignores для GUI файлов |
| `noqa: PLR2004` magic numbers в тестах | 3 | Убрать noqa — PLR не в select, не сработает |
| `noqa: ANN001` | 1 | Убрать noqa — ANN не в select |
| `noqa: E402` sys.path перед импортами | 6 | Убрать sys.path хаки (см. Phase 2) |
| `noqa` без кода (bare) | 1 (form_builder.py) | Убрать noqa, исправить строку |
| Глобальный ignore E402 | ~12 файлов с sys.path.insert | Убрать sys.path хаки через `pythonpath` в pytest и `pip install -e .` |
| Глобальный ignore E731 | ~6 настоящих нарушений | Заменить `cb = lambda` на `def cb()` |
| Глобальный ignore E722 | 2 bare except | Заменить на `except Exception` |
| Глобальный ignore E501 | неизвестно (нужен ruff check) | Исправить длинные строки (line-length=120) |
| Глобальный ignore E701/E702 | неизвестно | Исправить compound statements |
| `noqa: F401, F403` star imports | 2 (pipeline shims) | Оставить `__all__` + удалить `noqa`, или переписать shims |
| per-file-ignores `__init__.py` F401 | глобальное правило | Убрать — все `__init__.py` уже имеют `__all__` |

## Порядок выполнения

### Phase 1: Безопасные удаления noqa (нулевой риск)

- Task 1.1: Удалить избыточные noqa в __init__.py с __all__ [DONE]
- Task 1.2: Удалить noqa для не-активных правил (PLR2004, ANN001) [DONE]
- Task 1.3: Удалить bare noqa в form_builder.py [DONE]

### Phase 2: Forward references и TYPE_CHECKING (низкий риск)

- Task 2.1: Исправить F821 forward references [PENDING]

### Phase 3: Yaml/pytest_asyncio availability checks (низкий риск)

- Task 3.1: Заменить import-based проверки на importlib.util.find_spec [PENDING]

### Phase 4: E-коды — реальные исправления (средний риск)

- Task 4.1: Исправить E731 lambda assignments [PENDING]
- Task 4.2: Исправить E722 bare except [PENDING]
- Task 4.3: Исправить E701/E702 compound statements [PENDING]
- Task 4.4: Исправить E501 длинные строки [PENDING]

### Phase 5: sys.path хаки и E402 (высокий риск)

- Task 5.1: Добавить pythonpath в pytest config [PENDING]
- Task 5.2: Убрать sys.path.insert из conftest.py [PENDING]
- Task 5.3: Убрать sys.path.insert из тестовых файлов [PENDING]
- Task 5.4: Решить sys.path в production-коде (main.py, run.py) [PENDING]

### Phase 6: Финализация конфига ruff (зависит от всех Phase)

- Task 6.1: Убрать ignore и per-file-ignores из pyproject.toml [PENDING]
- Task 6.2: Настроить минимальные обоснованные per-file-ignores [PENDING]
- Task 6.3: Добавить N802 per-file-ignores для Qt GUI файлов [DONE]
- Task 6.4: Прогнать ruff check, убедиться в 0 ошибках [PENDING]
- Task 6.5: Прогнать тесты, убедиться в 2631+ passed [PENDING]

---

## Детали задач

### Task 1.1 — Удалить избыточные noqa в __init__.py с __all__

**Level:** Junior (Haiku)
**Assignee:** developer
**Goal:** Убрать `# noqa: F401` из `__init__.py`, где уже определён `__all__` (ruff не ругается при наличии `__all__`)
**Context:** При наличии `__all__` ruff понимает, что импорт используется для реэкспорта. Комментарии `noqa: F401` избыточны.
**Files:**
- `multiprocess_prototype/frontend/bridge/__init__.py` — 8 noqa: F401 (все символы в `__all__`)

**Steps:**
1. Удалить все `# noqa: F401` из указанного файла
2. Убедиться, что `__all__` содержит все реэкспортируемые имена (уже содержит)

**Acceptance criteria:**
- [ ] Файл не содержит `noqa: F401`
- [ ] `ruff check multiprocess_prototype/frontend/bridge/__init__.py` — 0 ошибок

**Out of scope:** Файлы без `__all__` — они обрабатываются в Task 1.4

---

### Task 1.2 — Удалить noqa для не-активных правил

**Level:** Junior (Haiku)
**Assignee:** developer
**Goal:** Убрать `noqa: PLR2004`, `noqa: ANN001`, `noqa: PLR0124` — эти правила не в `select`, ruff их не проверяет
**Files:**
- `multiprocess_prototype/frontend/widgets/primitives/tests/test_tree_nav_widget.py` — 3x `noqa: PLR2004`
- `multiprocess_framework/modules/frontend_module/widgets/entity_editor/base_editor_tree.py` — 1x `noqa: ANN001`
- `multiprocess_framework/modules/state_store_module/tests/test_delta.py` — 1x `noqa: PLR0124`

**Steps:**
1. Удалить все перечисленные `noqa` комментарии

**Acceptance criteria:**
- [ ] 5 файлов без лишних noqa
- [ ] `ruff check` на этих файлах — 0 ошибок

---

### Task 1.3 — Удалить bare noqa в form_builder.py

**Level:** Middle (Sonnet)
**Assignee:** developer
**Goal:** Исправить строку с bare `# noqa` в form_builder.py — понять что она делает и исправить
**Files:**
- `multiprocess_prototype/frontend/forms/form_builder.py` — строка 195

**Steps:**
1. Прочитать строку 195: `name_item.setFlags(name_item.flags() & ~(name_item.flags() & name_item.flags()))` — это бессмысленная битовая операция (flags & flags = flags, flags & ~flags = 0)
2. Определить намерение автора (скорее всего: сделать элемент нередактируемым)
3. Заменить на корректный код, например `name_item.setFlags(name_item.flags() & ~Qt.ItemIsEditable)`
4. Удалить `# noqa`

**Acceptance criteria:**
- [ ] Строка логически корректна
- [ ] Нет bare `noqa`

**Edge cases:** Проверить что `Qt.ItemIsEditable` импортирован (или `Qt.ItemFlag.ItemIsEditable` в PySide6)

---

### Task 2.1 — Исправить F821 forward references

**Level:** Middle (Sonnet)
**Assignee:** developer
**Goal:** Убрать все `noqa: F821` через добавление `from __future__ import annotations` или `TYPE_CHECKING` блок
**Context:** 6 файлов используют строковые аннотации типов для классов, не импортированных в runtime. Решение: `from __future__ import annotations` (PEP 604) делает ВСЕ аннотации строковыми, ruff не ругается.
**Files:**
- `multiprocess_prototype/main.py` — строки 31, 50 (`"SystemConfig"`, `"SystemLauncher"`)
- `multiprocess_framework/modules/config_module/tools/loader.py` — строка 122 (`"Config"`)
- `multiprocess_framework/modules/shared_resources_module/memory/platform/shm.py` — строка 54 (`"Dict[str, Any]"`)
- `multiprocess_framework/modules/shared_resources_module/handles/process_handle.py` — строка 219 (`"MemoryHandle"`)
- `multiprocess_framework/modules/process_module/plugins/base.py` — строка 201 (`PluginMetrics`)

**Steps:**
1. В каждом файле добавить `from __future__ import annotations` как первый импорт (если ещё нет)
2. Убрать `# noqa: F821` из всех 6 строк
3. Для `shm.py`: заменить `"Dict[str, Any]"` на `dict[str, Any]` (Python 3.12, generic dict встроен)
4. Для `base.py`: строка `self.metrics: PluginMetrics | None = None` — если `PluginMetrics` определён ниже в том же файле, `__future__` annotations решит проблему. Если в другом модуле — добавить `TYPE_CHECKING` импорт

**Acceptance criteria:**
- [ ] 0 файлов с `noqa: F821`
- [ ] `ruff check` на всех 6 файлах — 0 ошибок
- [ ] Тесты проходят (forward references не ломают runtime)

**Edge cases:** `from __future__ import annotations` может сломать Pydantic модели (если есть `model_validator` с `mode="before"`). Проверить что файлы не содержат Pydantic моделей. Файл `main.py` уже имеет `from __future__ import annotations` (строка 11) — значит noqa избыточен, просто удалить.

---

### Task 3.1 — Заменить import-based проверки на importlib.util.find_spec

**Level:** Middle (Sonnet)
**Assignee:** developer
**Goal:** Заменить паттерн `try: import yaml # noqa: F401` на `importlib.util.find_spec("yaml")` для проверки доступности библиотеки
**Files:**
- `multiprocess_framework/modules/message_module/factories/message_factory.py` — строка 12
- `multiprocess_framework/modules/message_module/tests/test_message.py` — строки 346, 366, 526
- `multiprocess_framework/modules/data_schema_module/tests/test_converter.py` — строки 149, 244
- `multiprocess_framework/modules/data_schema_module/tests/test_io.py` — строка 165
- `Services/sql/tests/test_sql_manager.py` — строка 8 (pytest_asyncio)
- `Services/sql/tests/test_adapters.py` — строка 8 (pytest_asyncio)

**Steps:**
1. Для тестовых файлов (yaml): заменить паттерн:
   ```python
   # Было:
   try:
       import yaml  # noqa: F401
       HAS_YAML = True
   except ImportError:
       HAS_YAML = False

   # Стало:
   HAS_YAML = importlib.util.find_spec("yaml") is not None
   ```
   Добавить `import importlib.util` в начало файла.

2. Для `message_factory.py` (production): тот же паттерн, но проверить что yaml используется далее в коде (не только проверка наличия).

3. Для pytest_asyncio: аналогично:
   ```python
   HAS_ASYNCIO = importlib.util.find_spec("pytest_asyncio") is not None
   ```

**Acceptance criteria:**
- [ ] 0 файлов с `import yaml  # noqa: F401` или `import pytest_asyncio  # noqa: F401`
- [ ] `ruff check` на всех файлах — 0 ошибок
- [ ] Тесты с yaml/asyncio skip-условиями работают корректно

---

### Task 4.1 — Исправить E731 lambda assignments

**Level:** Middle (Sonnet)
**Assignee:** developer
**Goal:** Заменить `name = lambda ...` на `def name(...)` в местах, которые ruff флагит как E731
**Context:** E731 срабатывает только на `name = lambda`, НЕ на keyword args (`formatter=lambda`). Реальных нарушений ~6-7 штук, все в тестах + 1 в auth manager.
**Files:**
- `multiprocess_framework/modules/config_module/tests/test_config.py:116` — `cb = lambda k, o, n: events.append(n)`
- `multiprocess_framework/modules/actions_module/tests/test_bus.py:226` — `cb = lambda: called.append(1)`
- `multiprocess_framework/modules/router_module/tests/test_router_manager.py:702` — `cb = lambda msg: None`
- `multiprocess_framework/modules/router_module/tests/test_router_adapter.py:78` — `fn = lambda m: None`
- `multiprocess_framework/modules/state_store_module/tests/test_state_proxy.py:282` — `callback = lambda deltas: None`
- `Services/auth/manager.py:241` — `tracker._on_active_change = lambda count: ...`

**Steps:**
1. Заменить каждую `name = lambda args: body` на `def name(args): return body`
2. Для auth/manager.py (attribute assignment): создать вложенную функцию
   ```python
   def _on_active(count):
       self._record_metric("auth.sessions.active", count)
   tracker._on_active_change = _on_active
   ```

**Acceptance criteria:**
- [ ] `ruff check --select E731` — 0 ошибок (после удаления ignore)
- [ ] Тесты проходят

**Out of scope:** lambda в keyword arguments (formatter=lambda, setter=lambda) — НЕ нарушение E731

---

### Task 4.2 — Исправить E722 bare except

**Level:** Junior (Haiku)
**Assignee:** developer
**Goal:** Заменить `except:` на `except Exception:` в 2 файлах
**Files:**
- `multiprocess_framework/tests/integration/test_performance.py:72` — `except:` в цикле получения из queue
- `multiprocess_framework/modules/data_schema_module/tools/examples/excel_formatter.py:116` — `except:` в cell width calc

**Steps:**
1. Заменить `except:` на `except Exception:` в обоих файлах

**Acceptance criteria:**
- [ ] `ruff check --select E722` — 0 ошибок
- [ ] Тесты проходят

---

### Task 4.3 — Исправить E701/E702 compound statements

**Level:** Middle (Sonnet, extended thinking)
**Assignee:** developer
**Goal:** Разбить compound statements (`;` на одной строке, `if ...: action` на одной строке) на отдельные строки
**Context:** Точный масштаб неизвестен — нужно запустить `ruff check --select E701,E702` после удаления ignore из конфига. Предварительно найдено ~9 строк с `;`.
**Files:**
- `Services/sql/action_log/log_writer.py` — 4 строки с `;`
- `Services/sql/action_log/schema_ext.py` — 1 строка
- `Services/sql/tests/test_sql_manager.py` — 1 строка
- `Services/sql/tests/test_queryset.py` — 2 строки
- `multiprocess_framework/__init__.py` — 1 строка
- Возможны другие (ruff check покажет)

**Steps:**
1. Временно убрать E701, E702 из ignore в pyproject.toml
2. Запустить `ruff check --select E701,E702` из корня проекта
3. Для каждого нарушения: разбить compound statement на отдельные строки
4. Вернуть ignore обратно (финальное удаление в Phase 6)

**Acceptance criteria:**
- [ ] `ruff check --select E701,E702` — 0 ошибок (при пустом ignore)
- [ ] Тесты проходят

---

### Task 4.4 — Исправить E501 длинные строки

**Level:** Middle+ (Sonnet, extended thinking)
**Assignee:** developer
**Goal:** Привести все строки к max 120 символов (текущий `line-length = 120`)
**Context:** Масштаб неизвестен до запуска `ruff check --select E501`. Предположительно 50-100 строк. Включает строки кода, строки комментариев, docstrings, URL.
**Files:**
- Определяются по `ruff check --select E501`

**Steps:**
1. Временно убрать E501 из ignore
2. Запустить `ruff check --select E501` — получить полный список
3. Для URL в комментариях/docstrings: допустимо `# noqa: E501` (единственное обоснованное исключение)
4. Для кода: разбить на несколько строк с правильными переносами
5. Для строковых литералов: разбить конкатенацией или implicit join

**Acceptance criteria:**
- [ ] `ruff check --select E501` — 0 ошибок (или только обоснованные URL noqa)
- [ ] Тесты проходят

**Edge cases:** Строки в `__all__` списках, строки с длинными import paths, строки с regex — могут требовать нестандартного форматирования

---

### Task 5.1 — Добавить pythonpath в pytest config

**Level:** Middle (Sonnet)
**Assignee:** developer
**Goal:** Добавить `pythonpath = ["."]` в `[tool.pytest.ini_options]` в pyproject.toml, чтобы pytest автоматически добавлял корень проекта в sys.path
**Context:** Сейчас 4 conftest.py и 4+ тестовых файла вручную делают `sys.path.insert(0, ...)` для импорта фреймворка. `pythonpath` в pytest.ini решает это централизованно.
**Files:**
- `pyproject.toml` — секция `[tool.pytest.ini_options]`

**Steps:**
1. Добавить `pythonpath = ["."]` в секцию `[tool.pytest.ini_options]`
2. Проверить что тесты запускаются из корня проекта

**Acceptance criteria:**
- [ ] `pythonpath = ["."]` в pyproject.toml
- [ ] Тесты проходят без sys.path хаков

**Dependencies:** Нет

---

### Task 5.2 — Убрать sys.path.insert из conftest.py

**Level:** Middle (Sonnet)
**Assignee:** developer
**Goal:** Удалить sys.path хаки из 4 conftest.py (после Task 5.1 они не нужны)
**Files:**
- `multiprocess_framework/modules/config_module/tests/conftest.py`
- `multiprocess_framework/modules/data_schema_module/tests/conftest.py`
- `multiprocess_framework/modules/process_module/tests/conftest.py`
- `Services/sql/tests/conftest.py`

**Steps:**
1. Удалить блоки `sys.path.insert(0, ...)` из каждого conftest.py
2. Удалить неиспользуемые `import sys`, `import os`, `from pathlib import Path` (если больше не нужны)
3. Запустить тесты каждого модуля отдельно: `pytest <module>/tests/ -v`

**Acceptance criteria:**
- [ ] 0 файлов conftest.py с sys.path.insert
- [ ] Все 4 набора тестов проходят

**Dependencies:** Task 5.1

---

### Task 5.3 — Убрать sys.path.insert из тестовых файлов

**Level:** Middle (Sonnet)
**Assignee:** developer
**Goal:** Удалить sys.path хаки из тестовых/скриптовых файлов (после Task 5.1)
**Files:**
- `Services/sql/tests/test_schema_mapper.py` — sys.path.insert + 6x noqa: E402
- `Services/sql/tests/test_repositories.py` — sys.path.insert
- `multiprocess_framework/tests/integration/run_integration_tests.py` — sys.path.insert
- `multiprocess_framework/tests/integration/template_app/template_application.py` — sys.path.insert
- `scripts/code_stats/code_stats_tokei.py` — sys.path.insert
- `scripts/validate.py` — sys.path.insert (но тут может быть нужно для standalone запуска)

**Steps:**
1. Удалить sys.path.insert и связанные noqa: E402
2. Для `scripts/` — оценить: если скрипты запускаются через `python -m scripts.X`, sys.path не нужен. Если через `python scripts/X.py` напрямую — может быть нужен. Предпочтительно: оставить sys.path в scripts/ + добавить per-file-ignores
3. Для integration tests — удалить sys.path, полагаться на pythonpath из pytest

**Acceptance criteria:**
- [ ] Тесты проходят
- [ ] `ruff check --select E402` — 0 ошибок (или обоснованные per-file-ignores для scripts/)

**Dependencies:** Task 5.1

---

### Task 5.4 — Решить sys.path в production-коде

**Level:** Senior (Opus)
**Assignee:** teamlead
**Goal:** Решить sys.path.insert в `multiprocess_prototype/main.py` и `multiprocess_prototype/run.py` — это production entry points
**Context:** `main.py` и `run.py` — точки входа. Они добавляют PROJECT_ROOT в sys.path для импорта фреймворка. При `pip install -e .` это не нужно. Но проект может запускаться без установки (через `python multiprocess_prototype/run.py`).
**Files:**
- `multiprocess_prototype/main.py:24` — `sys.path.insert(0, str(PROJECT_ROOT))`
- `multiprocess_prototype/run.py:61` — `sys.path.insert(0, str(PROJECT_ROOT))`
- `Services/hikvision_camera/__main__.py:10` — `sys.path.insert(0, str(_root))`

**Steps:**
1. Оценить: используется ли `pip install -e .` (есть `pyproject.toml` с build config)?
2. Если да — sys.path хаки можно убрать, добавить инструкцию `pip install -e .` в README
3. Если нет (запуск через `python run.py`) — оставить sys.path, добавить per-file-ignores для entry points:
   ```toml
   "multiprocess_prototype/main.py" = ["E402"]
   "multiprocess_prototype/run.py" = ["E402"]
   "Services/hikvision_camera/__main__.py" = ["E402"]
   ```
4. Принять ADR-решение о стандартном способе запуска

**Acceptance criteria:**
- [ ] Решение задокументировано
- [ ] Приложение запускается
- [ ] E402 в production-коде либо исправлен, либо обоснованно заигнорирован per-file

**Dependencies:** Нет

---

### Task 6.1 — Убрать ignore и per-file-ignores из pyproject.toml

**Level:** Middle (Sonnet)
**Assignee:** developer
**Goal:** Удалить `ignore = [...]` и `"__init__.py" = ["F401"]` из `[tool.ruff.lint]`
**Files:**
- `pyproject.toml` — строки 93-97

**Steps:**
1. Удалить строку `ignore = ["E402", "E501", "E701", "E702", "E722", "E731", "E741"]`
2. Удалить строку `"__init__.py" = ["F401"]`
3. Оставить `"multiprocess_prototype_backup/**" = [...]` (backup не трогаем)

**Acceptance criteria:**
- [ ] Секция `[tool.ruff.lint]` содержит только `select = ["E", "F"]`
- [ ] Секция `[tool.ruff.lint.per-file-ignores]` содержит только backup + обоснованные исключения

**Dependencies:** Tasks 1.x — 5.x (все исправления завершены)

---

### Task 6.2 — Настроить минимальные обоснованные per-file-ignores

**Level:** Middle (Sonnet)
**Assignee:** developer
**Goal:** Добавить per-file-ignores только для обоснованных случаев (entry points с sys.path, F401 реэкспорты без __all__)
**Context:** Некоторые файлы не являются `__init__.py`, но реэкспортируют символы. Для них нужен либо `__all__`, либо per-file-ignore.
**Files:**
- `pyproject.toml`
- `multiprocess_framework/modules/shared_resources_module/interfaces.py` — re-export
- `multiprocess_framework/modules/shared_resources_module/registry/data_schema_adapter.py` — re-export
- `multiprocess_framework/modules/process_module/types/types.py` — re-export ProcessStatus
- `multiprocess_framework/modules/shared_resources_module/types/types.py` — re-export ProcessStatus
- `multiprocess_prototype/frontend/app_context.py` — re-export AuthContext
- `multiprocess_prototype/frontend/widgets/tabs/pipeline/layout.py` — star import shim
- `multiprocess_prototype/frontend/widgets/tabs/pipeline/dag_utils.py` — star import shim

**Steps:**
1. Для re-export файлов: добавить `__all__` с реэкспортируемыми именами — предпочтительнее per-file-ignore
2. Для star import shims (layout.py, dag_utils.py): эти файлы пробрасывают `*` из framework — добавить per-file-ignores `["F401", "F403"]`
3. Для entry points (если Task 5.4 решил оставить sys.path): добавить per-file-ignores `["E402"]`

**Acceptance criteria:**
- [ ] Каждый per-file-ignore прокомментирован с причиной
- [ ] `ruff check` — 0 ошибок

**Dependencies:** Tasks 5.4, 6.1

---

### Task 6.3 — Добавить N802 per-file-ignores для Qt GUI файлов

**Level:** Middle (Sonnet)
**Assignee:** developer
**Goal:** Если в будущем включить правило N802, Qt override-методы (`paintEvent`, `sizeHint`, etc.) будут ложно срабатывать. Пока N802 не в select — просто удалить noqa: N802 из 11 файлов.
**Context:** N802 НЕ в текущем `select = ["E", "F"]`. Поэтому noqa: N802 избыточны. Если позже включить N — нужно будет добавить per-file-ignores.
**Files:**
- 5 файлов с `noqa: N802` (11 строк) — см. анализ выше

**Steps:**
1. Удалить все `# noqa: N802` из 5 файлов (правило не активно)
2. Добавить комментарий в pyproject.toml: `# При включении правила N добавить per-file-ignores для Qt виджетов (N802)`

**Acceptance criteria:**
- [ ] 0 файлов с `noqa: N802`
- [ ] `ruff check` — 0 ошибок

---

### Task 6.4 — Финальный прогон ruff check

**Level:** Middle (Sonnet)
**Assignee:** developer
**Goal:** Запустить `ruff check .` из корня и убедиться в 0 ошибках
**Files:**
- Весь проект

**Steps:**
1. `ruff check . --statistics` — получить сводку
2. Если есть ошибки — исправить или добавить обоснованный per-file-ignore с комментарием
3. Цель: 0 ошибок, 0 warnings

**Acceptance criteria:**
- [ ] `ruff check .` — exit code 0
- [ ] Конфиг не содержит глобальных ignore (только per-file с комментариями)

**Dependencies:** Tasks 6.1, 6.2, 6.3

---

### Task 6.5 — Финальный прогон тестов

**Level:** Middle (Sonnet)
**Assignee:** developer
**Goal:** Убедиться что все изменения не сломали тесты и приложение
**Steps:**
1. `python scripts/run_framework_tests.py` — framework tests
2. `python scripts/validate.py` — валидация проекта
3. Ручной запуск `python multiprocess_prototype/run.py` — проверка старта GUI

**Acceptance criteria:**
- [ ] 2631+ тестов passed
- [ ] 0 новых failures
- [ ] Приложение запускается

**Dependencies:** Task 6.4

---

## Риски и ограничения

1. **GUI код без unit-тестов.** Удаление F401 из автофикса ruff (416 ранее применённых) уже сделано. Риск: если ruff удалил импорт, который GUI использует через `from package import *` — сломается runtime. Митигация: ручной запуск приложения в Task 6.5.

2. **sys.path в entry points.** Если убрать sys.path из main.py/run.py, запуск `python run.py` без `pip install -e .` сломается. Митигация: Task 5.4 — решение принимает teamlead.

3. **E501 масштаб неизвестен.** Может быть 50 строк, может быть 200. Task 4.4 — самая трудоёмкая задача. Митигация: extended thinking, батчевое исправление.

4. **from __future__ import annotations + Pydantic.** В файлах с Pydantic моделями `from __future__ import annotations` может сломать валидаторы. Митигация: проверка в Task 2.1 — все 6 файлов НЕ содержат Pydantic моделей.

5. **star import shims (pipeline/layout.py, dag_utils.py).** Эти файлы пробрасывают `*` из framework — F403 неизбежен. Митигация: per-file-ignores с комментарием.
