# Документы, сетка, переприёмка

> Фаза Ф5 плана [`observability-closure`](./plan.md). Правила приёмки — `plan.md` §3 (наследуют `observation-port/plan.md` §3), развилки владельца — `plan.md` §4, что удаляется и миграции — `plan.md` §9–§10. Номера находок (C*, M*, m*) — по [ревью 2026-08-28](../../docs/reviews/2026-08-28_observability-full-review.md).

## Ф5 — Документы, сетка, переприёмка

### Task 5.1 — Четыре справочника под HEAD + стражи утверждений (M15, m5, m16)
**Level:** Middle+ (Sonnet) · **Assignee:** tech-writer + developer (стражи) · **Layer:** docs, scripts
**Files:** `multiprocess_framework/docs/observability/{CONNECTORS,CONTROL_PANEL,SINKS_MAP,NEW_MODULE_RECIPE}.md`, `logger_module/README.md:250-610`, `scripts/docs_verify/*`, `multiprocess_framework/docs/OBSERVABILITY_MAP.md`.
**Steps:** полная ревизия под HEAD плана (порт, политика чисел, хуки, `NumberRecord`, инструменты MCP, `ServiceContext`); контракт `_call_manager` (три тихих допуска) — дословно из докстринга; номера строк снимаются из прозы (якоря — имена символов); банер = коммит; в `docs_verify` — проверки: допуски `_call_manager`, паритет инструментов ↔ CONTROL_PANEL, число команд из `BUILTIN_COMMAND_CONTRACTS`, наличие слова «порт» в CONNECTORS §разъёмы; слепой прогон рецепта агентом (S2-линза, повторяемо).
**Acceptance criteria:**
- [ ] `docs_check` ≥ 20 проверок, 0 расхождений; инъекция: вернуть старую фразу про `manager_call_failures` → красный.
- [ ] Слепой агент по `NEW_MODULE_RECIPE.md` заводит модуль с логом, метрикой (с единицей) и отказом → всё видно в `introspect_observability` без чтения исходников; транскрипт приложен.
- [ ] **Добор ревью Ф1 — индекс ADR:** ADR-PM-045 невидим для `scripts/sync` при зелёном
      `--check` — чинится сбор + проверка «каждый `ADR-\w+-\d+` из модульных DECISIONS.md
      представлен в сводном индексе» (инъекция: спрятать один — красный). Противоречие
      **ADR-PM-030 ↔ ADR-PM-045** («инцидент под тем же дросселем» против снятого дросселя)
      согласовано текстом с датой.

### Task 5.2 — `link_check` в гейте и мёртвые ссылки (M16, m15)
**Level:** Middle (Sonnet) · **Assignee:** developer · **Layer:** scripts, docs
**Files:** `scripts/link_check/link_check.py` (`_slugify` = `scripts/sync/adr_toc.py._slugify`, один модуль), `scripts/validate.py`, `multiprocess_framework/DECISIONS.md` (34 ссылки), `scripts/observability_seal/README.md` (слепая зона многоинкарнационных каталогов).
**Acceptance criteria:**
- [ ] `link_check` по четырём справочникам и `DECISIONS.md` → 0 `missing_file`, 0 ложных `missing_anchor` (пара: сломать один якорь → 1); `validate.py` вызывает его.

### Task 5.3 — Сетка: независимость от порядка как гейт, дедлайны, docstring (m16, CTL-F10)
**Level:** Middle (Sonnet) · **Assignee:** developer · **Layer:** tests
**Files:** `scripts/run_framework_tests.py` (режим `--reverse-modules`/случайный порядок в CI раз в день), `backend_ctl/tests/test_await_condition.py` (9 `join/wait` → daemon + дедлайн), `channel_routing_module/tests/*` (docstring на 164 тестах — минимум: свойство одной строкой).
**Acceptance criteria:**
- [ ] Гейт в обратном порядке модулей зелен (число); тест, который виснет, падает за дедлайн, а не висит (инъекция `Event` без `set`).
- [ ] **Добор ревью Ф1 — страж «один разъём на точку»:** (а) нижняя граница охвата числом —
      страж сегодня зелен по пустоте (обход, собравший 0 сайтов, неотличим от чистого дерева);
      (б) опознание голоса не только по имени `_log_error` — пара «голос `log_warning`/
      `log_critical` + факт» в одной ветке невидима, в дереве 4 живых случая (включая
      `GuiProcess`) — решить: расширить правило или объявить границу; (в) корни обхода — не
      литералы имён этого приложения. Пара инъекций на (а): пустой обход → красный.
- [ ] **Добор ревью Ф1 — граница тестов:** фреймворковые тесты импортируют слой `Plugins`,
      sentrux-правила смотрят только на прод-код — завести boundary-правило на `tests/` либо
      квалифицировать исключение письменно.

### Task 5.4 — Переприёмка гейта Ф6 этапа 6 (C4) и закрытие трека
**Level:** — · **Assignee:** независимый приёмщик (reviewer), владелец
**Steps:** все 16 пунктов `telemetry-stage6.md` §Ф6 на HEAD плана, два стенда (`webcam_sketch`, `inspection_full`), порог 8, конъюнкция по блокам; roadmap: этапы 6/8/10 — статус по факту; список отложенного с решением владельца: экспорт (7), fingerprint (9.1), fd-stderr (9.2), масштаб > 20 процессов, GUI.
**Acceptance criteria:**
- [ ] Отчёт приёмки в `docs/reviews/`, общая ≥ 8; шапки `observability-roadmap.md`, `QUEUE.md`, `OBSERVABILITY_MAP.md` — по факту; записи памяти обновлены в обоих местах.
