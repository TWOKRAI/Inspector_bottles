# Roadmap — От 8.1 к 10.0

**Контекст:** см. [`ASSESSMENT.md`](./ASSESSMENT.md). Текущая оценка фреймворка — **8.1 / 10**. Этот документ — план «дельт», которые довешивают каждый раздел до максимума.

**Сгруппировано по приоритетам (Tier 1–3) и сведено в спринты.**

---

## Tier 1 — обязательно, без этого выше 8.5 не вырасти

| # | Где теряется балл | Что добавить | Усилие |
|---|-------------------|--------------|--------|
| 1 | **CI отсутствует** | GitHub Actions matrix: `os: [ubuntu, windows, macos] × python: [3.11, 3.12]`. Прогон тестов + `tools/validate_all_modules.py` + lint | 1 день |
| 2 | **Performance baseline отсутствует** | `tests/performance/` с `pytest-benchmark`: throughput RouterManager, latency end-to-end IPC, BatchBuffer overhead, ConfigStore sync. Цифры в CI как regression-guard | 2 дня |
| 3 | **2 failing-теста** в зелёной зоне | Починить `test_init_creates_components` (нужен `config_handler` defensive guard) и `test_console_process_config_build_and_process_helper` (обновить ожидаемый contract `proc_dict`) | 30 мин каждый |
| 4 | **Editable installation хрупкая** | В `pyproject.toml` корня Inspector_prototype добавить `[tool.setuptools]` или `[tool.uv.sources]` с явным указанием пакета `multiprocess_framework`. Сейчас работает только из `Inspector_prototype/` cwd | 1 час |
| 5 | **`pytest-asyncio` не подключён** | Async SQL-тесты выдают `Unknown pytest.mark.asyncio` warnings — нужно добавить в зависимости и настроить `pytest.ini` | 15 мин |

---

## Tier 2 — выводит на 9.0+

| # | Где теряется балл | Что добавить | Усилие |
|---|-------------------|--------------|--------|
| 6 | **3 разных `ProcessStatus` enum'а** в `process_module`, `shared_resources_module`, `process_manager_module` | Унифицировать — вынести в `base_manager` или `data_schema_module`, остальные → импорт | 2 часа |
| 7 | **`data_schema_module` 16K LOC** — растёт без декомпозиции | Выделить `extensions/`, `builders/`, `serialization/`, `registers_layer/` в подмодули с собственными `__init__.py` | 1 неделя |
| 8 | **`frontend_module` 12K LOC внутри фреймворка** | Вынести в отдельный пакет `frontend_framework/` (это уже в плане ADR-планов, milestone M3) | 2 недели |
| 9 | **Двойной API коммуникации** `send_message` (`bool`) и `send` (`dict`) | Депрекейт одного из двух с `warnings.warn` + срок удаления. Одно API — одна точка боли | 4 часа |
| 10 | **`DECISIONS.md` 1 874 строки** — плотный | Разбить тематически: `DECISIONS_FOUNDATION.md`, `DECISIONS_PROCESS.md`, `DECISIONS_OBSERVABILITY.md` + автогенерируемый `INDEX.md` | 4 часа |
| 11 | **Нет `CHANGELOG.md`** | Создать с привязкой к `__version__`, формат Keep-a-Changelog. Каждый релиз = пункт + ссылки на ADR | 2 часа на старт |
| 12 | **Нет автогенерации API-докментации** | `mkdocs` + `mkdocstrings` (или Sphinx). Чтение `docstrings` → красивый HTML/PDF | 1 день |
| 13 | **Нет интеграционных тестов «всё вместе»** | `tests/integration/`: запуск SystemLauncher с 3 процессами + IPC + graceful shutdown. Сейчас интеграция декларирована, но `TEST_ISSUES.md` упоминает баги | 2 дня |
| 14 | **`MemoryManager` skip 15 тестов на macOS** | Разобраться с `SharedMemory` на Apple Silicon, либо честно задокументировать, либо найти fallback (mmap) | 1 день расследования |

---

## Tier 3 — добивает до 10/10

| # | Где теряется балл | Что добавить | Усилие |
|---|-------------------|--------------|--------|
| 15 | **Нет линтера инвариантов** | `pre-commit` hook + custom-checker для R-1 (импорты), R-3 (pickle-safe), R-9 (sys.exit), R-15 (Pydantic v2). Сейчас правила ловятся только code-review | 1 день |
| 16 | **Нет deployment guide** | `docs/DEPLOYMENT.md` — Dockerfile, docker-compose с volume для логов, systemd unit, Windows service, рекомендации по ulimits | 1 день |
| 17 | **Нет cookiecutter-шаблона для нового приложения** | `templates/new_app/` — готовый scaffold (`my_app/process_a.py`, `my_app/registers.py`, `my_app/main.py`). Снижает порог входа разработчика | 1 день |
| 18 | **Узкое позиционирование** | `docs/USE_CASES.md` — 3-5 кейсов: видео-инспекция, IoT-агрегатор, лабораторный pipeline, real-time мониторинг. Когда брать фреймворк, когда — нет | 0.5 дня |
| 19 | **Нет нативной интеграции с observability-стеком** | `StatsManager` → `PrometheusChannel` (`/metrics` endpoint). `RouterManager` → OpenTelemetry tracing (correlation_id уже есть — почти готово) | 2 дня |
| 20 | **Нет release-процесса** | Semver, релизные ветки `release/2.x`, теги `v2.0.0`, GitHub Releases с changelog-фрагментом | 0.5 дня настройки |
| 21 | **Нет публичного репозитория / community** | Если планируется опен-сорс — лицензия в каждом файле (сейчас только `MIT` в README), `CONTRIBUTING.md`, `CODE_OF_CONDUCT.md`, issue-templates | 1 день |
| 22 | **Кривая обучения крутая** | `docs/TUTORIAL.md` пошагово: 0 → hello world, hello → ping-pong, ping-pong → camera+detector. Текущий `QUICK_START.md` (101 строка) — это reference, не tutorial | 2 дня |

---

## По разделам — что вычитает балл и что довешивает до 10

| Раздел | Сейчас | До 10 нужно |
|--------|-------:|-------------|
| Концепция | 9 | `USE_CASES.md` (#18) + явное позиционирование (узкое окно — это плюс, если правильно подать) |
| Архитектура | 9 | Депрекейт одного из `send_message`/`send` (#9) + вынос `frontend_module` (#8) |
| Реализация | 7.5 | Унифицировать `ProcessStatus` (#6) + декомпозиция `data_schema` (#7) + 2 failing-теста (#3) |
| Тесты | 8 | Integration E2E (#13) + performance baseline (#2) + `pytest-asyncio` (#5) + macOS SharedMemory (#14) |
| Документация | 8.5 | Разбить DECISIONS (#10) + автогенерация API (#12) + CHANGELOG (#11) + TUTORIAL (#22) |
| Производительность | 7 | Performance baseline (#2) + опубликованные числа |
| Кросс-платформенность | 7 | CI matrix 3 OS (#1) + macOS SharedMemory (#14) |
| Обслуживаемость | 8 | Pre-commit linter (#15) + cookiecutter (#17) + декомпозиция модулей (#7, #8) |
| Готовность к проду | 8 | CI (#1) + deployment guide (#16) + release-процесс (#20) + observability (#19) |
| Соответствие декларации | 9 | Editable installation fix (#4) |

---

## Дорожная карта спринтов

| Спринт | Что входит | Срок | Балл |
|--------|-----------|------|------|
| **Sprint 1** | #1, #3, #4, #5, #6 | 1 неделя | 8.1 → **8.7** (CI, тесты в зелёной зоне, корректная установка, унификация enum'ов) |
| **Sprint 2** | #2, #11, #13, #14 | 2 недели | 8.7 → **9.2** (performance baseline + integration + macOS) |
| **Sprint 3** | #9, #10, #12, #15, #16 | 2 недели | 9.2 → **9.6** (документация + линтеры + deployment) |
| **Sprint 4** | #7, #8 (большая декомпозиция) | 4 недели | 9.6 → **9.9** |
| **Sprint 5** | #17, #18, #19, #20, #21, #22 | 2 недели | 9.9 → **10.0** (release-readiness + community + observability) |

**Итого:** ~12 недель work full-time. Реалистично — 4–6 месяцев с учётом основной разработки.

**Минимальный путь до 9.0** — 3 недели (Tier 1 целиком + #6 + #11). Это уже зачёт уровня «зрелого open-source с автоматизацией».

---

## Принципы работы по карте

1. **Один пункт = один PR.** Не смешивать рефакторинг с фичами.
2. **Каждый пункт сопровождается ADR**, если меняется публичный контракт (правило R-12 из [`docs/DESIGN_RULES.md`](docs/DESIGN_RULES.md)).
3. **CI всегда зелёный.** Если пункт ломает тесты — это блокер до починки, а не «допилим потом».
4. **Документация — синхронно с кодом.** Изменился контракт — обновлены [`SPEC.md`](SPEC.md), [`docs/MODULE_CONTRACTS.md`](docs/MODULE_CONTRACTS.md), [`MODULES_STATUS.md`](MODULES_STATUS.md).
5. **Не торопиться с new features**, пока не пройден минимум Tier 1 + #6 + #11. Иначе технический долг продолжит расти.

---

## Связанные документы

- [`ASSESSMENT.md`](ASSESSMENT.md) — обоснование текущей оценки 8.1
- [`SPEC.md`](SPEC.md) — целевая архитектура
- [`docs/DESIGN_RULES.md`](docs/DESIGN_RULES.md) — инварианты, которые нельзя нарушать в ходе работы по карте
- [`PROBLEMS.md`](PROBLEMS.md) — известные ограничения, многие из которых закрываются Tier 1–2
- [`DECISIONS.md`](DECISIONS.md) — место для новых ADR по мере выполнения пунктов
