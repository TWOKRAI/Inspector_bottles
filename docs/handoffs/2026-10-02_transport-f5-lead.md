# Хендофф лида: transport-single-policy, фаза 5 — 2026-10-02 (сессия 19)

**План:** [`plans/transport-single-policy/phase-5.md`](../../plans/transport-single-policy/phase-5.md) — раздел «Объём фазы» (решение владельца).
**Ветки/worktree:**
- `feat/transport-f5` — `.claude/worktrees/t5-lead` (документы лида: план, отчёты, ревью). Не влита в main.
- `fix/t55-green-main` — `.claude/worktrees/t55-green` (Task 5.5). Не влита.
- `.claude/worktrees/stand` — detached на `003264912`, для замеров. Замок: `D:\PROJECT_INNOTECH\Inspector_vision\stand.lock` (снят).
**main:** `003264912`, в корне не трогали. Сосед — сессия 60 (layer-render, свои worktree, main не двигает, стенд — только по замку).
**Журнал «Компании v3»:** [`docs/claude/pilot-company-v3-transport-f5.md`](../claude/pilot-company-v3-transport-f5.md).

## Объём фазы (владелец, 2026-10-02)
В работе: 5.0 ✅ → 5.1 ✅ → **5.5** → **5.2 ∥ 5.3 ∥ 5.4** → **5.6 ∥ 5.9a** → **5.8 ∥ 5.11**. Цель 5.8 — 1080p@60 без потерь, при 100 — число и максимум.
Отложены с условиями возврата: 5.7, 5.9, 4.8b. 5.10 снята по факту 5.0(а).

## Сделано
| Шаг | Итог |
|---|---|
| 5.0 факты | `5dab8565d` — [`docs/audits/2026-10-02_transport-facts.md`](../audits/2026-10-02_transport-facts.md): дверь А; событие готовности не доходит до детей; транзит на старте; 2 рецепта не стартуют (поправка CTO: валидатор + нет `wires:`); `delivery_failed` = ветка `:574`; `g7_soak_probe` жива |
| 5.1 CTO | `7d07d77fc` — [`docs/reviews/2026-10-02_phase5-design-cto.md`](../reviews/2026-10-02_phase5-design-cto.md); Дизайн 5.2/5.3 переписан, новая 5.9a |
| объём | `470af822c`, `a110e25f4` |
| 5.4 дизайн | `cdee7e03b` (проводка события по образцу `system_stop_event`) |
| ревью спек 5.2/5.3/5.4 | итерация 1: все три CHANGES REQUESTED — [`docs/reviews/2026-10-02_phase5-spec-review-w2.md`](../reviews/2026-10-02_phase5-spec-review-w2.md). Редакция 2 внесена `e03db9eb2`; итерация 2 — у того же ревьюера (дозван) |
| 5.5 диагноз | `8cd6a60b2` (ветка t55): 10 красных с вердиктом; segfault не воспроизведён (5 прогонов) |
| 5.5A код | `c8a1853f4` (ветка t55): socket read-loop `_dead` → break, Path `as_posix()`, `get_std_logger` в field_meta/sdk_reader |
| инъекции 5.5A | I1–I4 живы по предсказанию (I3 переделана: заплата после `from __future__`) — [`docs/reviews/2026-10-02_task-5.5a-injections/`](../reviews/2026-10-02_task-5.5a-injections/) |

## Состояние на 2026-10-02 вечер (после компакта)
- 5.5: ветка `fix/t55-green-main` HEAD `39718c6f9` — код, тесты, правки ревью, ship, OPEN_QUESTIONS. Осталось: полный `run_framework_tests.py` + `logger_module/tests` ×3 (segfault) + прогон CTO из 5 файлов — **после** исполнителей волны 2 (CPU, тайминговые тесты); SHA соседу 60; слияние в main. Инъекция «/dev:ship отказывает» — за владельцем.
- Волна 2: спека `c4ffa28af` (ред. 3). Реализации готовы, инъекции лида сделаны:
  - 5.2 `b2ab22ff1` (team-t52): 12/12 по предсказанию; находка M6b — страж AST слеп к `sleep` в помощнике `_actuate` (держит только p99). Решения лида в работе: fire = диспетчер `payload(count)`, `tolerance_s` на запись, WARNING алиаса раз на экземпляр, `test_verdict_documents` переписан (спека «без изменений» ошибочна — поправить в плане при слиянии). Открыто: счётчики late/unfired — процессные, не по плагину; PLUGIN_API_VERSION не поднят → OPEN_QUESTIONS; ADR-PM-051.
  - 5.3 `2254a2b2c` + `ffb698fd9` (team-t53): 13/13; L10 (замок слияния в хвост) ловит только авторский тест с окном 0.3 с. Отклонения приняты: `test_t47d2b_author.py` и кейс `is marker` → равенство. Pickle 1078 id = 37 968 Б.
  - 5.4 `0bd3fce1f` (team-t54): 8/8; **K6/K7 зелёные — звено GenericProcess → SourceProducer не охранено ни одним тестом**; исправление обязательно (тест на настоящем GenericProcess, убивающий K6 и K7) — автору (developer, agentId ниже, 157k) вместе с находками ревью. Авторских hazard-тестов у 5.4 нет — дефект брифа лида. Флейк `test_mark_only_after_confirmed_death` — прогнать на базе `4aed4a3dd`.
- **5.5 ВЛИТА В MAIN (сессия 20):** main `68fb2e6df` (до этого в ветку 5.5 влит свежий main `3e79b264a` трека plans-progress, конфликт только `OPEN_QUESTIONS.md`). Решение владельца: влить + Task 5.5c «весь `make gate` зелёный» (в плане). Гейт: `test-fw` 10750 passed / 0 failed; ruff 7, pyright 1, bandit, корневой pytest 39 — одинаково на main до 5.5, отчёт `docs/reviews/2026-10-02_task-5.5-gate.md`. CTO merge gate для 5.5 не запускался — решение владельца в чате. SHA отправлены сессиям 60 и 0f. main влит в `feat/transport-f5` (`1e9a8efc3`): router + волна 2 — 846 passed, HOL зелёные. Дальше: стенды D100/P10/s0 под `stand.lock` (дерево `stand` — пересадить на свежий main/фазу), затем волна 3 (5.6 ∥ 5.9a), 5.5c — параллельно отдельным писателем.
- **ВОЛНА 2 ВЛИТА в `feat/transport-f5` (сессия 20):** 5.3 `0eb42340a`, 5.2 `236ec9e5b`, 5.4 `d06155efd` (+ `scripts.sync`). На слитом дереве: process+process_manager+router 5619 passed, 3 failed — только HOL (известные красные main, чинит 5.5), robot_control 126. Ревью: 5.3 APPROVED (р1), 5.4 APPROVED (р2), 5.2 закрыта р2 + флак 0/1500. План 5.2 сверен (`1936757ad`); добавлена Task 5.12 «гейт готовности к линии» (`32d8b6732`) — пороги ждут владельца. Дальше: полный прогон t55 (идёт) → CTO merge gate → владелец → main; стенды D100/P10/s0; `phase-5.md` 90 КБ — разделить по `##` после слияний.
- **Ревью волны 2 (сессия 20):** 5.2 CHANGES REQUESTED (страж транзитивно, сброс счётчиков, WARNING на первом `process()`, фикстура записи 5.3; цель после закрытого окна → CTO, OPEN_QUESTIONS); 5.3 APPROVED (тексты ⌈N/1500⌉ и режим красного L10, проба `acquire(blocking=False)`, `_CARRIED_SYSTEM_FIELDS` + поля записи); 5.4 CHANGES REQUESTED (тест K6/K7 на настоящем GenericProcess + 4 hazard-теста, снять `@pytest.mark.timeout`). Правки отправлены авторам по agentId — ждём SHA. **Условие слияния:** 5.3 не в main без 5.2 (в дереве 5.3 `robot_control` считает запись за 1 кадр); P10 — только на дереве с обеими. **На слиянии лиду:** `python -m scripts.sync` (дрифт `ADR-PMM-001…033 → 034`), поправить в плане «`test_verdict_documents` без изменений» и «WARNING один раз на процесс» → «на экземпляр».
- **Следующие шаги после компакта (исходные):** (1) три СВЕЖИХ синхронных ревьюера (5.2, 5.3, 5.4), в бриф — итоги инъекций из `docs/reviews/2026-10-02_task-5.{2,3,4}-injections/`; (2) правки ревью — авторам по agentId; (3) полный `run_framework_tests.py` + `logger_module/tests` ×3 на t55 (когда никто не грузит CPU) → SHA соседу 60 → слияние t55 в main; (4) слияние t52/t53/t54 в `feat/transport-f5` (конфликт: `multiprocess_framework/DECISIONS.md` у 5.3 + `scripts.sync` лидом; номера ADR-PM-051 / ADR-PMM-034); (5) стенды D100 (5.2), P10 (5.3), s0 (5.4) под `stand.lock`.
- Мусор вне репо: `C:/t54ref` (копия фреймворка тестера 5.4) — удаление `rm -rf` запрещено правилами, просить владельца.

## Следующие шаги (по порядку)
1. ~~Переделать I3~~ — сделано, жива.
2. (в работе, дозван 2026-10-02, два брифа в одном сообщении) Дозвать `dev-t55` (agentId ниже) на **5.5B** — тестовые правки, ≤ 6 файлов: снимки вместо пинов (`test_hot_rebuild_provenance_acceptance.py:309-322`, `test_catalog_kind_roundtrip.py:67`); `test_second_sender_to_stuck_socket` — 2 прогревочных `send` + `warnings.clear()`; `test_yaml_io.py::test_update_yaml_preserving_keeps_file_mode` — skipif win32; `test_remote_frame_source.py::test_r2_*` — skipif win32 (вердикт рассуждением); `test_reader_gone_hazards.py` H8/H9 — PYTHONPATH из `__file__`, не `os.getcwd()`; литерал `_EXPECTED_FRAMEWORK_METRICS` (`tests/test_declarations_leak_session_catalogue_guard.py:34`) — 5 → 10 имён (проверить объявления в `process_module/heartbeat/`). Два брифа по ≤ 6 файлов (лимит хука).
3. Инъекции 5.5B → ревьюер 5.5 (синхронно) → `make gate` в `/dev:ship` (`.claude/plugins/dev/commands/ship.md` + зеркало `.claude/commands/dev/ship.md`) → полный прогон → слияние t55 в main (SHA соседу 60 заранее).
4. ~~Внести правки ревью спек~~ — `e03db9eb2`; итерация 2 ревьюера — в работе. Исходно: внести правки ревью спек в 5.2/5.3/5.4 (решения лида уже приняты: широкая запись несёт `trace_ids`+`count`, 5.6 считает Σcount; `cmd_set_delay` пишет `transit_ms` с WARNING; чанк — жадная упаковка неделимых входов; `capture_ts None` → min/max по не-None; 5.4 — keyword-only `system_ready_event` через `kwargs`). Дозвать ревьюера спек по agentId на итерацию 2.
5. Три слепых тестера (по одному на 5.2/5.3/5.4) в worktree на коммите до реализации → три исполнителя (teamlead 5.2/5.3, developer 5.4), файлы не пересекаются.
6. Перед слиянием `feat/transport-f5` в main — SHA соседям.

## agentId (дозывать по нему)
| Роль | agentId | Контекст |
|---|---|---|
| debugger 5.5 диагноз | `a52f1f37cca20d851` | 198k — за порогом, свежего вместо него |
| cto 5.1 | `aebdaa3b36791e860` | 242k |
| reviewer спек волны 2 | `a6267fc79dbcdffc7` | 210k — дозвать на итерацию 2 спек |
| developer 5.5 | `a8a80c7f5d48416bc` | 167k после 5.5B — за порогом, свежего |
| reviewer 5.5 (код) | `aa3a684b6cf539a59` | 192k — дозвать на итерацию 2 5.5, если будет |
| tester RED 5.2 | `a23540be420c15aa1` | 236k — эталон в scratchpad |
| tester RED 5.3 | `aaf44f211e9262ca8` | 217k |
| tester RED 5.4 | `a1fc33e1c2ae840eb` | 187k |
| teamlead 5.2 (реализация, team-t52) | `a8e2b5cc9f20512f9` | в работе, фон |
| teamlead 5.3 (реализация, team-t53) | `aedeeac947002f768` | в работе, фон |
| developer 5.4 (реализация, team-t54) | `a7db2e08b1b860d78` | дозван на правки ревью 1 |
| reviewer 5.2 (код) | `a4ecb97af27002458` | 206k — дозвать на раунд 2 |
| reviewer 5.3 (код) | `a6f6cd104159fc4a1` | 224k — APPROVED, раунд 2 не нужен |
| reviewer 5.4 (код) | `a95dd3d836dfd45bf` | 228k — дозвать на раунд 2 |

## Открыто
- Segfault `test_sampler_ceiling_policy` не воспроизведён — записать в `OPEN_QUESTIONS.md` при закрытии 5.5.
- Решено владельцем 2026-10-02: вход `PluginContext.scheduler` — сразу (ленивое свойство, `plugins/base.py` + `plugins/interfaces.py`), внесено в Дизайн 5.2. Ревьюеру спек на итерации 2 — проверить, что файлы не пересекаются с 5.3/5.4.
- Пока стенд не нужен; следующий замер — после волны 2.
