# Refactoring plan: `error_module` (модуль #14)

> **Статус:** ожидает исполнения.  
> **Автор плана:** Opus 4.6, Фаза 1 мета-плана v4.1.  
> **Исполнитель:** Cursor Composer Agent (Agent mode / Composer 2).  
> **Ревьюер:** Claude Code (Opus).  
> **Ссылки:** [00_overview.md](../../plans/refactoring/00_overview.md) · [ARCHITECTURE.md](../../Inspector_prototype/multiprocess_framework/ARCHITECTURE.md) · [05_logger_module.md](../../plans/refactoring/05_logger_module.md)

---

## 0. Контекст

Второй (и последний) CRM-наследник через LoggerManager. `ErrorManager` **уже мигрирован** на CRM-инфраструктуру (STATUS: 3/8, фаза 3 CRM-миграции завершена). Код чистый: `_level_to_channel` + `log()` override работают правильно, severity routing реально используется. Модуль компактный (570 LOC, 7 `.py` файлов).

**Проблема:** модуль не формализован документально:
1. **Нет `DECISIONS.md`** — ни одного ADR, хотя решения существенны (наследование vs композиция, `_level_to_channel` до `super().__init__()`, нормализация конфига).
2. **ARCHITECTURE.md §6.14** — заглушка `TODO (после модуля #14)` (строка 742).
3. **Тестовые пробелы** — 12 тестов покрывают конструктор и конфиг, но не покрывают level routing, fallback, `track_error()`, `log()` override для DEBUG/INFO.
4. **`core/__init__.py`** не экспортирует `ErrorManager` — несогласованность с остальными модулями.
5. **README.md** — 4 неточности: `ChannelRoutingConfig` вместо `SchemaBase`, `RegisterBase` вместо `SchemaBase`, путь `refactored` (не существует), устаревшее число тестов.

**Цель:** формализовать error_module — документация + тесты + мелкие code hygiene правки. Без изменения публичного API и core логики.

**Сложность:** ★★☆☆☆ — 80% документация + тесты, 20% мелкие правки.

---

## 1. Текущее состояние (baseline)

- **Файлов:** 7 `.py` (без tests/__pycache__)
- **LOC:** 570 (без тестов)
- **Тестов:** 2 файла (test_error_manager.py — 73 LOC, 7 тестов; test_error_config.py — 47 LOC, 5 тестов). Итого **12 тестов**.
- **Публичный API:** `ErrorManager`, `ErrorManagerConfig`, `expand_error_manager_config`, `IErrorManager`, `ErrorConfigLike`

### 1.1. Внешние потребители

| Модуль | Что импортирует | Затронут? |
|--------|----------------|-----------|
| process_module | `ErrorManager`, `ErrorManagerConfig` | Нет (API не меняется) |
| process_manager_module | `ErrorManager` | Нет |

### 1.2. Файлы — что НЕ меняется в логике

| Файл | LOC | Статус |
|------|-----|--------|
| `core/error_manager.py` | 280 | Логика без изменений. Только добавить export в `core/__init__.py`. |
| `core/error_config_assembly.py` | 61 | Без изменений. |
| `configs/error_manager_config.py` | 40 | Без изменений. |
| `interfaces.py` | 147 | Без изменений. |
| `__init__.py` | 31 | Без изменений. |

---

## 2. Атомарные шаги

### Шаг 0 — Baseline и аудит

1. `pytest error_module/tests -v` — записать число тестов и статус.
2. Подсчитать LOC: `find modules/error_module -name "*.py" -not -path "*/tests/*" -not -path "*__pycache__*" | xargs wc -l`
3. Подтвердить внешних потребителей:
   ```bash
   grep -rn "from.*error_module\|import.*error_module\|ErrorManager\|ErrorManagerConfig" --include="*.py" modules/ | grep -v error_module | grep -v __pycache__
   ```
4. Записать baseline: 12 тестов, 7 файлов, ~570 LOC.
5. Коммит: `docs(error_module): baseline audit before formalization`.

---

### Шаг 1 — Добавить `ErrorManager` в `core/__init__.py` export

**Файл:** `modules/error_module/core/__init__.py`

**Было:**
```python
from .error_config_assembly import expand_error_manager_config

__all__ = ["expand_error_manager_config"]
```

**Стало:**
```python
from .error_config_assembly import expand_error_manager_config
from .error_manager import ErrorManager

__all__ = ["expand_error_manager_config", "ErrorManager"]
```

**Обоснование:** консистентность — `core/__init__.py` logger_module, router_module, dispatch_module все экспортируют основной класс.

Коммит: `refactor(error_module): export ErrorManager from core/__init__.py`.

---

### Шаг 2 — Тесты: level routing, fallback, track_error, log() override

**Создать** `tests/test_error_level_routing.py` (~120–150 LOC).

#### Класс `TestLevelRouting` — 6 тестов:

1. `test_level_routes_after_initialize` — после `initialize()` маппинг содержит CRITICAL→critical_file, ERROR→errors_file, WARNING→warnings_file.
2. `test_critical_routes_to_critical_file` — `em.critical("msg")` → `messages_processed > 0`.
3. `test_error_routes_to_errors_file` — `em.error("msg")` → `messages_processed > 0`.
4. `test_warning_routes_to_warnings_file` — `em.warning("msg")` → `messages_processed > 0`.
5. `test_fallback_critical_to_errors_file_when_no_critical_channel` — конфиг без `critical_file` → CRITICAL маппится на `errors_file`.
6. `test_fallback_warning_to_errors_file_when_no_warnings_channel` — конфиг без `warnings_file` → WARNING маппится на `errors_file`.

#### Класс `TestLogOverride` — 3 теста:

1. `test_debug_goes_to_parent_log` — DEBUG не падает, идёт через parent.
2. `test_info_goes_to_parent_log` — INFO не падает, идёт через parent.
3. `test_messages_processed_counts_correctly` — после 3 error/warning → `messages_processed >= 3`.

#### Класс `TestTrackError` — 3 теста:

1. `test_track_error_calls_log_exception` — с контекстом `{"message": "...", "module": "..."}`.
2. `test_track_error_with_empty_context` — без контекста, не падает.
3. `test_track_error_with_dict_message` — `context={"message": {"key": "val"}}` конвертируется в строку.

**Тесты зелёные** (и новые, и существующие).

Коммит: `test(error_module): add level routing, fallback, track_error, log override tests`.

---

### Шаг 3 — Интеграционный тест: severity → реальный файл

**Создать** `tests/test_error_integration.py` (~60–80 LOC).

#### Класс `TestErrorIntegration` — 2 теста:

1. `test_error_writes_to_file(tmp_path)`:
   - Конфиг с `enable_batching=False`, `errors_file` → `tmp_path / "errors.log"`.
   - `em.error("integration test error")` → проверить `error_log.exists()` и `"integration test error" in content`.

2. `test_log_exception_writes_traceback_to_file(tmp_path)`:
   - Конфиг с `enable_batching=False`.
   - `em.log_exception(exc, include_stacktrace=True)` → проверить traceback в файле.

**Важно:** `enable_batching=False` проверяет direct write path в `ErrorManager.log()` (ветка `else: ch.write()`).

Коммит: `test(error_module): add integration test for file writing`.

---

### Шаг 4 — Документация

#### 4.1. DECISIONS.md (новый файл `modules/error_module/DECISIONS.md`)

```markdown
# error_module — Архитектурные решения

> Ссылки: [`../../DECISIONS.md`](../../DECISIONS.md) · [`../logger_module/DECISIONS.md`](../logger_module/DECISIONS.md)

## ADR-EM-001: ErrorManager как наследник LoggerManager (не композиция)

- **Дата:** 2026-03-12
- **Статус:** принято
- **Контекст:** ErrorManager нуждается в каналах, буферизации, scope-based routing для DEBUG/INFO — всё есть в LoggerManager. Альтернатива: композиция (ErrorManager содержит LoggerManager).
- **Решение:** Наследование `ErrorManager(LoggerManager)`. Переиспользует CRM-инфраструктуру (ChannelRegistry, BatchBuffer, Dispatcher), добавляет только severity routing через `_level_to_channel` и `log()` override.
- **Не сливать:** ErrorManager остаётся отдельным модулем — severity routing опциональная специализация.
- **Отклонено:** Композиция — избыточная обёртка без выгоды.

## ADR-EM-002: Level-based routing через _level_to_channel dict

- **Дата:** 2026-03-12
- **Статус:** принято
- **Контекст:** Маппинг WARNING → warnings_file, ERROR → errors_file, CRITICAL → critical_file. Альтернатива: через CRM's Dispatcher.
- **Решение:** `Dict[str, str]` с O(1) lookup в `log()`. Проще и быстрее Dispatcher для 3 уровней.
- **Fallback:** Если канал отсутствует — используется `errors_file`.

## ADR-EM-003: _normalize_error_config() как модульная функция

- **Дата:** 2026-03-31
- **Статус:** принято
- **Решение:** Модульная функция в `error_manager.py`, не метод класса. Паттерн совпадает с logger_module.

## ADR-EM-004: expand_error_manager_config() в отдельном файле

- **Дата:** 2026-03-31
- **Статус:** принято
- **Решение:** `core/error_config_assembly.py` — единственное место merge severity-каналов. configs/ содержит только поля, core/ содержит логику сборки.

## ADR-EM-005: _level_to_channel инициализация до super().__init__()

- **Дата:** 2026-04-03
- **Статус:** принято
- **Контекст:** `LoggerManager.__init__()` выставляет `LoggerManager._instance = self`. Косвенные вызовы через `get_logger()` могут дёрнуть `ErrorManager.log()` → `self._level_to_channel` → `AttributeError`.
- **Решение:** `self._level_to_channel = {}` ДО `super().__init__()`. Пустой dict безопасен: все уровни fallback на parent.
```

#### 4.2. Главный DECISIONS.md — добавить строку

В таблице «Модульные решения» (`multiprocess_framework/DECISIONS.md`, после строки `process_manager_module`, строка ~1851):

```
| `error_module` | [`modules/error_module/DECISIONS.md`](modules/error_module/DECISIONS.md) | Observability | ADR-EM-001…005 (наследование LoggerManager, _level_to_channel, normalize config, expand assembly, init order) |
```

#### 4.3. ARCHITECTURE.md §6.14

Заменить строку 742 (`### 6.14 \`error_module\` — *TODO (после модуля #14)*`) на:

```markdown
### 6.14 `error_module` — severity-based channel routing

**Роль:** Специализированный менеджер ошибок — наследник `LoggerManager` с level-based routing. WARNING/ERROR/CRITICAL направляются в отдельные файлы; DEBUG/INFO — через scope-based routing родителя.

**`ErrorManager`** (`LoggerManager`) — severity routing через `_level_to_channel` dict. Использует CRM-инфраструктуру (ChannelRegistry, BatchBuffer) через наследование. Добавляет `log_exception()` с traceback и `track_error()` для ObservableMixin.

```
ErrorManager (LoggerManager → ChannelRoutingManager)
    ├── _level_to_channel  — {CRITICAL→critical_file, ERROR→errors_file, WARNING→warnings_file}
    ├── log() override     — severity routing для WARNING+, scope fallback для DEBUG/INFO
    ├── log_exception()    — traceback + self.error()
    ├── track_error()      — интеграция с ObservableMixin._track_error()
    └── ErrorManagerConfig (SchemaBase) → expand_error_manager_config → LoggerManagerConfig
```

Ключевые решения (ADR-EM-001…005):
- ErrorManager — наследник LoggerManager, не композиция и не слияние.
- `_level_to_channel` — O(1) dict lookup, не через Dispatcher.
- `_level_to_channel = {}` до `super().__init__()` — защита от AttributeError.

📖 [`modules/error_module/README.md`](modules/error_module/README.md) · [`modules/error_module/DECISIONS.md`](modules/error_module/DECISIONS.md)
```

#### 4.4. README.md — исправить 4 неточности

| Строка | Было | Стало |
|--------|------|-------|
| 40 | `ErrorManagerConfig(ChannelRoutingConfig) для конфигурации путей` | `ErrorManagerConfig(SchemaBase) для конфигурации путей` |
| 135 | `# Вариант 3: RegisterBase-конфиг` | `# Вариант 3: SchemaBase-конфиг` |
| 276 | `ErrorManagerConfig наследует ChannelRoutingConfig` | `ErrorManagerConfig наследует SchemaBase` |
| 387 | `cd Inspector_prototype/multiprocess_framework/refactored` | `cd Inspector_prototype/multiprocess_framework/modules` |

#### 4.5. STATUS.md — обновить

1. `## Текущий этап: 3 / 8` → `## Текущий этап: 5 / 8`
2. Оценка `Тесты`: `7` → `9`, комментарий: `~25 тестов; level routing, fallback, track_error, integration`
3. Чеклист — отметить:
   ```
   - [x] Этап 4: DECISIONS.md (ADR-EM-001…005), §6.14 в ARCHITECTURE.md
   - [x] Этап 5: Тестовое покрытие (level routing, fallback, track_error, integration)
   ```
4. Добавить в историю: `| 2026-04-10 | DECISIONS.md, ARCHITECTURE.md §6.14, тесты level routing/integration, README fix | 4–5 |`

Коммит: `docs(error_module): add DECISIONS.md, fill ARCHITECTURE.md §6.14, fix README/STATUS`.

---

### Шаг 5 — Финальная валидация

1. `pytest error_module/tests -v` — все зелёные.
2. `pytest logger_module/tests -v` — зелёные (кросс-зависимость через наследование).
3. `python Inspector_prototype/scripts/run_framework_tests.py` — все зелёные.
4. Метрики «после»:
   - Файлов: 7 `.py` (без тестов) — без изменений.
   - LOC: ~572 (+2 строки в `core/__init__.py`).
   - Тест-файлов: 4.
   - Тестов: ~25.
5. Обновить `plans/refactoring/00_overview.md` строка #14:
   ```
   | 14 | `error_module` | 7 | 580 | 2 | TODO | TODO | 7 | ~572 | 4 (~25 passed) |
   ```
6. Коммит: `refactor(error_module): final validation and metrics`.

---

## 3. Что НЕ делать

1. **НЕ** менять `core/error_manager.py` core логику (`_level_to_channel`, `log()`, `_normalize_error_config()`, `_setup_level_routes()`) — всё работает.
2. **НЕ** менять `core/error_config_assembly.py` — корректна.
3. **НЕ** менять `configs/error_manager_config.py` — стабилен.
4. **НЕ** менять `interfaces.py` — полный.
5. **НЕ** менять `__init__.py` — lazy loading работает.
6. **НЕ** сливать ErrorManager в LoggerManager (ADR-EM-001).
7. **НЕ** менять публичный API.
8. **НЕ** трогать другие модули кроме главного `DECISIONS.md` и `ARCHITECTURE.md`.
9. **НЕ** добавлять AlertChannel / Telegram / Slack (этапы 6+ — отдельная задача).

---

## 4. Кросс-модульные изменения (ВАЖНО для Composer)

**Никаких кросс-модульных изменений в коде.** Только два общих `.md` файла.

| Файл | Что меняется |
|------|-------------|
| `modules/error_module/core/__init__.py` | Добавить export `ErrorManager` (+2 строки) |
| `modules/error_module/tests/test_error_level_routing.py` | **СОЗДАТЬ** (~120-150 LOC, 12 тестов) |
| `modules/error_module/tests/test_error_integration.py` | **СОЗДАТЬ** (~60-80 LOC, 2 теста) |
| `modules/error_module/DECISIONS.md` | **СОЗДАТЬ** (ADR-EM-001…005) |
| `modules/error_module/README.md` | Исправить 4 неточности (строки 40, 135, 276, 387) |
| `modules/error_module/STATUS.md` | Обновить этап, оценки, чеклист, историю |
| `multiprocess_framework/ARCHITECTURE.md` | Заменить заглушку §6.14 (строка 742, ~20 строк) |
| `multiprocess_framework/DECISIONS.md` | Добавить 1 строку в таблицу «Модульные решения» (после строки ~1851) |
| `plans/refactoring/00_overview.md` | Обновить строку #14 с метриками «после» |

**Порядок:** Шаг 0 → Шаг 1 → Шаг 2 → Шаг 3 → Шаг 4 → Шаг 5. Атомарные коммиты.

---

## 5. Definition of Done (модуль #14)

- [ ] `core/__init__.py` экспортирует `ErrorManager`
- [ ] Тесты level routing: CRITICAL → critical_file, ERROR → errors_file, WARNING → warnings_file
- [ ] Тесты fallback: CRITICAL/WARNING → errors_file при отсутствии severity-канала
- [ ] Тесты log() override: DEBUG/INFO → parent LoggerManager.log()
- [ ] Тест track_error() — с контекстом, без контекста, с dict message
- [ ] Тест messages_processed — корректный счёт
- [ ] Интеграционный тест: ERROR → реальный файл
- [ ] Интеграционный тест: log_exception() с traceback → файл
- [ ] Все тесты error_module зелёные
- [ ] Все тесты logger_module зелёные (кросс-зависимость)
- [ ] `run_framework_tests.py` зелёный
- [ ] `DECISIONS.md` создан (ADR-EM-001…005)
- [ ] Главный `DECISIONS.md` обновлён
- [ ] ARCHITECTURE.md §6.14 заполнен
- [ ] README.md — исправлены неточности
- [ ] STATUS.md — обновлён
- [ ] Метрики «после» в `00_overview.md`

---

## 6. Целевые метрики

| Метрика | До | После (цель) |
|---------|-----|--------------|
| Файлов (без tests) | 7 | 7 (без изменений) |
| LOC (без tests) | 570 | ~572 (+2 строки в core/__init__.py) |
| Тест-файлов | 2 | 4 (+test_error_level_routing, +test_error_integration) |
| Тестов (pytest) | 12 | ~25 (+13 новых) |
| DECISIONS.md | нет | ADR-EM-001…005 |
| ARCHITECTURE.md §6.14 | заглушка | заполнен |
| Публичный API | Без изменений | Без изменений |

---

## 7. Верификация

После выполнения всех шагов:

```bash
# Из директории Inspector_prototype
cd Inspector_prototype

# 1. Тесты error_module
python -m pytest multiprocess_framework/modules/error_module/tests -v

# 2. Тесты logger_module (кросс-зависимость)
python -m pytest multiprocess_framework/modules/logger_module/tests -v

# 3. Полная валидация фреймворка
python scripts/run_framework_tests.py

# 4. Метрики LOC
find multiprocess_framework/modules/error_module -name "*.py" -not -path "*/tests/*" -not -path "*__pycache__*" | xargs wc -l
```
