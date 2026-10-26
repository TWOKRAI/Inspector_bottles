# План: протокол робота v2 — закрытые задачи (DONE)

> Вынесено из [plan.md](plan.md) по размеру (лимит 32 КБ). Строки задач со статусом DONE перенесены дословно; в `plan.md` на каждую осталась одна строка со ссылкой сюда. Что не закрыто (PENDING, IN PROGRESS, BLOCKED, DEFERRED) — в `plan.md`.

## Ф0 — контракт

<a id="t01"></a>
- Task T0.1: YAML-контракт `delta_v2.yaml` [DONE 2026-09-27 — `527f471e`]
<a id="t02"></a>
- Task T0.2: ADR RC-009..014 и ссылки в индексе [DONE 2026-09-27 — `e00e623b`; статус ADR «Предложено» до GATE-0]

## Ф1 — кодоген и сборщик

<a id="t11"></a>
- Task T1.1: Кодоген: Python, `RobotParamsV2`, Lua-блок [DONE 2026-09-27 — `22900de7`] (после T0.1)
<a id="t12"></a>
- Task T1.2: Схемные инварианты YAML [DONE 2026-09-30 — `bc8cacc1`; слияние `4fd912ccd`] (после T1.1)
<a id="t13"></a>
- Task T1.3: Сборщик прошивки `build_fw.py` [DONE 2026-09-30 — `c8494eef`; слияние `4fd912ccd`] (после T1.1)

## Ф2 — симулятор v2

<a id="t20"></a>
- Task T2.0: Геометрия SCARA `programs/geometry.py` [DONE 2026-09-27 — слияние `0dcffc5e`] (после T1.1)
<a id="t21"></a>
- Task T2.1: sim v2: mailbox, параметры, плоскость безопасности [DONE 2026-09-27 — слияние `0dcffc5e`] (после T2.0)
<a id="t22"></a>
- Task T2.2: sim v2: движение, зона SCARA, стоп, jog [DONE 2026-09-27 — слияние `0dcffc5e`] (после T2.1)
<a id="t2-k"></a>
- Task T2-k: Модель робота: `RobotModel` + `ScaraModel` [DONE 2026-09-27 — слияние `0dcffc5e`] (после T2.2)
<a id="t2-v"></a>
- Task T2-v: Окно-вид sim v2: вид сверху, демо-режим [DONE 2026-09-27 — слияние `0dcffc5e`] (после T2-k)
<a id="t2-j"></a>
- Task T2-j: JOINT/HOME интерполируются по суставам модели [DONE 2026-09-27 — слияние `0dcffc5e`] (после T2-k)
<a id="t2-j2"></a>
- Task T2-j2: Суставы — состояние sim: пределы, время по суставам [DONE 2026-09-27 — слияние `0dcffc5e`] (после T2-j)
<a id="t2-w"></a>
- Task T2-w: Окно-вид: поворот инструмента RZ, шкала Z [DONE 2026-09-27 — слияние `0dcffc5e`] (после T2-v)
<a id="t23"></a>
- Task T2.3: sim v2: сценарий, `CVT_JOB`, сторожевой таймер, мост ПЧ [DONE 2026-10-12 — слияние `1b69f4f71`, итог `tasks/T2.3.result.md`] (после T2-j2) — О-10 решено 2026-10-11: вариант Б, одним шагом с T2.4 на механизмах фреймворка (`tasks.md`, T2.3)
<a id="t24"></a>
- Task T2.4: `Plugins/sim/robot_host` и журнал понимают v2 [DONE 2026-10-12 — слияние `1b69f4f71`] (после T2.3) — одним шагом с T2.3 (О-10, вариант Б); рецепт на v2 не закрыт: нужен `client_v2` (T3.1) и драйвер v2 в `device_hub`
<a id="t25"></a>
- Task T2.5: sim v2 — ход нулевой длины без `ZeroDivisionError` [DONE 2026-10-12 — слияние `ddbfdc01a`, ревью APPROVED; `docs/reviews/2026-10-12_task-sim-zero-path-debugger.md`] (после T2.2) — дефект R-13: «Домой» в HOME, `sim_core_v2.py` `pose_at`

## Ф3 — клиент и программы

<a id="t31"></a>
- Task T3.1: `client_v2`: ядро [DONE 2026-10-12 — слияние `117f58f9b`, итог `tasks/T3.1.result.md`] (после T2.4)
<a id="t32"></a>
- Task T3.2: `client_v2`: обёртки, пинг-понг, golden-лог [DONE 2026-10-12 — слияние `ca48fc244`, итог `tasks/T3.2.result.md`] (после T3.1)
<a id="t33"></a>
- Task T3.3: Программы: точки, СК, шаги, compile [DONE 2026-10-12 — слияние `13fc80cdc`, итог `tasks/T3.3.result.md`] (после T1.1)
<a id="t34"></a>
- Task T3.4: Генераторы: рисование, возврат, смена инструмента [DONE 2026-10-13 — слияние `352f081e0`, итог `tasks/T3.4.result.md`] (после T3.3)
<a id="t35"></a>
- Task T3.5: e2e клиент ↔ sim [DONE 2026-10-13 — слияние `e5cf50c04`, итог `tasks/T3.5.result.md`] (после T3.2, T3.4)
<a id="t35b"></a>
- Task T3.5b: хвост T3.1 — `v2_driver.py` стенда `robot_host` удалить, тесты T2.4 на клиент v2 [DONE] (после T3.5) — слияние `0c38542fc` 2026-10-13, ревью кода APPROVED (2 круга), инъекции 10/11; итог `tasks/T3.5b.result.md` — решение владельца 2026-10-13 (В2 брифа T3.5); `tasks.md` → «### T3.5b»
<a id="t36"></a>
- Task T3.6: Ленивые `__init__` пакета `robot_comm` и `core/` [DONE 2026-10-12 — слияние `ca48fc244`, итог `tasks/T3.6.result.md`] (после слияния T3.1)
<a id="t37"></a>
- Task T3.7: `robot_host` линии на протоколе v2 [DONE 2026-10-14 — инъекции `tasks/T3.7.injections.md` (23/23 по прогнозу), reviewer APPROVED во 2-м круге, стенд: `jobs_done` 3, `hub_errors` 0, итог `tasks/T3.7.result.md`; узкий срез T5.3 — `enqueue_job`/`return_job` у `RobotDriverV2`; `fault.*` хоста на v2 — долг] (после T3.5; при закрытии — удалить временный страж T3.5b `Plugins/sim/robot_host/tests/test_t35b_guard.py`) — 2026-10-12: `apps/line_sim/pipeline.yaml:51` — `protocol: v1`; пожелание владельца «всё на одном экране», `plans/queue/_proposals/2026-10-12_plans-sync.md`
<a id="t38"></a>
- Task T3.8: вид робота рисует робота линии из её состояния, а не своё ядро [DONE 2026-10-18, слияние `7fc7c3b2f` — итог `tasks/T3.8.result.md`, отчёт `docs/reports/2026-10-18_robot-protocol-v2_T3.8.md`; ревью Opus APPROVED (р.2); стенд пройден, порог «разных x» — 10 из 10 по эталону; цена перечитываний у `camera` ≈2.4× — решение владельца; ветка `feat/robot-v2-t38`] (после T3.7) — 2026-10-12: `Services/robot_comm/gui/sim_view.py:481-500` создаёт `RobotSimCoreV2` сам; потребитель — `line-sim` Task 6.4 (вид сверху на `pult_web`)
<a id="t39"></a>
- Task T3.9: Состояние сценария на границе куска — `SC_RUN` несёт стартовые `spd_pct`/`accel`/`accur` [DONE 2026-10-13 — слияние `efaa394ea`, итог `tasks/T3.9.result.md`] (после T3.5, до T5.1) — решение владельца «как в v1, дёшево»

## Ф5 — приложение без GUI

<a id="t51"></a>
- Task T5.1: `RobotDriverV2` [DONE 2026-10-14 — инъекции `tasks/T5.1.injections.md` (24/27 по прогнозу, выжившая U2-inj → Ф1 закрыта), reviewer APPROVED во 2-м круге, итог `tasks/T5.1.result.md`] (после T3.5, T3.9) — бриф `tasks/T5.1.md` (стадия 0: reviewer 2 круга, правки R2 вставлены лидом дословно)
<a id="t52"></a>
- Task T5.2: `RobotDataStore` [DONE 2026-10-14 — лид inspector-bottles-89; бриф `tasks/T5.2.md` ред. 2 (стадия 0: reviewer 2 круга), слепая приёмка 10, тесты автора 27, инъекции `tasks/T5.2.injections.md` (20/20 пойманы, 19/20 по прогнозу, выживших нет), reviewer APPROVED во 2-м круге, итог `tasks/T5.2.result.md`; В1, В2 — решения владельца 2026-10-14] (после T5.1)
<a id="t53f"></a>
- Task T5.3f: Одно явное состояние `RobotDriverV2` под одним замком [DONE, в main `60b99f210` (ветка refactor/robot-v2-t53f)] (итог — `tasks/T5.3f.result.md`, отчёт — `docs/reports/2026-10-21_robot-protocol-v2_T5.3f.md`; первой после T5.3c/d — порядок владельца 2026-10-20; задача — решение владельца 2026-10-20) — 30 полей под `_flags_lock` (26 драйвера + 4 `_JogRun`, из них 14 флагов), 53 секции `with self._flags_lock`, 4 замка (3 экземпляра + 1 модуля; `robot_driver_v2.py:188`, :429-433) → одна машина состояний; класс дефектов G2/G4/H* ревью T5.3c/d уходит по построению. Бриф `tasks/T5.3f.md` (f1-T, f1, f2, f3, f4; счёт `tasks/T5.3f.counts.md`, оракул `tasks/T5.3f.state-table.md`, инъекции `tasks/T5.3f.injections.md`) — стадия 0 пройдена (решения teamlead Q1–Q10, ревью стадии 0 учтено, решения владельца 2026-10-20): 27 полей в `RobotState` (13 флагов), 49 секций одного листового замка, 4 замка, пакет на месте модуля с миксинами; окна W1–W4 не закрываются и не открываются (правило 1:1). Дальше f0.5 (инъекции L-I3, H2b на базе) и f1-T.
<a id="t53g"></a>
- Task T5.3g: Окна W1 и W4 гонки `connect` ↔ `request_stop` драйвера робота v2 [DONE на ветке `feat/robot-v2-t53g` 2026-10-21, ждёт слияния — лид inspector-bottles-a9; итог: окна W1, W1′, W4, WW закрыты одной точкой линеаризации (`request_stop_begin`, снимок `_stop_linked`), `_ready` в `RobotState`, ADR-DH-011; проба `tasks/T5.3g.probe.md` 10/10 по прогнозу; стадия 0 Opus р.1 CHANGES REQUESTED (окно W1′) → р.2 APPROVED; слепая приёмка 9 тестов (на старом коде 4 failed / 5 passed по прогнозу); инъекции `tasks/T5.3g.injections-result.md` — 15 из 15 красные (15 — геттер под замком: после быстрого сторожа красный за 3,8 с); на main `cf5855f9c`: device_hub 556 passed, framework suite 12000 passed, backend 235 passed, validate без ошибок. Хэши после rebase: проба `d31bfbf63`→`e0f7cd767`, правка `a550a1f65`/`c322ba796`→`2e4828d68`, правки ревью `4c12d54f3`, быстрый сторож `f26c15b06`; отчёт `docs/reports/2026-10-21_robot-protocol-v2_T5.3g.md`] (после f2 T5.3f — решение владельца 2026-10-20; окна найдены стадией 0 T5.3f, `tasks/T5.3f.state-table.md`, «Окна W1–W4») — W1: `connect`, проверивший выключение до `request_stop`, делает драйвер готовым после выключения (`robot_driver_v2.py:619-623`); W4: `connect` снимает `_stopping` после `request_stop` (:567-578). Простой робот, которому `request_stop` пришёл посреди `connect`, считается подключённым и получает SOFT выключения (решение владельца 2026-10-20). Порядок: проба с барьером «вход → наблюдение», красный тест, правка через переходы `RobotState`. Бриф — `tasks/T5.3g.md`.
<a id="t53h"></a>
- Task T5.3h: SOFT при обычном «Отключить» посреди `connect` драйвера робота v2 [DONE, в main `6652ef88a` 2026-10-21 (ветка `feat/robot-v2-t53h`) — лид inspector-bottles-a9; итог: снимок `_stop_linked` в `disconnect_stop_plan` (монотонный, с живым `link_up()`), переходы `disconnect_soft_plan`/`disconnect_owns_close`, повторная проверка `desired_connected` в тике, ADR-DH-011 дополнен; стадия 0 Opus 2 раунда; слепая приёмка 9/9 по прогнозу; инъекции 14/14 (`tasks/T5.3h.injections-result.md`); ревью задачи Sonnet и ветки Opus APPROVED; device_hub 601/0/3 на main с 1.9m; стенд тика: «Отключить» посреди переподключения → 1 SOFT, до подъёма связи → 0; отчёт `docs/reports/2026-10-21_robot-protocol-v2_T5.3h.md`] (решение владельца 2026-10-21 ~11:50: «да — SOFT и при обычном «Отключить» посреди connect»; порядок: после C-18 robot_demo, до SPI хаба) — правило T5.3g для `disconnect()` (`_stopping` без `_shutdown`): после границы A3 (`connect_link_up`) простой робот считается подключённым и получает ровно один SOFT; до A3 — записи нет (правило 2026-10-19). Остаток ADR-DH-011: `disconnect` решает SOFT по `is_connected`, а `connect_begin` снял `_ready` на весь `connect`. Проба `tasks/T5.3h.probe.md`: 21/21 по прогнозу, 8 красных. Бриф — `tasks/T5.3h.md` (уровень Senior+; стадия 0 Opus р.1 и р.2 CHANGES REQUESTED, бриф р.3: снимок не переписывает request_stop, монотонный снимок, закрытие сокета — только хвост disconnect, повторная проверка `desired_connected` в тике, живой терм `link_up()` в снимке D2).
<a id="c29"></a>
- Task C-29: «Отключить» прерывает идущее ручное подключение робота v2 [DONE на ветке `fix/robot-v2-c29` 2026-10-25, ждёт «ок» на слияние — лид inspector-bottles-e7; стенд S0–S3 PASS (0,75–1,23 с), инъекции 23/23, ревью задачи Sonnet и ветки Opus APPROVED; отчёт `docs/reports/2026-10-25_robot-protocol-v2_C-29.md`; остаток I1 → C-38] (решение владельца 2026-10-21: после T5.3h, перед SPI хаба; решения В1–В6 2026-10-25, реестр C-29/C-33) — `request_disconnect` драйвера v2 из `cmd_device_disconnect` под `_workers_lock` до очереди (точка линеаризации, снимок `_stop_linked`, счётчик запросов); отказ jog / заданий / программ / `return_job` в окне; очистка очереди заданий при отключении; статус без `error`. Бриф `tasks/C-29.md` (Senior+; стадия 0 Opus ×2), приёмка `tasks/C-29.acceptance.md`, проба `tasks/C-29.probe.md`, прогноз инъекций `tasks/C-29.injections-predictions.md`.
<a id="t56"></a>
- Task T5.6: Журнал обмена драйвера [DONE 2026-10-19, слияние `6b16c17fb` — итог `tasks/T5.6.result.md`; ревью Opus APPROVED (р.2); стенд пройден; ветка `feat/robot-v2-t56`] (после T5.1; параллельно T5.3, порядок с полосой Р2 согласован через координатора) — решение владельца 2026-10-18: следующая задача полосы Р, до задач с настоящим роботом

## Ф5 — строка Task T5.3 до сокращения

Полный текст строки Task T5.3 (статус IN PROGRESS, строка остаётся в `plan.md` с сокращённой скобкой статуса):

<a id="t53"></a>
- Task T5.3: Команды хаба [IN PROGRESS — T5.3a+b DONE 2026-10-19, слияние `0a4b07af0`, отчёт `docs/reports/2026-10-19_robot-protocol-v2_T5.3.md`; круг 2 сделан 2026-10-19 (лид inspector-bottles-59, ветка `feat/robot-v2-t53`, перебазирована на main): решение `tasks/T5.3.round2-decision.md`, ADR-DH-009; ревью Opus р.2 → 2b → 2c APPROVED (`docs/reviews/2026-10-19_T5.3ab-round2-opus-review.md`); слепая приёмка 27/27 (до круга 2 — 6 красных); прогнозы инъекций `tasks/T5.3.round2-injections.md`, факты `docs/reports/2026-10-19_T5.3r2-evidence/`; стенд через PM — остановка плагина 0,61–0,77 с, 1 STOP_REQ на робота (`.../stand.md`); выход процесса с двумя роботами — дефект фреймворка L-9 (main `plans/queue/defects.md`); CTO MERGE-READY с условиями (выполнены), слово владельца 2026-10-19. T5.3c, T5.3d — DONE 2026-10-20 на ветке (отчёт `docs/reports/2026-10-20_robot-protocol-v2_T5.3cd.md`; живой стенд 3 passed ×3, ревью Opus р.8 APPROVED `docs/reviews/2026-10-20_T5.3cd-r7-opus-review.md`; слияние — слово владельца); начаты 2026-10-19 (лид inspector-bottles-a5, ветка `feat/robot-v2-t53cd`): брифы сверены с main `ed62d6b38`; T5.3c разделена на c1 (команды данных, каталог, Д2), c2 (отказы параметров и конфига, C-11), c3 (путь стопа драйвера, `tasks/T5.3c3.md`); стадия 0 Opus р.3 — c1, c3 APPROVED, c2 minor закрыты (`tasks/T5.3c.stage0-r3.md`); T5.3d — стадия 0 р.3 CHANGES REQUESTED, бриф делится на d1/d2 (`tasks/T5.3d.stage0-r3.md`); прежнее: бриф `tasks/T5.3.md` + `T5.3a..d.md`, решения владельца О1–О7 2026-10-14] (после T5.2) — в бриф: потоки RobotDriverV2 (поводок, исполнитель) берутся у scope плагина хаба через `spawn`, запись G6 R1 `robot_driver_v2.py` в `scripts/lifecycle_guards/tables.py` удаляется (решение владельца 2026-10-14); advisory ревью T5.1 V1..V3 — `docs/claude/OPEN_QUESTIONS.md` → «Task T5.1»; из T5.2 (решения лида 2026-10-14): `delete_program(device_id, name, *, base_rev)` в `Services/robot_comm/store.py` (ревизия под замком, как `recipe.delete`); один экземпляр `RobotDataStore` на процесс (замки живут в экземпляре); рост словаря `_locks` без предела (ревью T5.2 р.1 п.4: 5000 имён → +1,7 МиБ) — решить, когда имена пойдут из команд хаба (кандидат `WeakValueDictionary` под `_locks_guard`); формат `params.yaml` и адаптер к `param_source=` драйвера
