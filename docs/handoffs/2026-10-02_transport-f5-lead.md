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
| developer 5.5 | `a8a80c7f5d48416bc` | 113k — дозвать на 5.5B |

## Открыто
- Segfault `test_sampler_ceiling_policy` не воспроизведён — записать в `OPEN_QUESTIONS.md` при закрытии 5.5.
- Решено владельцем 2026-10-02: вход `PluginContext.scheduler` — сразу (ленивое свойство, `plugins/base.py` + `plugins/interfaces.py`), внесено в Дизайн 5.2. Ревьюеру спек на итерации 2 — проверить, что файлы не пересекаются с 5.3/5.4.
- Пока стенд не нужен; следующий замер — после волны 2.
