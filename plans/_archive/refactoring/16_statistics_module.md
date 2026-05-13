# Refactoring plan: `statistics_module` (модуль #15)

> **Статус:** выполнено (2026-04-10).  
> **Автор плана:** Opus 4.6, Фаза 1 мета-плана v4.1.  
> **Исполнитель:** Cursor Composer Agent (Agent mode / Composer 2).  
> **Ревьюер:** Claude Code (Opus).  
> **Ссылки:** [00_overview.md](../../plans/refactoring/00_overview.md) · [ARCHITECTURE.md](../../multiprocess_framework/ARCHITECTURE.md) · [15_erorr_module.md](../../plans/refactoring/15_erorr_module.md) · [05_logger_module.md](../../plans/refactoring/05_logger_module.md)

---

## 0. Контекст

Третий (и последний) Observability-layer CRM-наследник. `StatsManager` наследует `ChannelRoutingManager` **напрямую** (ADR-022), а НЕ через `LoggerManager` (в отличие от ErrorManager). Код чистый: stage 4/8, 981 LOC, 24 теста. Модуль компактный (13 `.py` файлов).

**Ключевое архитектурное отличие от error_module/logger_module:**

```
ChannelRoutingManager (CRM)
    ├── LoggerManager (scope + level routing)
    │   └── ErrorManager (severity routing)
    └── StatsManager (metric aggregation — ПРЯМОЙ наследник CRM, ADR-022)
```

StatsManager НЕ наследует LoggerManager, потому что scope/level избыточны для метрик. Вместо этого — собственная агрегация (counter sum, gauge last, timing p95) через `AggregationWindow(IBufferStrategy)`.

**Проблема:** модуль не формализован документально:
1. **Нет `DECISIONS.md`** — ни одного локального ADR, хотя решений много (прямое наследование CRM, dual-layer storage, sentinel-паттерн, _metric_key дупликация, AggregationWindow вместо BatchBuffer).
2. **ARCHITECTURE.md §6.15** — заглушка `TODO (после модуля #15)` (строка 766).
3. **Тестовые пробелы** — 24 теста покрывают lifecycle, metric types, tags, N-counting, flush, config. Но нет: интеграции FileStatsChannel с файлом, LogStatsChannel верификации, thread-safety, StatsAdapter тестов, get_metric с tags.
4. **README.md** — 4 неточности: `RegisterBase` вместо `SchemaBase` (строки 28, 204), `config/` вместо `configs/` (строка 257), `refactored/modules/` (строка 287).

**Цель:** формализовать statistics_module — документация + тесты + README fix. Без изменения публичного API и core логики.

**Сложность:** ★★☆☆☆ — 80% документация + тесты, 20% README-правки.

---

## 1. Текущее состояние (baseline)

- **Файлов:** 13 `.py` (без tests/__pycache__)
- **LOC:** 981 (без тестов)
- **Тестов:** 3 файла (test_stats_manager.py — 241 LOC, ~19 тестов; test_aggregation_window.py — 58 LOC, 3 теста; test_stats_config.py — 30 LOC, 2 теста). Итого **24 теста**.
- **Публичный API:** `StatsManager`, `StatsManagerConfig`, `IStatsManager`, `MetricRecord`, `MetricType`, `AggregationWindow`, `LogStatsChannel`, `FileStatsChannel`, `StatsAdapter`

### 1.1. Внешние потребители

| Модуль | Что импортирует / использует | Затронут? |
|--------|------------------------------|-----------|
| process_module | `StatsManager`, `StatsManagerConfig`, `StatsAdapter` (из process_managers.py) | Нет (API не меняется) |
| base_manager (ObservableMixin) | `_record_metric` / `_record_timing` маршрутизируются в StatsManager (строки 126-144) | Нет |
| dispatch_module | `_record_metric` / `_record_timing` через ObservableMixin | Нет |
| command_module | `_record_metric` через ObservableMixin | Нет |
| sql_module | `_record_timing` через ObservableMixin | Нет |

### 1.2. Как ObservableMixin маршрутизирует метрики

```python
# base_manager/mixins/observable_mixin.py:126-144
def _record_metric(self, metric_name, value=1, tags=None):
    if not self._call_manager('stats', 'record_metric', metric_name, value, tags or {}):
        self._call_manager('statistics', 'record_metric', metric_name, value, tags or {})

def _record_timing(self, metric_name, duration, tags=None):
    if not self._call_manager('stats', 'record_timing', metric_name, duration, tags or {}):
        self._call_manager('statistics', 'record_timing', metric_name, duration, tags or {})
```

Любой менеджер с ObservableMixin → `_record_metric()` → StatsManager.record_metric().

### 1.3. Файлы — что НЕ меняется в логике

Все 13 `.py` файлов остаются без изменений. Нулевые изменения в production-коде.

---

## 2. Атомарные шаги

### Шаг 0 — Baseline и аудит

1. `pytest statistics_module/tests -v` — записать число тестов и статус.
2. Подсчитать LOC: `find modules/statistics_module -name "*.py" -not -path "*/tests/*" -not -path "*__pycache__*" | xargs wc -l`
3. Подтвердить внешних потребителей:
   ```bash
   grep -rn "from.*statistics_module\|import.*statistics_module\|StatsManager\|StatsManagerConfig\|StatsAdapter" --include="*.py" modules/ | grep -v statistics_module | grep -v __pycache__
   ```
4. Записать baseline: 24 теста, 13 файлов, 981 LOC.
5. Коммит: `docs(statistics_module): baseline audit before formalization`.

---

### Шаг 1 — Тесты: интеграция каналов, get_metric с tags, thread-safety

**Создать** `tests/test_stats_integration.py` (~150–180 LOC).

#### Класс `TestFileStatsChannelIntegration` — 3 теста:

1. `test_write_to_real_file(tmp_path)`:
   - Создать `FileStatsChannel(file_path=str(tmp_path / "metrics.jsonl"))`.
   - `ch.write({"timestamp": 1.0, "total_count": 1, "metrics": [{"name": "x", "type": "counter", "count": 5}]})`.
   - Проверить файл существует и `json.loads(content)["metrics"][0]["count"] == 5`.

2. `test_write_csv_format(tmp_path)`:
   - `FileStatsChannel(file_path=..., format="csv")`.
   - Записать и проверить CSV-строку в файле.

3. `test_write_creates_parent_dirs(tmp_path)`:
   - `FileStatsChannel(file_path=str(tmp_path / "deep" / "nested" / "metrics.jsonl"))`.
   - Проверить что parent dirs созданы и файл записан.

#### Класс `TestLogStatsChannelIntegration` — 2 теста:

1. `test_write_calls_performance()`:
   - Mock `logger_manager` с `performance = MagicMock()`.
   - `LogStatsChannel(logger_manager=mock_logger).write({...})`.
   - `mock_logger.performance.assert_called_once()`.

2. `test_write_without_logger_returns_error()`:
   - `LogStatsChannel(logger_manager=None).write({...})`.
   - Проверить `result["status"] == "error"`.

#### Класс `TestGetMetricWithTags` — 2 теста:

1. `test_get_metric_returns_first_match_ignoring_tags()`:
   - `mgr.increment("x", tags={"region": "eu"})` + `mgr.increment("x", tags={"region": "us"})`.
   - `mgr.get_metric("x")` — возвращает первое совпадение по name.
   - `mgr.get_all_metrics()` — оба присутствуют (2 ключа).

2. `test_get_metric_missing_returns_none()`:
   - `mgr.get_metric("nonexistent")` returns `None`.

#### Класс `TestThreadSafety` — 2 теста:

1. `test_concurrent_record_metric()`:
   - 10 потоков, каждый `mgr.record_metric("ops", 1)` × 100.
   - После join: `mgr.get_metric("ops")["count"] == 1000.0`.

2. `test_concurrent_mixed_operations()`:
   - 5 потоков record_metric + 5 потоков get_all_metrics.
   - Smoke test: не должно быть исключений.

**Тесты зелёные.**

Коммит: `test(statistics_module): add integration, tags, thread-safety tests`.

---

### Шаг 2 — Тест StatsAdapter

**Создать** `tests/test_stats_adapter.py` (~80–100 LOC).

#### Класс `TestStatsAdapter` — 4 теста:

1. `test_setup_registers_commands()`:
   - Mock process с `command_manager.register_command = MagicMock()`.
   - `StatsAdapter(stats_manager, process=mock_process).setup()`.
   - Проверить `register_command.call_count == 5`.

2. `test_setup_without_process_returns_false()`:
   - `StatsAdapter(stats_manager, process=None).setup()` → `False`.

3. `test_setup_without_command_manager_returns_false()`:
   - Mock process без `command_manager` → `False`.

4. `test_is_initialized_after_setup()`:
   - После `setup()` → `True`. Без `setup()` → `False`.

Коммит: `test(statistics_module): add StatsAdapter command registration tests`.

---

### Шаг 3 — Документация

#### 3.1. DECISIONS.md (новый файл `modules/statistics_module/DECISIONS.md`)

```markdown
# statistics_module — Архитектурные решения

> Ссылки: [`../../DECISIONS.md`](../../DECISIONS.md) (ADR-022)

## ADR-SM-001: StatsManager как прямой наследник ChannelRoutingManager (не LoggerManager)

- **Дата:** 2026-03-15
- **Статус:** принято
- **Контекст:** Нужен менеджер метрик. Рассматривалось наследование от LoggerManager (как ErrorManager). LoggerManager добавляет scope/level — не нужны для метрик.
- **Решение:** `StatsManager(ChannelRoutingManager, IStatsManager)` — прямой наследник CRM. Получает каналы, буферизацию, dispatcher без overhead LoggerManager.
- **Глобальная ссылка:** ADR-022 в `../../DECISIONS.md`.
- **Отклонено:** `StatsManager(LoggerManager)` — scope/level избыточны.

## ADR-SM-002: Dual-layer storage (_metrics + AggregationWindow)

- **Дата:** 2026-03-31
- **Статус:** принято
- **Контекст:** Метрики нужны в двух режимах: (1) императивный запрос `get_metric()`, (2) периодический flush снапшотов в каналы.
- **Решение:** `self._metrics` (Dict[str, MetricRecord]) для live-запросов + `AggregationWindow` (IBufferStrategy) для flush. Каждый record_metric() пишет в оба.
- **Компромисс:** Двойная запись, стоимость O(1), данные консистентны.

## ADR-SM-003: Sentinel-паттерн (_STATS_SENTINEL) для N-channel broadcast

- **Дата:** 2026-03-31
- **Статус:** принято
- **Контекст:** Если enqueue для каждого из N каналов — метрики считаются N раз.
- **Решение:** `_enqueue_to_buffer()` использует sentinel `"__stats__"`. `_do_flush()` транслирует снапшот во ВСЕ каналы через `_channel_registry.all()`.

## ADR-SM-004: _metric_key дупликация — намеренная изоляция слоёв

- **Дата:** 2026-03-31
- **Статус:** принято
- **Контекст:** `_metric_key(name, tags)` определена в `stats_manager.py:31` и `aggregation_window.py:18`.
- **Решение:** Намеренная изоляция. Вынос в общий модуль создаёт нежелательную связность.
- **Компромисс:** При изменении формата ключа — менять в двух местах.

## ADR-SM-005: StatsAdapter для CommandManager-интеграции

- **Дата:** 2026-04-01
- **Статус:** принято
- **Решение:** `StatsAdapter(BaseAdapter)` регистрирует 5 команд: get_metrics, get_metric, reset_metrics, stats_snapshot, flush_stats. Паттерн совпадает с другими адаптерами.

## ADR-SM-006: AggregationWindow как IBufferStrategy (не BatchBuffer)

- **Дата:** 2026-03-31
- **Статус:** принято
- **Контекст:** CRM предоставляет BatchBuffer (collect + flush). Для метрик нужна агрегация: counter sum, gauge last, timing p95.
- **Решение:** `AggregationWindow(IBufferStrategy)` — агрегация MetricRecord вместо простого батчинга. Flush отправляет агрегированный снапшот.
- **Отклонено:** BatchBuffer — не поддерживает агрегацию.
```

#### 3.2. Главный DECISIONS.md — добавить строку

В таблице «Модульные решения» (`multiprocess_framework/DECISIONS.md`, после строки `error_module`, строка ~1852):

```
| `statistics_module` | [`modules/statistics_module/DECISIONS.md`](modules/statistics_module/DECISIONS.md) | Observability | ADR-SM-001…006 (прямое наследование CRM, dual-layer storage, sentinel broadcast, _metric_key isolation, StatsAdapter, AggregationWindow) |
```

#### 3.3. ARCHITECTURE.md §6.15

Заменить строку 766 (`### 6.15 \`statistics_module\` — *TODO (после модуля #15)*`) на:

```markdown
### 6.15 `statistics_module` — метрики и агрегация

**Роль:** Менеджер статистики и метрик — прямой наследник `ChannelRoutingManager` (ADR-022). Агрегирует counter/gauge/timing/histogram, периодически сбрасывает снапшоты в каналы. Все менеджеры с `ObservableMixin` маршрутизируют метрики сюда через `_record_metric()` / `_record_timing()`.

**`StatsManager`** (`ChannelRoutingManager`, `IStatsManager`) — dual-layer: live-dict для `get_metric()` + `AggregationWindow` для flush. Sentinel `_STATS_SENTINEL` предотвращает N-кратный счёт при N каналах.

```
StatsManager (ChannelRoutingManager)
    ├── _metrics (Dict)        — live-state для get_metric() / get_all_metrics()
    ├── AggregationWindow      — IBufferStrategy с агрегацией (counter sum, gauge last, timing p95)
    ├── _do_flush()            — broadcast snapshot во ВСЕ каналы
    ├── LogStatsChannel        — IChannel → LoggerManager.performance()
    ├── FileStatsChannel       — IChannel → JSON/CSV файл
    ├── StatsAdapter           — BaseAdapter → CommandManager (5 команд)
    └── StatsManagerConfig     — ChannelRoutingConfig + aggregation/flush/tags
```

Ключевые решения (ADR-SM-001…006):
- Прямой наследник CRM, не LoggerManager (scope/level избыточны).
- Dual-layer storage: live-dict + AggregationWindow.
- Sentinel-паттерн: enqueue один раз, flush во все каналы.
- `_metric_key` дупликация — намеренная изоляция слоёв.

📖 [`modules/statistics_module/README.md`](modules/statistics_module/README.md) · [`modules/statistics_module/DECISIONS.md`](modules/statistics_module/DECISIONS.md)
```

#### 3.4. README.md — исправить 4 неточности

| Строка | Было | Стало |
|--------|------|-------|
| 28 | `normalize_config() — Dict at Boundary (принимает None / dict / RegisterBase)` | `normalize_config() — Dict at Boundary (принимает None / dict / SchemaBase)` |
| 204 | `StatsManager(config=StatsManagerConfig(...))    # RegisterBase с build()` | `StatsManager(config=StatsManagerConfig(...))    # SchemaBase с build()` |
| 257 | `├── config/` | `├── configs/` |
| 287 | `# из каталога refactored/modules/` | `# из каталога modules/` |

#### 3.5. STATUS.md — обновить

1. `## Текущий этап: 4 / 8` → `## Текущий этап: 5 / 8`
2. Оценка `Тесты`: `8` → `9`, комментарий: `~37 тестов; integration, adapter, thread-safety, tags`
3. Оценка `Документация`: `8` → `10`, комментарий: `DECISIONS.md (ADR-SM-001…006), §6.15 в ARCHITECTURE.md, README fix`
4. Чеклист — отметить:
   ```
   - [x] Этап 5: Формализация — DECISIONS.md (ADR-SM-001…006), ARCHITECTURE.md §6.15, тесты integration/adapter/thread-safety
   ```
5. Добавить в историю: `| 2026-04-10 | DECISIONS.md (ADR-SM-001…006), ARCHITECTURE.md §6.15, тесты integration/adapter/thread-safety, README fix | 4→5 |`

Коммит: `docs(statistics_module): add DECISIONS.md, fill ARCHITECTURE.md §6.15, fix README/STATUS`.

---

### Шаг 4 — Финальная валидация

1. `pytest statistics_module/tests -v` — все зелёные.
2. `pytest logger_module/tests -v` — зелёные (проверка кросс-зависимости LogStatsChannel).
3. `python scripts/run_framework_tests.py` — все зелёные.
4. Метрики «после»:
   - Файлов: 13 `.py` (без тестов) — без изменений.
   - LOC: 981 (без изменений в production-коде).
   - Тест-файлов: 5 (+test_stats_integration, +test_stats_adapter).
   - Тестов: ~37 (+13 новых).
5. Обновить `plans/refactoring/00_overview.md` строка #15:
   ```
   | 15 | `statistics_module`          |  13   |   981  |   3   |  TODO  | TODO | 13 | 981 | 5 (~37 passed) |
   ```
6. Коммит: `refactor(statistics_module): final validation and metrics`.

---

## 3. Что НЕ делать

1. **НЕ** менять `core/stats_manager.py` — record_metric, _do_flush, _enqueue_to_buffer, sentinel, _merged_tags работают.
2. **НЕ** менять `core/aggregation_window.py` — AggregationWindow стабилен.
3. **НЕ** менять `core/metric_record.py` — MetricRecord стабилен.
4. **НЕ** менять `interfaces.py` — IStatsManager полный.
5. **НЕ** менять `configs/stats_config.py` — стабилен.
6. **НЕ** менять `channels/` — оба канала работают.
7. **НЕ** менять `adapters/stats_adapter.py` — адаптер стабилен.
8. **НЕ** менять `__init__.py` — eager imports корректны.
9. **НЕ** выносить `_metric_key` в общий модуль (ADR-SM-004 — намеренная изоляция).
10. **НЕ** реализовывать `retention_seconds` (known limitation, будущая задача).
11. **НЕ** реализовывать router_manager integration (known limitation, будущая задача).
12. **НЕ** менять публичный API.
13. **НЕ** трогать другие модули кроме главного `DECISIONS.md` и `ARCHITECTURE.md`.
14. **НЕ** добавлять PrometheusChannel / OpenTelemetry (этапы 6+ — отдельная задача).

---

## 4. Кросс-модульные изменения (ВАЖНО для Composer)

**Никаких кросс-модульных изменений в коде.** Только два общих `.md` файла.

| Файл | Что меняется |
|------|-------------|
| `modules/statistics_module/tests/test_stats_integration.py` | **СОЗДАТЬ** (~150–180 LOC, 9 тестов) |
| `modules/statistics_module/tests/test_stats_adapter.py` | **СОЗДАТЬ** (~80–100 LOC, 4 теста) |
| `modules/statistics_module/DECISIONS.md` | **СОЗДАТЬ** (ADR-SM-001…006) |
| `modules/statistics_module/README.md` | Исправить 4 неточности (строки 28, 204, 257, 287) |
| `modules/statistics_module/STATUS.md` | Обновить этап, оценки, чеклист, историю |
| `multiprocess_framework/ARCHITECTURE.md` | Заменить заглушку §6.15 (строка 766, ~20 строк) |
| `multiprocess_framework/DECISIONS.md` | Добавить 1 строку в таблицу «Модульные решения» (после строки ~1852) |
| `plans/refactoring/00_overview.md` | Обновить строку #15 с метриками «после» |

**Порядок:** Шаг 0 → Шаг 1 → Шаг 2 → Шаг 3 → Шаг 4. Атомарные коммиты.

---

## 5. Definition of Done (модуль #15)

- [ ] Интеграционный тест: FileStatsChannel запись в файл (JSON + CSV)
- [ ] Интеграционный тест: FileStatsChannel создание parent dirs
- [ ] Интеграционный тест: LogStatsChannel вызывает performance()
- [ ] Интеграционный тест: LogStatsChannel без logger → error
- [ ] Тест get_metric с tags: первое совпадение, отсутствующая метрика
- [ ] Thread-safety: 10 потоков concurrent record_metric → count == 1000
- [ ] Thread-safety: mixed record + get_all_metrics без исключений
- [ ] StatsAdapter: setup регистрирует 5 команд
- [ ] StatsAdapter: без process / без command_manager → False
- [ ] StatsAdapter: is_initialized корректен
- [ ] Все тесты statistics_module зелёные
- [ ] `run_framework_tests.py` зелёный
- [ ] `DECISIONS.md` создан (ADR-SM-001…006)
- [ ] Главный `DECISIONS.md` обновлён
- [ ] ARCHITECTURE.md §6.15 заполнен
- [ ] README.md — исправлены неточности
- [ ] STATUS.md — обновлён
- [ ] Метрики «после» в `00_overview.md`

---

## 6. Целевые метрики

| Метрика | До | После (цель) |
|---------|-----|--------------|
| Файлов (без tests) | 13 | 13 (без изменений) |
| LOC (без tests) | 981 | 981 (без изменений) |
| Тест-файлов | 3 | 5 (+test_stats_integration, +test_stats_adapter) |
| Тестов (pytest) | 24 | ~37 (+13 новых) |
| DECISIONS.md | нет | ADR-SM-001…006 |
| ARCHITECTURE.md §6.15 | заглушка | заполнен |
| Публичный API | Без изменений | Без изменений |

---

## 7. Верификация

После выполнения всех шагов:

```bash
# Из текущего каталога

# 1. Тесты statistics_module
python -m pytest multiprocess_framework/modules/statistics_module/tests -v

# 2. Тесты logger_module (кросс-зависимость через LogStatsChannel)
python -m pytest multiprocess_framework/modules/logger_module/tests -v

# 3. Полная валидация фреймворка
python scripts/run_framework_tests.py

# 4. Метрики LOC
find multiprocess_framework/modules/statistics_module -name "*.py" -not -path "*/tests/*" -not -path "*__pycache__*" | xargs wc -l
```
