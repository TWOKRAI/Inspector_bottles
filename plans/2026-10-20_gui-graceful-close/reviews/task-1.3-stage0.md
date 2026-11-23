# Ревью стадии 0 — Task 1.3 (волна «последними»: GUI гаснет после всех)

- **Режим:** `MODE: plan` на одном файле задачи `plans/2026-10-20_gui-graceful-close/tasks/1.3.md`; reviewer, раунд 1 из 2.
- **Дерево:** `main` = `009e35f86`. Задача 1.2 влита (`68884237c`); LSO Task 1.11 тоже уже в `main` (`b1e695121`, `d95959bc9`). Чтение, `git grep`, `git diff main...<ветка>`; тесты не запускались.
- **Вердикт: CHANGES REQUESTED** (14 находок: 8 блокеров `spec`, 4 `architecture`/`tests`, 2 `quality`).
- **Главный итог:** бриф писался до Task 1.11 и до слияния 1.2. Он считает, что бюджет — одна функция `stop_budget()`. Сейчас у бюджета четыре потребителя (`stop_budget()`, `_ceiled_budget`/`_root_budget` PM, область `children`, `ProcessSpawner.stop()`), и два из них вне FILES.

## 1. Чек-лист (для файла задачи: a, d, f, i, ii, iii)

| Пункт | Ответ | Где |
|---|---|---|
| (a) приёмка несёт команду/литерал | частично | числа 7,0/9,0 и 8,5/10,5 — верны (п. 3 ниже); нет литерала для корня PM, спавнера и `stop_deadline_at` последней волны (пп. 1, 2, 7, 13) |
| (d) `Module contract`, `Handoff`, `Gate`, `Dependencies` | да | шапка заполнена; в `Dependencies` LSO Task 1.11 уже влита — пометить «в main», убрать «ждёт» |
| (f) `OUT OF SCOPE` не пуст и не повтор `Goal` | да | |
| (i) у каждого решения DESIGN есть причина | нет | шаг 3 (откуда окно `last`), шаг 5 (`topology.apply`) — причины и механизма нет (пп. 2, 3, 5) |
| (ii) решение не ломает инвариант модуля | нет | шаг 3 ломает окно `main` и force-срок (пп. 3, 4); шаг 4 ломает 3 набора тестов (п. 6); `Literal` ломает «один сбой не роняет соседа» (п. 8) |
| (iii) тексты ошибок без входных значений | нет | `Literal["main","last"]` у pydantic несёт `input_value` в тексте (п. 8) |

## 2. Якоря: «в брифе → сейчас» (`main` `009e35f86`)

| В брифе | Сейчас | Примечание |
|---|---|---|
| `blueprint.py:123` (`protected`) | **:149**; `depends_on` :163; `stop_window_s` :183 | прецедент 1.11 (`Any`, сырым до реестра) стоит прямо рядом |
| `blueprint.py:250-266` (`as_generic_config`) | **:296**; `protected` :305-307; `depends_on` :312-315; `stop_window_s` :345-347 | |
| `process_launch_config.py:76` (`depends_on`) | :76 — не сдвинулось; `stop_window_s` :94 | |
| `process_launch_config.py:161-203` | **:171-188** (pop-блок: `depends_on` :182, `stop_window_s` :188); **`proc_dict` :217-236** (`depends_on` :228-229, `stop_window_s` :232-233) | |
| `presentation.yaml:29-31` | :29-31 — не сдвинулось | |
| `backend/launch.py:309-341` | **:312-350** (`apply_presentation_overlay`); патч целиком `{**procs[position], **patch}` :343 | подтверждает «накладывается целиком» |
| `process_registry.py:438` (`children_stop`) | **:576**; `_build_child_stop` :523-574; `_stop_many` :585-631 | |
| `process_registry.py:531-556` (класс группы) | **`_ChildrenGroupStop` :664-756**; `request_stop` :692, `join_until` :715, `kill` :730, `signalled_at` :735, `result` :743 | |
| `child_process_stop.py:172` | `request_stop` **:195-216**; `join_until` :293-324; `_name_escalate` :326-379; `kill` :244 | |
| `stop_budget.py:73-96` | `stop_budget()` **:80-103**; плюс `valid_window_s` :106, `outer_graceful_s` :124 (1.11) | |
| `process_manager_process.py:3530-3535` | `_root_budget` **:4000-4006**; `_ceiled_budget` :4008-4015; `_budget` :4017-4024; область `children` :4051; вызывается из `process_module.py:379-384` (`_open_root`) внутри `super().initialize()` PM (:320) | |
| (1.2) `stop_wave` геттер | `_stop_wave` **:1080-1082** (вернёт `"main"`), запись в `supervision.status` :1073 | |
| (1.2) `_ChildrenStop` | **:4866-5041**; `set_force_deadline` :4965, `join_until` :4974, `signalled_at` :5004, `kill` :5014 | |
| (1.2a) `_set_system_stop_phase` | **:631**; `_SYSTEM_STOP_PHASES` :61 содержит `last_wave`; `_begin_system_stop` :591 | |
| ADR | **ADR-PMM-042 занят** (1.2, DECISIONS.md:2232); следующий свободный — **ADR-PMM-043** (`git grep ADR-PMM-04[3-9]` вне плана — 0); ADR-PMM-031 :1326, ADR-PMM-035 :1696 | |

## 3. Числа ACCEPTANCE против кода

`stop_budget(None)` (`stop_budget.py:91-93`): `pm_graceful_s` 5,0 → `pm_total_s` = 5,0 + `TERMINATE_GRACE_S` 1,0 + `KILL_CONFIRM_S` 1,0 = **7,0**; `outer_s` = 7,0 + `PM_TEARDOWN_MARGIN_S` 1,5 = **8,5**. С `LAST_WAVE_S = 2,0` в `pm_total_s` до расчёта `outer_s`: **9,0** и **10,5**. Числа верны. Они верны только для самой функции: ни корень PM, ни спавнер в этой проверке не участвуют (пп. 1, 2).

## 4. Находки

### Блокеры (`spec`)

**1. [шапка FILES, шаг 4/TRAPS] FILES неполон: нет `launcher/spawner.py` и `DECISIONS.md`.**
`ProcessSpawner.stop()` считает внешний срок сам: `effective_timeout = stop_budget(graceful)["outer_s"]` (`launcher/spawner.py:212`), без `has_last`. Вход: GUI-топология, PM по новой формуле держит `pm_total_s` 9,0 с; спавнер ждёт `PM.join(8,5)` и шлёт `terminate()` PM в момент, когда `last` ещё гаснет. Результат: ACCEPTANCE «`outer_s` 10,5» верен для функции и ложен для системы. Источник `has_last` у спавнера есть: `self._processes_config` (`spawner.py:57`, :90). Бриф сам называет это в TRAPS («спавнер считает `outer_s` до старта PM»), но FILES туда не ведёт, а правило «файл вне FILES — стоп» остановит teamlead на шаге 4.
Второе: шаг 6 говорит «DECISIONS — 7-й с согласия лида», но в FILES шесть пунктов.
Замена: FILES п. 7 — `multiprocess_framework/modules/process_manager_module/launcher/spawner.py` (`stop()` :205-212: `has_last` из `self._processes_config` и тот же вызов `stop_budget(graceful, has_last=...)`); п. 8 — `multiprocess_framework/modules/process_manager_module/DECISIONS.md` (ADR-PMM-043 + строка в ADR-PMM-031). Для обоих — RED в REDS (п. 13).

**2. [шаг 5] `has_last` «по `_process_configs` до открытия корня» невозможен; «на `topology.apply`» не расширяет открытые области.**
Корень открывается в `super().initialize()` PM (:320 → `process_module.py:255` → `_open_root` :379 → `_root_budget` :4000). `_process_configs` наполняется позже — `_create_processes_from_config` (:338, запись :3848). Вход: GUI-топология при старте → `_process_configs == {}` → `has_last = False` → `proc/PM` получает `budget_s` = 7,0 + 1,0 = 8,0, а ходу детей нужно 9,0 + 1,0. Результат: корень закрывается раньше волны `last`.
Источник на этот момент один: `self.get_config("processes_config")` (его читает и :334). Читать его надо в `__init__` рядом с `self._stop_window_ceiling_s = ...` (:199) — тем же приёмом, что в 1.11.
`topology.apply`: `open_scope(... budget_s=...)` корня и `work.child("children", budget_s=...)` (:4051) считаются один раз при открытии. Рецепт с `gui`, применённый после загрузки топологии без `last`, не может их удлинить; пересчёт `has_last` на `topology.apply` обновит только читателей `_budget()` (например `deadline_at`), но не сами области. Нужно решение лида (ESCALATION → lead): (а) `has_last` фиксируется на старте, смена топологии на `last` без стартового — известное ограничение, записать в ADR-043; (б) резервировать 2,0 с всегда (ломает «числа прежние» и REDS 6); (в) пересоздание областей — вне объёма. Рекомендую (а). Шаг 5 переписать под выбранное; убрать «и на `topology.apply`» либо дать механизм.

**3. [шаг 3 + шаг 5] Область `children` не получает `+ last_wave_s`: `deadline − last_wave_s` зажимает окно `main` до 3,0 с.**
`work.child("children", budget_s=self._budget()["pm_graceful_s"], kill_reserve_s=KILL_RESERVE_S)` (:4051). Бриф прибавляет `last_wave_s` только к `pm_total_s` и `outer_s`, не к `pm_graceful_s`. Срок фазы 2 области = старт + 5,0. По шагу 3 `main.join_until(deadline - 2,0)` = старт + 3,0. `ChildProcessStop._name_escalate` берёт `term_at = min(request_stop + окно, deadline)` (`child_process_stop.py:345`) = старт + 3,0.
Вход: `has_last`, ребёнок `main` штатно выходит за 3,5 с (в пределах его `stop_budget` для g = 5,0: `work_s` 3,0 + `infra_s` 1,0 = 4,0). Наблюдаемый результат: `terminate` на 3,0 с, `stop_outcome = terminated` вместо `exited`. Это регресс каждого штатного стопа с окном, и ни один из 6 REDS его не ловит.
Замена шага 3/5: «при `has_last` область `children` строится с `budget_s = pm_graceful_s + last_wave_s` (резерв прежний `KILL_RESERVE_S`); тогда `deadline` фазы 2 = старт + 7,0, `deadline − last_wave_s` = старт + 5,0 = окно `g`, потолок хода = 7,0 + 2,0 = 9,0 = `pm_total_s`». `_begin_system_stop().deadline_at` (:601, `pm_graceful_s`) остаётся граничным сроком `main`; сказать это в ADR-043. Добавить RED (п. 13, R7).

**4. [шаг 3] Не определено, что делать, когда `deadline − now < last_wave_s` (режим `force`).**
`_ChildrenStop.join_until` режет срок `min(deadline, force_at)` (:4992-4994). Вход: `system.shutdown {"mode": "force", "deadline_s": 0.5}` — ровно то, что шлёт «Закрыть принудительно» (`design.md`, C) — на топологии с `gui`. `main.join_until(force_at − 2,0)` → срок в прошлом → `_name_escalate`: `term_at = min(request + окно, прошлое)` → `terminate` всем детям `main` на первом проходе. Результат: graceful-окно `main` 0 с вместо 0,5 с; `last` получает `request_stop` сразу. Регресс force из Task 0.2 (диапазон `deadline_s` 0,1–5,0) для любой топологии с `gui`.
Замена: «если `deadline − time.monotonic() ≤ last_wave_s` (в частности при `force`) разделения нет: `request_stop` обеим группам сразу, один общий `join_until(deadline)`». RED R8. Если лид хочет иное (например `force` всё равно ждёт `main` первым) — записать.

**5. [шаг 3] Две группы, один блокирующий `join_until`: поток-владелец не может ждать обеих.**
`ChildProcessStop.join_until` — цикл до срока; `name`-kill (`_name_kill_at`, term + `TERMINATE_GRACE_S`) уходит только из этого цикла (:343-355). Прямое прочтение шага 3: `main.join_until(D − 2,0)`, затем `last.request_stop()`, `last.join_until(D)`. Вход: ребёнок `main` игнорирует SIGTERM; terminate на 5,0, kill должен уйти на 6,0; в интервале [5,0; D] поток внутри `last.join_until` — `main` не опрашивается. Результат: SIGKILL уходит на `kill()` фазы 3 (старт + 7,0 и позже), а не на 6,0; метка ReaderGone и итог `main` задерживаются; `last` ждёт без нужды. Бриф говорит «эскалация у каждой группы своя» и не описывает, кто её крутит.
Замена шага 3 (цикл): «`_ChildrenGroupStop.join_until(deadline)` при `has_last` и `deadline − now > last_wave_s` крутит оба объекта короткими шагами (`join_until(min(now + STOP_POLL_S, D))` по очереди); `last.request_stop()` один раз — как только `main.join_until` вернул `True` или `now ≥ D − last_wave_s`; возврат `True` — обе группы пусты». Дописать, что на каждом шаге затронуты все методы, где сегодня стоит один `self._group`: `join_until` (`survived` — снимок обеих групп, :724-727), `kill` (:730, `last.kill()` — только если `last` уже сигналили; иначе `terminate` придёт до `stop_event`), `close` (:739), `result` (:743-756), `request_stop` (запись `exited` умершим до стопа — объединить `done` двух сборок, :709-711). Фаза 3 зовёт тот же `join_until` с `until = now + 2,0`: `D − 2,0 = now`, значит повторный вызов — одна выборка `main` и ожидание `last`; сказать это явно.

**6. [шаг 4] Ключ `last_wave_s` в словаре: «есть всегда» ломает три набора существующих тестов.**
Бриф: «новая константа `LAST_WAVE_S = 2.0` и ключ `last_wave_s`» + «числа прежние». Если ключ есть в результате всегда (`0.0` без `has_last`), красными становятся (это страж, не RED): `test_stop_budget_child_stop_acceptance.py:187,200,213` (`list(r) == _KEYS`, пять ключей), `test_stop_budget.py:59` (`pytest.approx` по словарю из пяти ключей), `test_process_root_pm_hazards.py:100,106,121` (`==` по пяти ключам; `DEFAULT_STOP_BUDGET`). Слепой тестер, читая шаг 4, может написать RED 6 любым из двух способов.
Замена: «`last_wave_s` — ключ результата **только** при `has_last=True`; при `False` словарь — ровно пять прежних ключей, в прежнем порядке. `_STOP_BUDGET_KEYS` раннера (`process_runner.py:41`) не меняется: шестой ключ в `process_config["stop_budget"]` не нужен, PM считает `has_last` сам». И дать форму вызова: `stop_budget(5.0, has_last=True)`.

**7. [шаг 5, `supervision.status`] `stop_deadline_at` у детей волны `last` — по сигналу волны `main`.**
`_cmd_supervision_status` берёт один `signalled_at = self._children_signalled_at()` (вызов :1034, метод :1084; источник `_ChildrenStop.signalled_at` :5004 → `_ChildrenGroupStop.signalled_at` :735 → `self._group.stop_requested_wall`), и `_stop_deadline_at` (:1102) прибавляет к нему окно имени. С двумя группами значение одно. Вход: `main` выходит 3,0 с, `gui` получил сигнал на 3,0 с; запрос на 3,5 с. Наблюдаемое: `gui.stop_deadline_at` = сигнал `main` + 5,0 = 5,0 с, реальный срок 8,0 с → окно прогресса (Task 2.1, «порог вопроса о зависании = `stop_deadline_at`») назовёт `gui` зависшим на 5,0 с; на 1,0 с (до сигнала `last`) поле уже число, а контракт ADR-PMM-042 — `null` до сигнала.
Замена: `signalled_at(name)` на волну: `_ChildrenGroupStop.signalled_at(name=None)` отдаёт `stop_requested_wall` группы, в которой имя; `_children_signalled_at(name)` в PM и `_stop_deadline_at` — по имени; для `last` до `last.request_stop()` — `None`. Двойники группы без аргумента `name` читать через `getattr` + `try/except TypeError` (как сегодня в `_children_signalled_at` :1084). RED R9.

**8. [шаг 1, (ii)+(iii)] `stop_wave: Literal["main", "last"]`: опечатка в рецепте роняет весь blueprint, текст ошибки несёт значение.**
Pydantic на `stop_wave: "late"` бросит `ValidationError` с `input_value='late'`. Вход: `stop_wave: late` у одного процесса рецепта. Результат: топология не грузится целиком (принцип 5: сбой одного не роняет соседей), а текст ошибки содержит введённое значение (пункт (iii)). Прецедент 1.11 решает это иначе: поле `Any`, значение идёт сырым до реестра, там `valid_window_s` → негодное игнорируется WARNING без значения (`blueprint.py:183-190`, `process_launch_config.py:94-100`, `process_registry.py:164-179`).
Замена шага 1: «`stop_wave: Any = None` (как `stop_window_s`; `"main"` и `None` — одно и то же), проверка в реестре: годно ровно `"main"` или `"last"`, иное — WARNING без значения (`stop_wave процесса '<имя>' негоден — волна main`), процесс идёт в `main`». Тип `Literal` убрать из DESIGN. RED (в REDS 4 или отдельный): негодное значение не роняет `as_generic_config` и не попадает в текст.

### Major

**9. [шаг 3, `process_registry.py`] Не описано, как реестр узнаёт волну имени.**
`_ChildrenGroupStop.request_stop` берёт имена из `os_processes` (:698); поля волны у `Process` нет. Бриф говорит только «схема → `proc_dict`». `ProcessRegistry.create_and_register` получает `proc_dict` целиком (`_topology_create` :4834-4851 передаёт его как `config`; `_register_stop_window` вызывается из :292).
Замена: «реестр держит `_stop_waves: dict[str, str]`, пишет в `create_and_register` рядом с `_register_stop_window` (:292) — пересоздание `gui` после `topology.apply` обновляет запись, снятие процесса её удаляет; публичный `stop_wave(name) -> str` (по умолчанию `"main"`); PM `_stop_wave` (:1080) делегирует ему через `getattr` + проверку `str` (двойники реестра — `tests/conftest.py:73`, `MagicMock` в `test_supervision_instance_truth.py`)». Это закрывает TRAPS «рестарт `gui` после `topology.apply`»: другого пути создания (`_create_processes_from_config` :4117 — `create_process`) нет. Путь рестарта монитором проверить: берёт ли он конфиг из `_process_configs` (в них `stop_wave` сохраняется как есть).

**10. [шаг 5] Переход `main → last` случается внутри группы реестра; вызвать `_set_system_stop_phase("last_wave")` оттуда некому.**
Фаза ставится в PM (`_ChildrenStop._announce_phase` :5029 → `_set_system_stop_phase` :631 + `_publish_system_stop`). Переход же определяет `_ChildrenGroupStop` (слой реестра, PM не знает). Бриф пишет «PM ставит фазу при переходе» без механизма. Нельзя добавить kwarg в `children_stop(*, mark_reader_gone)` (:576): двойник `children_stop(*, mark_reader_gone: bool)` в `tests/test_pm_responsive_during_children_stop.py:241` упадёт `TypeError` (и ещё четыре двойника — читал по `grep`).
Замена: «`_ChildrenGroupStop` получает публичный атрибут/свойство `wave: str` (`"main"` → `"last"`), PM читает его в `_ChildrenStop.join_until` после каждого вызова группы и при смене зовёт `_announce_phase("last_wave")`; сигнатура `children_stop` не меняется; двойники без `wave` читаются через `getattr(..., None)`». Дописать: `_set_system_stop_phase` меняет только `phase`, `deadline_at` («конец graceful-окна текущей фазы», `design.md`) остаётся `started_at + pm_graceful_s` — решить: сдвигать ли его на `now + last_wave_s` при переходе (рекомендую: да, одна строка в `_set_system_stop_phase`/вызывающем, иначе `system_stop.deadline_at` в `last_wave` уже в прошлом).

**11. [шаг 6] Номер ADR и ссылки.**
`ADR-PMM-0xx` → **ADR-PMM-043** (042 занят). Строка в ADR-PMM-031 (:1326) — «бюджет волн: `pm_total_s`/`outer_s` + `last_wave_s` только при `has_last`»; ссылка на ADR-PMM-035 (:1696, `stop_budget`) и на 1.11 (потолок окон). В ADR-043 назвать: пп. 2 (ограничение `topology.apply`), 3 (`budget_s` области), 4 (force без разделения), 7 (`signalled_at` по волне), 8 (`stop_wave` негодное → `main`). В ADR-PMM-042 «Последствия» дописать «`stop_wave` — константа `main` до Task 1.3».

**12. [шаг 4, ACCEPTANCE] `LAST_WAVE_S = 2,0` — выбор без замера против бюджета самого `gui`.**
`gui` получает `stop_budget` с `work_s` 3,0 + `infra_s` 1,0 = 4,0 (g = 5,0). Окно `last` — 2,0 с. Вход: `gui` с Qt-teardown 2,5 с. Результат: `terminate` на 2,0 с, exitcode −15 — тот самый дефект, который чиним. Это не противоречие коду, а непроверенное число: Mac-проба 1.1a/1.2 и H2 Task 0.1 мерили выход всей системы, не `gui` отдельно. В ACCEPTANCE записать предусловие «замер штатного выхода `gui` при стопе (сколько секунд от `stop_event` до `exit 0`) снят на стенде до фиксации `LAST_WAVE_S`», либо взять константу с запасом (3,0 с — на 1,0 с длиннее; цену в `outer_s` назвать). Решение лида; не блокер, потому что живой пункт «5 из 5» это поймает.

**13. [REDS, ACCEPTANCE] Пробелы в REDS и в инъекциях.**
Все шесть REDS достижимы по FILES (REDS 1–2 — `process_registry.py`, 3 — `stop_budget.py`, 4 — `blueprint.py` + `process_launch_config.py`, 5 — `presentation.yaml` и `apply_presentation_overlay` без правки `launch.py`, 6 — `stop_budget.py`). Но:
- Ни один RED не касается корня PM и спавнера (пп. 1, 2): `has_last` в `_root_budget`/`_ceiled_budget`/`spawner.stop()` можно не написать — все шесть позеленеют.
- Нет RED на пп. 3, 4, 7, 8. Предел 10: добавить четыре — итого 10.
  R7 `test_main_child_with_4s_stop_not_terminated_when_last_present` (п. 3); R8 `test_force_deadline_shorter_than_last_wave_gives_both_waves_signal_at_once` (п. 4); R9 `test_last_child_stop_deadline_null_until_signalled_then_from_own_signal` (п. 7); R10 `test_invalid_stop_wave_ignored_with_warning_without_value` (п. 8). Корень и спавнер (пп. 1, 2) — внутрь REDS 3: `has_last` по `processes_config` для `_root_budget` и `spawner.stop()` как параметры того же теста; если не влезает — вместо R10 (п. 8 как страж в авторских тестах).
- Break-injection: заявлена одна («одна группа вместо двух»). Добавить: `has_last` всегда `False` в `_root_budget` → красный REDS по корню; `last_wave_s` вне условия `has_last` → REDS 3 и 6; `deadline − last_wave_s` убрать (обе группы сразу) → REDS 1; ключ `last_wave_s` всегда → страж `test_stop_budget_child_stop_acceptance`; волну по имени читать из `main` для всех → R9. Предсказать красные до прогона.
- REDS 3 и 6: форму вызова дать литералом (`stop_budget(5.0, has_last=True)`); REDS 6 — «словарь ровно из пяти ключей» (п. 6).

### Quality

**14. [шапка, TESTS, `Dependencies`] Остатки.**
- Якоря шагов 1–5 заменить таблицей из п. 2 (бриф пятикратно промахивается).
- `TESTS`: `.venv/Scripts/python.exe` — путь Windows; на Darwin стенда нет `Scripts`. Образец 1.2 шёл Mac-пробой — написать оба (`.venv/bin/python` на Mac) или `python` из окружения.
- `Dependencies`: LSO Task 1.11 «влита в `main` (`b1e695121`, `d95959bc9`)»; Task 1.2 — «влита `68884237c`»; «`stop_wave` — геттер Task 1.2» → `_stop_wave` :1080.
- Шаг 5: «`stop_wave` в `supervision.status` (геттер… здесь заменяется)» → «`_stop_wave(name)` :1080 делегирует `registry.stop_wave(name)`».

## 5. FILES: полнота

Нужно: 1–6 как в брифе (правки по пп. 2, 3, 9, 10 уходят в п. 3 и п. 5) + **п. 7 `launcher/spawner.py`** + **п. 8 `DECISIONS.md`** (п. 1). `tests/conftest.py` (`MockProcessRegistry`) — не нужен, если PM читает волну через `getattr` + проверку типа (п. 9). `process_runner.py` и `process_module.py` не меняются (п. 6; `_root_budget` — переопределение PM). `interfaces.py` модуля не затрагивается.

## 6. Пересечения с чужими работами

- `git status` главного дерева: изменён только `docs/reports/2026-10-26_stage0-eval.md` (посторонний), без путей FILES.
- Открытые локальные ветки против FILES (`git diff main...<ветка>` по семи путям + `DECISIONS.md`): пересечение одно — `feat/fc-f2-frontend-entry` (создаёт `multiprocess_prototype/frontend/presentation.yaml` целиком; ветка старая, слияния нет, при её слиянии будет конфликт по файлу). Остальные ветки и worktree на этих путях чисты.
- Worktree с неслитыми файлами в `process_manager_module/tests/` — тестовые ветки 1.2, 1.2a, LSO 1.4 (`op-1.2-tester`, `op-1.2a-tester`, `lso-1.4-tester`, `agent-a140…`): только файлы тестов; в FILES 1.3 они не входят.
- `process_manager_process.py`: работ параллельно нет. Единственное окно конфликта — слепой тестер 1.3 пишет `tests/test_stop_wave_last.py` (новый файл, не конфликтует).

## 7. Итоговый список правок (для лида)

| Пункт чек-листа | Находка | Что исправить |
|---|---|---|
| (d)/(i) FILES | 1 | добавить `spawner.py` (п. 7) и `DECISIONS.md` (п. 8) |
| (i)/(ii) шаг 5 | 2 | `has_last` из `get_config("processes_config")` в `__init__`; решение лида по `topology.apply` |
| (ii) шаг 3/5 | 3 | `children` area `budget_s = pm_graceful_s + last_wave_s` при `has_last` |
| (ii) шаг 3 | 4 | при `deadline − now ≤ last_wave_s` — без разделения |
| (i) шаг 3 | 5 | цикл опроса двух групп; методы группы под две сборки; поведение фазы 3 |
| (ii) шаг 4 | 6 | `last_wave_s` — ключ только при `has_last`; форма вызова |
| (a)/(ii) шаг 5 | 7 | `signalled_at(name)` по волне |
| (ii)/(iii) шаг 1 | 8 | `stop_wave: Any = None` + проверка в реестре, WARNING без значения |
| (i) шаг 3 | 9 | `_stop_waves` в реестре, регистрация в `create_and_register` |
| (i) шаг 5 | 10 | `wave` у группы, PM читает; сигнатура `children_stop` не меняется; `deadline_at` |
| (i) шаг 6 | 11 | ADR-PMM-043; строка в ADR-031; ссылки |
| (a) | 12 | замер выхода `gui` до фиксации `LAST_WAVE_S` или запас |
| (a) | 13 | R7–R10, корень/спавнер в REDS 3, инъекции по свойствам |
| — | 14 | якоря, `TESTS`, `Dependencies` |

## 8. Что осталось открытым / ненадёжно

1. Ничего не запускал (по заданию). «Красный до правки» и все сценарии в пп. 3–7 — вывод из чтения кода (`ChildProcessStop._name_escalate`, `_ChildrenGroupStop`, `lifetime.py:568-654`), не из прогона. Числа «терминейт на 3,0 с», «SIGKILL на 7,0+» — арифметика по сроку фаз, не замер.
2. Фазы области читал по `lifetime.py:568-654` (`_close_entries`, `_phase3`), не целиком; допущение «срок фазы 2 = старт области + `budget_s`, срок фазы 3 = `now + kill_reserve_s`» — по этим строкам и :394-399.
3. Не проверял, что монитор при рестарте `gui` берёт конфиг из `_process_configs` целиком (п. 9: путь рестарта через `ProcessMonitor` не читал); не проверял, обновляет ли `topology.apply` `ProcessSpawner._processes_config` (почти наверняка нет — спавнер видит топологию старта, п. 1/2).
4. Пять двойников `children_stop` (п. 10) — читал только по `grep` и `test_pm_responsive_during_children_stop.py:117-135, 241`; остальные не открывал.
5. `design.md` («Порядок остановки»: «волна `main` → волна `last` → PM выходит») не говорит, нужен ли `pre_stop`/`force` без разделения волн; п. 4 — моё чтение «force: срок волн = `deadline_s`». Если владелец хочет, чтобы `gui` и в `force` ждал `main`, п. 4 меняется — решение лида.
6. Живой пункт ACCEPTANCE (Windows, 5 из 5, «окно скрыто позже строки эскалации») не оценивал: ждёт стенда. Число 2,0 с (п. 12) не проверено ни одним замером.
7. `memory hits:` — `scripts/memory/search.py` не запускал (бюджет контекста); qex не использовал, индекс не проверял — только `git grep` по путям. Список веток/worktree сверен по `git diff main...<ветка>` и `git status` по путям; незафиксированные правки в 80 worktree проверены только по этим путям.
8. Ветка `feat/fc-f2-frontend-entry`: считаю старой по тому, что `git diff main...` показывает `presentation.yaml` как новый файл; не выяснял, живая ли она у владельца.

---

# Раунд 2 (последний)

- **Читано:** `tasks/1.3.md` в рабочем дереве (не закоммичено: `git diff --stat` +97/−32) против кода `main` `79bd453f6`. С `009e35f86` в `main` добавлены только два файла `docs/` (отчёт и handoff Р2 T5.5) — якоря кода не сдвинулись, выборочно перепроверены (`blueprint.py` :149/:163/:183/:296, `process_registry.py` :576/:664-756/:292, `_stop_wave` :1080, `_ChildrenStop` :4866, область `children` :4051, `spawner.py` :205-212). Ничего не запускалось.
- **Вердикт: CHANGES REQUESTED (итерация 2 из 2).** Из 14 пунктов раунда 1 закрыто 10 по существу; 4 закрыты только по тексту или частично. Новых расхождений с кодом три — все в механике шагов 4 и 7 (одна — следствие моего же предложения из раунда 1, п. 3). Остальное — правки текста и тестов. Замены даны дословно: если лид применит их и проверит `git diff`, стадию 0 считаю закрытой без третьего раунда; выбор из развилок R2-1…R2-3 — за лидом.

## 1. Пункты раунда 1: закрыты ли

| № | Пункт | Статус | Замечание |
|---|---|---|---|
| 1 | FILES: `spawner.py`, `DECISIONS.md` | да (п. 7, 8) | если принять R2-1 вариант `poll`, нужен п. 9 `child_process_stop.py` |
| 2 | `has_last` из `processes_config` в `__init__`; `topology.apply` — вариант (а) | да (шаг 6, OUT OF SCOPE) | мелочь R2-7(b): ранний `return base` в `_ceiled_budget` :4011-4012 |
| 3 | `budget_s` области `children` + `last_wave_s` | да по тексту (шаг 5) | RED 7 на это свойство зелёный до правки (R2-4) |
| 4 | малый срок / `force` без разделения | да по тексту (шаг 4) | при цикле шага 4 правило избыточно, инъекция (8) красной не станет (R2-5) |
| 5 | цикл двух групп, методы, фаза 3 | **нет** | цикл из шага 4 сам ломает окна имён (R2-1); фаза 3 описана дважды по-разному (R2-7(e)) |
| 6 | `last_wave_s` — ключ только при `has_last` | да (шаг 5) | |
| 7 | `signalled_at(name)` по волне | частично (шаг 7) | `_ChildrenStop.signalled_at` :5004 не назван; имя из `done` не определено (R2-7(a)) |
| 8 | `stop_wave: Any`, WARNING без значения | да (шаг 1, RED 10) | RED 10 красен до правки, только если проверяет WARNING (R2-4) |
| 9 | `_stop_waves` в реестре | да (шаг 3) | вызов `_register_stop_window` стоит в `_create_process` :292, не в `create_and_register` (R2-7(c)) |
| 10 | хук перехода волны, `children_stop` без нового kwarg, `deadline_at` | **нет** | чтение `group.wave` после вызова группы не видит переход (R2-2); сдвиг `deadline_at` не определён (R2-2) |
| 11 | ADR-PMM-043, ADR-031, ссылки | да (шаг 8) | 043 свободен: `rg ADR-PMM-043` по `plans docs multiprocess_framework .claude/worktrees` — только тексты этого плана |
| 12 | `LAST_WAVE_S` и замер `gui` | да (шаг 9, ACCEPTANCE) | |
| 13 | REDS и инъекции | частично | REDS 7, 8 зелёные до правки; предсказания (1), (4), (5), (6), (7), (8) неверны или неполны (R2-4, R2-5) |
| 14 | якоря, `TESTS`, `Dependencies` | да | |

## 2. Новые расхождения с кодом

### R2-1 [шаг 4] [spec, блокер] Цикл «короткими шагами `join_until(min(now + STOP_POLL_S, D))`» посылает `terminate` через ~50 мс.

`ChildProcessStop._name_escalate` берёт срок сигнала имени как `term_at = min(self._stop_requested_at + window, deadline)` (`child_process_stop.py:345`) и шлёт `terminate`, как только `now >= term_at` (:346-352). `deadline` — аргумент ЭТОГО вызова `join_until`. Короткий шаг делает `deadline = now + 0,05`: к концу паузы (`pause = min(poll, deadline − now)` :319, `name_next − now` :322-323) `now >= deadline`, и на следующем проходе цикла `term_at = deadline` уже наступил.
Вход → результат: путь с окнами (хоть один `stop_window_s` в конфиге процесса или `max_stop_window_s` > g, `_group_windows`, `process_registry.py:192-203`), ребёнок `main` выходит штатно за 3,5 с; шаг 4 вызывает `main.join_until(now + 0,05)` → на втором проходе `terminate` ребёнку `main` на 0,05 с, итог `terminated` вместо `exited`; то же для `last`. Дефект тот же класс, что п. 3 раунда 1, но через шаг, а не через `D − last_wave_s`.
Оговорка: путь без окон (`windows_s is None`) сигналов до `kill()` не шлёт (docstring :25-28) — там цикл безвреден. Это путь по умолчанию в прототипе (`multiprocess_prototype`: `stop_window_s`/`max_stop_window_s` — 0 вхождений в не-тестовом коде, `git grep`), поэтому RED, собранный на пути по умолчанию, дефект не поймает; поймает только RED на пути с окнами.
Замена (выбор лида):
- **Рекомендую:** в FILES п. 9 `core/child_process_stop.py` — новый публичный `poll(deadline: float) -> tuple[bool | None, float]`: ровно один проход тела `join_until` (наблюдение, abort, `_name_escalate`, `_kill_at`), без ожидания; результат: `True` — ждать некого; `False` — срок `deadline` вышел или abort; `None` — продолжать; второй элемент — пауза до ближайшего события. `join_until` переписывается как `while True: r, pause = self.poll(deadline); if r is not None: return r; self._wait(pause)` — поведение прежнее, `deadline` настоящий. Строку в «Public API» и «Инварианты» модуля дописать. Тест на `poll` — авторский, страж `join_until`: существующие тесты `child_process_stop` зелёные без правки.
  Шаг 4 тогда: «`_ChildrenGroupStop.join_until(D)` при `has_last` и непустой `last`: `while True: m, p1 = main.poll(D)`; `last.request_stop()` ОДИН раз, вне `self._lock` группы, как только `m is True` или `monotonic() ≥ D − last_wave_s` (затем вызов слушателя волны, R2-2); после сигнала `l, p2 = last.poll(D)`; возврат `True`, когда обе пусты; `False`, когда срок `D` вышел или abort; пауза — `main._wait(min(p1, p2))` (idle PM, ADR-PMM-037). `D` в `poll` — срок области, а не шаг опроса».
- Запасной вариант без правки `child_process_stop.py`: `last.request_stop()` из колбэка `idle` сборки `main` (параметр уже есть, `process_registry.py:571`) и один вызов `main.join_until(D)`; сборка `last` не опрашивается, пока `main` не вернулся — метки ReaderGone и `exited` у `last` задерживаются до конца `main`. Хуже: не рекомендую.

### R2-2 [шаг 7] [spec, блокер] Фаза `last_wave` не будет видна: переход происходит внутри одного блокирующего вызова.

Шаг 7: «`_ChildrenStop.join_until` после каждого вызова группы читает `group.wave`; при смене на `"last"` зовёт `_announce_phase("last_wave")`». Область зовёт `join_until` один раз на фазу (`lifetime.py:581` — фаза 2; :645 — фаза 3), а переход `main → last` случается ВНУТРИ этого вызова (шаг 4). `_ChildrenStop.join_until` (:4974) читает `wave` только когда вызов вернулся.
Вход → результат: `main` вышел за 1,5 с, `gui` — за 3,5 с; вызов группы вернул `True` на 3,5 с; PM читает `wave == "last"` и вызывает `_announce_phase("last_wave")` и сразу `_announce_phase("done")` (:4996-5001). `system.stop.phase` весь ход равна `children`, `last_wave` публикуется за миллисекунды до `done`. Окно прогресса (Task 2.1, `design.md` A3: «Остановка процессов» → «Остановка интерфейса») шага «интерфейс» вживую не увидит. Тест, который читает фазу посреди хода, красный после правки.
Замена шага 7: «Группа имеет `set_wave_listener(callback)`; цикл шага 4 зовёт `callback("last")` в момент `last.request_stop()`, вне лока группы. PM в `_ChildrenStop._start` после `children_stop(...)` (:4906) делает `setter = getattr(group, "set_wave_listener", None); if callable(setter): setter(self._on_last_wave)`. `_on_last_wave` зовёт `_announce_phase("last_wave")` и `pm._extend_system_stop_deadline(...)` (ниже). Сигнатура `children_stop` не меняется; `_GroupProxy.__getattr__` (`tests/test_pm_responsive_during_children_stop.py:117-135`) делегирует метод настоящей группе — слушатель не теряется. Колбэк не бросает: сбой — ERROR в лог, стоп идёт (как `_announce_phase` :5037-5038). Публичное свойство `wave` остаётся для чтения (тест, `supervision.status`), но PM по нему переход не ловит».
Срок: «сдвигает `system_stop.deadline_at` на `monotonic-эквивалент + last_wave_s`» — не определено. Окно `last` не равно 2,0 с, если `main` вышел рано (`last` сигналят при пустом `main`; ему остаётся `D − now`). Замена: «`deadline_at` ставится в `time.time() + (D − time.monotonic())` — настоящий срок области на момент сигнала `last`; при `force` (`_force_at` стоит) срок остаётся `force`-овым, сдвига нет». Изменение — под `_system_stop_lock`, как `_escalate_system_stop` (:617-629); отдельный помощник PM, не вызов из реестра.

### R2-3 [шаги 4–5 против REDS 2 и ACCEPTANCE] [spec, блокер] «`last` получает сигнал после эскалации `main`» и «окно скрыто позже строки эскалации» не следуют из алгоритма.

Это следствие моего предложения из раунда 1 (п. 3: `budget_s = pm_graceful_s + last_wave_s`, `D − last_wave_s` = окно g): я не просчитал порядок событий. Алгоритм шага 4: `last.request_stop()` в `D − last_wave_s` = старт + 5,0 (или раньше, если `main` пуст). Эскалация `main`:
- путь с окнами: `terminate` на `min(request + 5,0, D)` = 5,0 — одновременно с сигналом `last` (ничья, порядок строк лога зависит от порядка кода);
- путь без окон (прототип по умолчанию): `terminate` `main` — на `kill()` области после срока фазы 2, то есть на 7,0. `gui` сигналят на 5,0, он выходит на 5,x. Строка «окно скрыто» (5,x) РАНЬШЕ строки эскалации (7,0).
Вход → результат на живом стенде (`main` висит 8 с, путь по умолчанию): ACCEPTANCE «строка «окно скрыто» позже строки эскалации зависшего» — ложна; REDS 2 «`last` получает сигнал после эскалации `main`» — ложен на этом пути.
Лид решает, что триггер: (А) по времени — алгоритм как написан; тогда меняются REDS 2 и живой критерий; (Б) по концу эскалации `main` — исходный замысел брифа раунда 0 (7,0 `main` + 2,0 `last` = `pm_total_s` 9,0); тогда областью `children` нужна другая раскладка (`budget_s` прежний, резерв `kill_reserve_s + last_wave_s`) и `last` сигналят после подтверждения смерти `main` — шаги 4–5 переписываются, раунд 3 не покроет. **Рекомендую (А)** — он согласован с остальным текстом и кодом. Замена при (А):
- REDS 2: «`main` висит 8 с → `last` получает `stop_event` не раньше старт + 5,0 (`D − last_wave_s`) и не позже старт + 5,0 + `STOP_POLL_S`; `gui` не получает `terminate` раньше, чем через 2,0 с после своего сигнала; exitcode `last` = 0, не −15. На пути с окнами: `terminate` `main` ровно на 5,0 (не на 0,05, R2-1)».
- Живой критерий: «exitcode `gui` 0 (не −15) 5 из 5; строка «окно скрыто» не раньше сигнала `last` + замера выхода `gui` и не позже старт + `pm_total_s`» (порядок относительно строки эскалации `main` не проверять — он зависит от пути).
- В ADR-043 записать: «`last` сигналят в `D − last_wave_s` или при пустом `main`; `terminate` `main` на пути без окон идёт на `kill()` области — позже сигнала `last`».

## 3. REDS 1–10: красные ли до правки, достижимы ли

Достижимость: все десять идут через FILES 1–7 (REDS 3, 6 — п. 4; 4, 10 — пп. 1–3; 5 — п. 6 и чтение `apply_presentation_overlay` без правки `launch.py`; 1, 2, 7, 8 — пп. 3, 5; 9 — пп. 3, 5). Литералы 7,0/9,0 и 8,5/10,5 — верны (раунд 1, п. 3).

| RED | Красный до правки? | Почему |
|---|---|---|
| 1 `last_wave_child_not_signalled_until_main_done` | да | одна группа сигналит всех сразу |
| 2 `hung_main_child_does_not_terminate_last_child` | да | `kill()` области терминирует всех, включая `gui` (−15) |
| 3 `budget_adds_2s_only_with_last` | да | `TypeError`: аргумента `has_last` нет |
| 4 `blueprint_stop_wave_roundtrip_to_proc_dict` | да | поля нет, `proc_dict` без `stop_wave` |
| 5 `presentation_overlay_marks_gui_last` | да | в `presentation.yaml` нет строки |
| 6 `no_last_children_keeps_old_budget_literals` | **нет**, если проверяет только старые литералы | зелёный до правки. Сделать красным: вызывать `stop_budget(5.0, has_last=False)` (до правки `TypeError`) и сверять пять ключей и литералы |
| 7 `main_child_with_4s_stop_not_terminated_when_last_present` | **нет** | до правки одна группа: `main` со стопом 4 с выходит `exited` в срок 5,0 (на любом пути) — зелёный. См. замену ниже |
| 8 `force_deadline_shorter_than_last_wave_...` | **нет** | до правки обе роли сигналятся сразу, `terminate` не раньше `force_at` (с окнами — `min(request + окно, force_at)` = `force_at`; без окон — на `kill()` после срока) — зелёный; это страж новой логики, не RED |
| 9 `last_child_stop_deadline_null_until_signalled_...` | да | до правки сигнал один, `stop_deadline_at(gui)` не `null` с начала стопа |
| 10 `invalid_stop_wave_ignored_with_warning_without_value` | да, только если проверяет WARNING | до правки WARNING нет; проверка «не бросает» одна — зелёная до правки |

Значит «REDS красные до, зелёные после» (ACCEPTANCE) выполняется для 1–5, 9, 10 и для 6 с явным `has_last=False`; REDS 7 и 8 — стражи. Предел 10 не нарушен; пометить 7, 8 как «страж (красный только под инъекцией)».

**R2-4 [tests, major]** Замены:
- RED 6: «вызывает `stop_budget(5.0, has_last=False)`; словарь — ровно пять прежних ключей в прежнем порядке, литералы 3,0/1,0/5,0/7,0/8,5».
- RED 7 (сделать RED, а не стражем): «`has_last`, `main`-ребёнок со стопом 4,0 с и `last`-ребёнок со стопом 2,0 с: `last` не сигналят до выхода `main` (красный до правки — как RED 1) и итог `last` — `exited`, а не `terminated`». Эта вторая половина ловит инъекцию (7): без `+ last_wave_s` срок области старт + 5,0, `last` сигналят на 4,0 и терминируют на 5,0 (1,0 с вместо 2,0). В брифе формулировка «`main` со стопом 4 с → `exited`» зелёная и до правки, и под инъекцией (7) — предсказание «RED 7 красный» на ней неверно (мой вывод из `child_process_stop.py:326-379` и `lifetime.py:568-654`, не прогон).
- RED 8: пометить «страж»; предсказание — см. R2-5.
- RED 10: «WARNING есть и не содержит слова `late`; `as_generic_config` не бросает; `proc_dict` без искажения — процесс в `main`».

## 4. Предсказания break-injection (9 штук)

| Инъекция (из ACCEPTANCE) | Предсказано | Моё чтение |
|---|---|---|
| (1) одна группа вместо двух | REDS 2 и 1 | **1, 2, 9** (`stop_deadline_at(gui)` не `null` до сигнала `last`) |
| (2) `has_last` всегда `False` в `_root_budget` | страж корня | верно: стража нет среди REDS, он авторский; RED 3 зелёный (функция) |
| (3) `last_wave_s` вне `has_last` | REDS 3 и 6 | верно (3: 7,0 ≠ 9,0 в части «без last»; 6: литералы) |
| (4) убрать `D − last_wave_s` (обе сразу) | REDS 1 и 2 | **1, 2, 9** |
| (5) ключ `last_wave_s` всегда | REDS 6 и `test_stop_budget_child_stop_acceptance` | **3, 6**, `test_stop_budget_child_stop_acceptance.py:187,200,213`, `test_stop_budget.py:59`, `test_process_root_pm_hazards.py:100,106,121` (RED 3 тоже: «ключей ровно 5») |
| (6) «волну по имени читать из `main` для всех» | REDS 9 | неоднозначно — две инъекции: (6а) `stop_wave(name)` всегда `"main"` → красные 1, 2, 9 (одна группа); (6б) `signalled_at(name)` всегда `main`-сборка → только 9. Написать обе |
| (7) `budget_s` без `+ last_wave_s` | REDS 7 | верно **только** для RED 7 в редакции R2-4 (с `last` 2,0 с); в редакции брифа — не красный |
| (8) убрать условие «нет разделения» | REDS 8 | **не красный**: цикл шага 4 запускает `last.request_stop()` при `now ≥ D − last_wave_s`; при `D − now ≤ last_wave_s` это истинно на первом проходе — отдельная ветка избыточна. Инъекция без красных = свойство без break-injection. Решение: убрать ветку и инъекцию (8) из текста, оставить RED 8 как страж; либо определить «нет разделения» по режиму (`_force_at is not None`) отдельной проверкой и тогда инъекция имеет смысл |
| (9) `Any` → `Literal` | REDS 10 | верно (`Literal` бросит `ValidationError` при сборке blueprint) |

Развилка по `force` для лида (R2-5, major): правило «нет разделения» задано порогом `deadline − now ≤ last_wave_s`, а в тексте названо как решение «force не ждёт `main` первым». Но `force` со `deadline_s` из (2,0; 5,0] порог не пересекает: `deadline_s = 3,0` → `last` сигналят на 1,0 с, `main` получает 1,0 с graceful из 3,0. Либо принять порог (записать в ADR-043: «при `force` `main` ждёт `deadline_s − last_wave_s`»), либо ввести проверку по режиму. Рекомендую порог (меньше кода), текст шага 4 тогда: «При `force` отдельной ветки нет: `last` сигналят в `D − last_wave_s`, и при `deadline_s ≤ last_wave_s` это первый проход».

## 5. Остальные замечания (мелкие, `quality`)

**R2-7** (все — правки текста):
- (a) Шаг 7: назвать `_ChildrenStop.signalled_at(name)` (:5004) — звено между `_children_signalled_at(name)` (:1084) и `_ChildrenGroupStop.signalled_at(name=None)` (:735): сегодня оно зовёт `getter()` без аргументов. Имя из `done` (умерло до стопа, запись `exited`): `signalled_at(name)` → сигнал `main` (как сегодня, ADR-042 — «значение остаётся»); имя вне обеих сборок и вне `done` — `None`. Вызов в цикле по именам: `signalled_at = self._children_signalled_at()` стоит ДО цикла (:1034) — перенести внутрь.
- (b) Шаг 6: `_ceiled_budget` при `has_last` обязан пересчитывать всегда — ранний `return base` при `ceiling is None` (:4011-4012) отдаст словарь раннера без `last_wave_s`; записать «`stop_budget(outer, has_last=True)` и без потолка».
- (c) Шаг 3: «`create_and_register` рядом с `_register_stop_window` (:292)» → «в `_create_process` рядом с `_register_stop_window` (:292); снятие — `remove_process` :205 (рядом с `self._stop_windows.pop`)».
- (d) Шаг 6: `has_last` — ровно `any(cfg.get("stop_wave") == "last" ...)` по записям `processes_config`, где `cfg` — словарь с `class`; негодное значение (`late`) волну `last` не создаёт.
- (e) Шаг 4: фаза 3 описана дважды («одна выборка `main` и ожидание `last`» и «общий `join_until`») — оставить одну: «цикл тот же; `last` уже сигналили, `D − now ≤ last_wave_s`».
- (f) Шаг 4: определить `D` («срок области, переданный в `join_until`, после зажима `force`»).
- (g) REDS 1, 2: указать путь (с окнами или без): RED 2 и живой пункт про `name`-kill «в срок (term + `TERMINATE_GRACE_S`)» имеют смысл только на пути с окнами (задать `stop_window_s` у `main`-ребёнка); для пути по умолчанию — вариант «`terminate` `main` на `kill()` области» (R2-3).

## 6. Сверка FILES, пересечения

- FILES: пп. 1–8 достаточны для вариантов без `poll`; при рекомендуемом R2-1 нужен п. 9 `core/child_process_stop.py`. `tests/conftest.py` не нужен (чтение через `getattr`).
- `git status` главного дерева: изменены посторонний `docs/reports/2026-10-26_stage0-eval.md` и `tasks/1.3.md`; новых работ на путях FILES нет. Ветки: `git diff main...<ветка>` по девяти путям (включая `child_process_stop.py`, `spawner.py`, `DECISIONS.md`) — пересечение прежнее и единственное: старая ветка `feat/fc-f2-frontend-entry` (`presentation.yaml`, слияния нет). Worktree с незафиксированными правками на этих путях — нет.
- ADR-PMM-043: другими планами и worktree не занят.

## 7. Что осталось открытым / ненадёжно (раунд 2)

1. Ничего не запускал. R2-1 (терминейт через ~50 мс) — прочтение `child_process_stop.py:293-379` и расчёт: `time.sleep` не возвращает раньше срока, следующий проход видит `now >= term_at`; но живого прогона на пути с окнами нет. R2-2 и R2-3 — арифметика по сроку фаз и порядку вызовов в `lifetime.py:568-654`; сроки фаз, выданные областью (`deadline = start + budget_s`, фаза 3 `until = now + kill_reserve_s`), прочитаны по этим строкам, не по трассе.
2. «Красный до правки» в таблице п. 3 — вывод из чтения кода и описаний тестов. Тексты REDS 1–10 ещё не написаны; если слепой тестер построит RED 6, 7 или 10 иначе, их колонка изменится.
3. Путь по умолчанию (без окон) выведен из `git grep stop_window_s|max_stop_window_s` по `multiprocess_prototype` (0 вхождений вне тестов и `.md`) и из `_group_windows`, `process_registry.py:192-203`. Рецепты вне `multiprocess_prototype` и env-конфиг PM не проверял.
4. Предложенный `poll` (R2-1) — мой дизайн, не прототип: возвращаемый тип и совместимость с `abort`/`idle` (ADR-PMM-037) не проверял прогоном; тесты `ChildProcessStop` (`test_stop_budget_child_stop_acceptance.py` и др.) читал только по `grep`.
5. Слушатель волны (R2-2) вызывается с потока области `children`; ограничение «не бросает, вне лока группы» — требование к исполнителю, проверки взаимных блокировок `_system_stop_lock`/`_system_stop_publish_lock` с `_stop_outcome_lock` не делал.
6. Не проверял, что монитор при рестарте `gui` берёт `stop_wave` из `_process_configs` (TRAPS 1.3 это оставляет исполнителю), и что `ProcessSpawner._processes_config` совпадает по форме с `processes_config` PM (`spawner.py:90` передаёт тот же словарь — вывод из чтения, не из прогона).
7. Вариант (Б) в R2-3 не прорабатывал: оценка «раунд 3 не покроет» — по объёму переписывания шагов 4–5, не по эскалации; эскалация на 3-й итерации — решение лида.
8. Живые пункты ACCEPTANCE (Windows, 5 из 5, замер выхода `gui`, значение `LAST_WAVE_S` 2,0/3,0) не оценивал: ждут стенда. `memory hits:` не запускал; qex не использовал.

---

# Раунд 3 (teamlead): решения

- **Основа:** чтение `child_process_stop.py:269-379`, `process_registry.py:164-203, 523-756`, `lifetime.py:568-654`, `process_module.py:379-399`, `process_manager_process.py:585-640, 935-984, 1020-1120, 4000-4064, 4866-5041`, `spawner.py:200-212`, `design.md:71-197`. Ничего не запускалось. Текст задачи переписан целиком (`tasks/1.3.md`).
- **R2-1 → `poll(deadline)` в `child_process_stop.py` (FILES 9) + публичный `wait(pause)`; `join_until` = цикл `poll` + `_wait`.** Короткий срок ломает не только `term_at` (:345), но и `_kill_at` (:274: `deadline − kill_confirm_s` уходит в прошлое → настоящий `kill` сразу после `kill()` фазы 3). Колбэк `idle` как механизм отвергнут: в фазе 3 вторая сборка ждёт конца первой, её `kill` уходит на `until` без окна подтверждения. Совместимость: `poll` зовёт только `time.monotonic` (`test_child_stop_idle_acceptance.py:115` подменяет `time`), вторая сборка строится только при именах `last` (`test_lifecycle_fifo_hazards.py:335`).
- **R2-2 → слушатель `set_wave_listener(cb)`**, `cb("last", D)` сразу после `last.request_stop()`, вне лока группы; PM подключает его в `_ChildrenStop._start` через `getattr` (сигнатура `children_stop` прежняя, `_GroupProxy.__getattr__` делегирует). `deadline_at = time.time() + max(0, D − monotonic())`, без сдвига при `force` и `done`; помощник PM под `_system_stop_lock`. Свойство `wave` остаётся только для чтения.
- **R2-3 → (А), сигнал `last` по времени** (`D − last_wave_s` или пустой `main`). (Б) требует у `last` своего резерва эскалации после эскалации `main`: `pm_total_s` 11,0 вместо 9,0 — против «+2,0 с» design.md (риск 6); без резерва зависший `gui` остаётся без `terminate`/`kill`. Дополнительно: при `last` обе сборки строятся с окнами по всем именам (как `children_from_g` 1.11) — область длиннее `g`, иначе на пути без окон `terminate` зависшему `main` уходил бы на 7,0 вместо 5,0. Итог: `terminate` `main` на 5,0 и сигнал `last` на 5,0 на любом пути; REDS 2 и живой критерий переписаны без порядка «эскалация `main` → сигнал `last`».
- **Ветка «нет разделения» убрана:** цикл даёт то же при `D − now ≤ last_wave_s`. **`force` в (2,0; 5,0] — пороговое правило принято** (в ADR-043). Поправка к R2-5: `main` не теряет graceful-срок — его `terminate` остаётся на `D`; меняется только то, что `last` сигналят в `D − 2,0`, пока `main` ещё в окне.
- **Тесты:** RED 7 переделан (`main` 4,0 с + `last` 2,0 с через область PM; ловит инъекцию (7)); RED 8 заменён на видимость фазы `last_wave` и сдвиг `deadline_at` (закрывает R2-2; ловит (7) и (10)); `force` 0,5 — в страж С2; RED 6 зовёт `stop_budget(5.0, has_last=False)`; RED 10 утверждает WARNING без `late`. Инъекции: (1), (4), (6a) → 1, 2, 7, 8, 9; (5) → 3, 6 и три набора; (6) разбита на 6a/6b; старая (8) убрана, новая (8) — короткий срок `poll` → 2, 7; добавлена (10) — чтение `wave` после возврата → 8.
- **R2-7:** (a) звено `_ChildrenStop.signalled_at(name)`, сигналы по именам до снимка `system_stop` (порядок :1032-1035 сохранён), имя вне `last` — сигнал `main`, как сегодня; (b) `_ceiled_budget` при `has_last` пересчитывает всегда; (c) запись в `_create_process` :292, снятие в `remove_process` :205; (d) `has_last` — точное выражение `any(... == "last")`; (e) фаза 3 описана один раз; (f) `D` определён (срок вызова после зажима `force`); (g) пути REDS названы: при `last` путь всегда с окнами.
- **Открыто (к лиду):** при (А) вопрос «процесс завис» (design.md C) для ребёнка с окном `g` совпадает по времени с сигналом `gui` (оба на 5,0): окно GUI гаснет, не задав вопроса. Для детей с окном < `g` время на вопрос есть (`g − окно`). Это сужает решение владельца 7. В задаче не правится; вопрос — в отчёте лиду.
