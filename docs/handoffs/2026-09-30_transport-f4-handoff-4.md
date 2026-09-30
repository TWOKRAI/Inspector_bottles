# Хендофф: T1 слита, main сведён, робот T1.2/T1.3, выбор 4.7 — 2026-09-30 (вечер, 4)

**Ветка основного дерева:** `feat/qr-code-reader` на `470d744f` (содержит main `9f751faf` + T1). **Предыдущий:**
[`2026-09-30_transport-f4-handoff-3.md`](2026-09-30_transport-f4-handoff-3.md).
**Планы:** [`pipeline-node-timing`](../../plans/pipeline-node-timing.md), [`transport-single-policy` Ф4](../../plans/transport-single-policy/phase-4-redesign.md)
(`task-4.7.md`, `task-4.8.md`), [`robot-protocol-v2`](../../plans/robot-protocol-v2/tasks.md) (T1.2, T1.3), очередь — [`queue/ORDER.md`](../../plans/queue/ORDER.md).

## Первым шагом в новом чате — спросить владельца

Владелец выбирает между двумя вариантами (вопрос задан в конце прошлого чата, ответа нет):
- **(a)** доделать робота T1.3 (небольшая), затем перемер стенда после T1 и 4.7;
- **(b)** отложить робота, сразу перемер стенда после T1 и 4.7.

Рекомендация лида: **перемер стенда первым** в любом варианте — все числа Ф4 сняты до T1 (цепочка без детекций).
Стенд свободен (сосед `inspector-bottles-79` снял `stand.lock`; стенд-worktree `.claude/worktrees/stand` detached
на чужом SHA `78c8a7bd` — переключить на нужный SHA перед замером, соседу написать перед `measure`).

## Состояние

| Что | Состояние |
|---|---|
| **pipeline-node-timing T1** | ✅ слита `b611e7a7`, закрыта `fb2eb07d`. 6/6 в `inspection_full/basic`, цепочка 1080p 4.1–4.7 мс (было 9.5 мс, 0 детекций). Песочница «Плагины»: первый `image/*`-выход, правило по dtype обязательных входов, io/output/sink/calibration закрыты (36 → 25). Ревью reviewer ×2 + teamlead APPROVE; инъекции I1–I6, J1–J5 |
| **main → feat/qr-code-reader** | ✅ fast-forward на `470d744f` (слияние подготовил сосед). Радиус 5479 passed, 1 failed = PC-7 (не слияние) |
| **PC-7** | открыт: тест T1 зависит от порядка (после `process_module` реестр пуст для `robot_io`). Починка — фикстура `all_real_plugins` |
| PC-5, PC-6 | открыты, мелкие (метаданные категорий плагинов; песочница по входам, не по выходу) |
| **robot-v2 T1.2** | коммит `bc8cacc1` в ветке `feat/robot-v2-t12-t13` (worktree `.claude/worktrees/rv2-t12`, от main `f4a4bf94`). 38 тестов инвариантов + `param_ids.snapshot` (58). Инъекции лида K1–K9 по прогнозу. Ревью Opus: **APPROVE**, minor m1–m4 + n1 не внесены (ниже). **Не слита** |
| **robot-v2 T1.3** | не начата. Worktree tester'а `.claude/worktrees/rv2-t13-tester` (ветка `tests/robot-v2-t13-blind` на `bc8cacc1`) создан и пуст. Запуск tester'а отклонил хук `lint-brief`: «DESIGN block missing» — заголовок должен начинаться ровно `DESIGN (decided by the lead` |
| 4.8a, 4.7, T2 | ждут; порядок Ф4 владельца: 4.8a → 4.7 → 4.8b |

## Робот T1.2 — замечания ревью (внести отдельным коммитом до слияния)

- **m1** `test_protocol_v2_yaml.py:255` `len(ids) == 58` → `>= 58` + docstring «новый параметр → строка `id name` в снимок».
- **m2** `:73-74` размах mailbox считается с `cmd_flag` (`CMD_BASE`), а FC16 пишет с `CMD_BASE + 1` — поправить или записать запас.
- **m3** `:83-88` `WRITE_CHUNK % SC_STRIDE == 0` в спеке не обоснован — docstring «удобство ПК, не правило протокола» или удалить.
- **m4** `:94` TLM по префиксу `tlm_` — по адресу `[TLM_BASE, 0x1080)` (та же слабость у существующего `test_structural_invariant_tlm_fits_block`).
- **n1** `:279` `_vfd_via_existing_test` → `_dw_even_via_existing_test`.
- **В GATE-0 (вопрос владельцу):** старшие половины широких параметров из блока 112..127 (plan.md:295) — годятся только id ≤ 124, иначе PMIR читается > `READ_MAX` 125. Беззнаковые параметры с max ≥ 32768 (`P_ACC_L`, `P_BELT_FACTOR`, `P_WDG_TIMEOUT_MS`, `P_CONFIG_EPOCH`) — дыра −32768 в слове W, уже xfail.

## Робот T1.3 — контракт лида (готов, перенести в бриф tester'а дословно)

Модуль `Services/robot_comm/build_fw.py`, CLI `python -m Services.robot_comm.build_fw [--check] [--root PATH]`.
- Источники `<root>/robot/v2/src/NN_*.lua` по возрастанию имени, перед каждым строка `-- ===== <имя файла> =====`;
  артефакт `<root>/robot/v2/main_v2.lua`, LF.
- `10_generated.lua` содержит строку `-- @@GENERATED@@` → заменяется на `codegen.lua_block(root)`.
- `00_header.lua` содержит `@@FW_BUILD@@` → `0x%04X` от FW_BUILD = `crc16_modbus(склейка сырых байтов NN_*.lua по
  порядку, концы строк → LF, ДО подстановок) & 0x7FFF` (как `DICT_FINGERPRINT`: регистр пишется знаковым словом W;
  нормализация LF — из-за `core.autocrlf=true`). Без времени и путей.
- API: `build(root) -> str` (на диск не пишет), `fw_build(root) -> int`, `check(root) -> list[str]`,
  `class BuildError`, `main(argv) -> int`.
- `BuildError`: нет `NN_*.lua`; нет `00_header.lua`/`10_generated.lua`; нет плейсхолдера или токена;
  в `80_mirror.lua` (если есть) `while` словом, `WAIT(` или `DELAY(` в коде (комментарии `--` не считаются).
- `main` без `--check` пишет артефакт → 0 (ошибка → stderr, 1); `--check` → 0 только если артефакт == `build(root)`
  байт в байт и нарушений нет.
- luacheck: нет в PATH (`shutil.which`) → предупреждение в stderr, не падение (на этой машине его нет); есть и
  упал → провал. В тестах — monkeypatch `shutil.which`/`subprocess.run`.
- В репо: заглушки `robot/v2/src/00_header.lua`, `10_generated.lua` и закоммиченный `robot/v2/main_v2.lua`;
  свежесть = `main(["--check"]) == 0` на корне репо.
- REDS tester'а (≤ 10): порядок и разделители; подстановка GENERATED; литерал FW_BUILD (+ одно число руками);
  детерминизм и CRLF; `DELAY(` в коде → ошибка, в комментарии → нет, `while` → ошибка; нет `10_generated.lua` /
  плейсхолдера → ошибка; `--check` 0 → правка → 1; luacheck нет → предупреждение, есть и упал → 1; свежесть на репо.
- Затем developer (Sonnet) в `rv2-t12`, инъекции лида, ревью Opus. Слияние ветки `feat/robot-v2-t12-t13` — в main
  (робот v2 живёт в main), договориться с соседом.

## Передача кадров между процессами — ответ владельцу (для 4.7)

Лучше: чужих кадров у плагинов 1797/1798 → 0 (4.4); ядра 8.4 → 4.56 при `cv_threads` 2 (4.6); наблюдаемость CPU /
`plugin_ms` / `queue_wait_ms` / `transport_ms` (4.5); цепочка 9.5 → 4.1–4.7 мс (T1).
Плохо (стенд 1080p 100 fps, **до T1**): цепочка 54–58 Гц; `queue_wait_ms` processor 1110 мс (data-очередь 50 длиннее
кольца); stale 821 + torn 1247 за 30 с — молча непроверенные бутылки; zero-copy выключен; L-6 (маски через pipe) —
в 4.4 маска ушла в `pack_images`, закрыт ли L-6 целиком — не проверено. 4.7 чинит: один режим, zero-copy, кольцо 8 и
очередь ≤ кольцо − 2, `overflow: latest | every` с маркером `not_inspected`; предусловия P-1, P-2 (`task-4.7.md`).

## Модели (указание владельца в этой сессии)

Код пишет **Sonnet** (`developer`, `tester` — `model: "sonnet"` явно), ревью — **Opus** (`reviewer`, 3-я итерация —
`teamlead` на Opus как ревьюер). Бриф по `.claude/plugins/dev/templates/executor-brief.md`: FILES ≤ 6, блоки
`DESIGN (decided by the lead`, `FILES`, `REDS`, `REPORT`; исправление по ревью — один developer с REDS (Д47).

## Соседи и ловушки

- Сосед `inspector-bottles-79`: line-sim R-5 (закрыт), R-6 (снял 102 `pytest.mark.timeout`, main `08b22515`), R-7
  (`camera_service test_stream_bad_url_reports_error_not_raises` красный на main — не наш). При сведении
  `feat/qr-code-reader` в main: документные конфликты `defects.md` (R-5/R-6 против PC-*) и `docs/sessions` (union).
- Ветку `merge/main-into-qr` и worktree `merge-qr` удаляет сосед.
- Worktree `.claude/worktrees/pnt-t1-impl` (ветка `feat/pipeline-node-timing`, слита) можно удалить.
- Хук commit-msg: тип `merge` запрещён; слияние — `fix(...)`/`feat(...)` + `Refs: plans/qr-code-reader.md`.
- Флак под нагрузкой: `test_pacing_hazards::test_idle_cycle_duration_measured_with_fine_clock` (10 ± 2 мс).
- Урок в памяти: фейк без атрибута, который читает правило, даёт пустой тест —
  `.claude/memory/feedback_fake_missing_attribute_vacuous_test.md`.

## Скрипты (scratchpad `78eb75da…/scratchpad`, временные)

`inject_t1fix.py` (I1–I6), `inject_sandbox.py` (J1–J5), `inject_t12.py` (K1–K9), `bench_t1.py` (замер цепочки,
от ревьюера).
