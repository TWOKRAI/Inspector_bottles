# Task 1.3 — код-ревью, стадия 5, раунд 1 из 2

Ветка `feat/gui-close-1.3`, коммиты `016fb61e6` (реализация), `10c1a168e` (стражи), `d44a619af` (слепые тесты).
Ревьюер: reviewer (opus). Код не правился, не коммитился.

## Вердикт: CHANGES REQUESTED

Находок: blocker 0, major 2, minor 8. Блокеров нет. Два major — одна правка в `_join_waves` (M1) и дописать
тесты на явные требования DESIGN (M2). Остальное — минор и документация.

## Что прогнано (воспроизведение)

Все прогоны — гейт `machine_gate.sh medium|light op-1.3`, `.venv/bin/python -m pytest -q`, `PYTHONPATH` = корень worktree.

| набор | итог |
|---|---|
| `test_stop_wave_last.py` + `test_stop_wave_last_guards.py` | 19 passed (34 с) |
| 10 соседних файлов, которые исполнитель не гонял (`test_blueprint_pick_nan_*`, `test_blueprint_extras`, `test_protected_propagation`, `test_boot_depends_on`, `test_t47c_blueprint_wiring`, `test_config_converters*`, `test_root_stop_outcome_*`) | 131 passed |
| 16 файлов: `test_lifecycle_command_classes`, `test_lifecycle_fifo_acceptance`, `test_no_orphans_*`, `test_pm_stop_drains_own_queue_acceptance`, `test_process_root_{acceptance,hazards,pm_acceptance}`, `test_stop_outcome_acceptance`, `test_stop_summary_hazards`, `test_stop_wait_idle_hazards`, `test_system_shutdown_force{,_author}`, `test_process_manager_process`, `test_plugin_stop_request_*` | 192 passed (165 с) |

Скретч-пробы лежат вне репозитория: `/private/tmp/claude-501/-Users-twokrai-Project-code-Inspector-bottles/bc222eb2-debb-4a30-8f5f-ca723e7ac548/scratchpad/{leak,e1,p3}.py`.
Инъекции лида (1)–(11) не повторялись. Новых инъекций в дерево не клал.

## Соответствие DESIGN (шаги 1–11)

| шаг | итог |
|---|---|
| 1 поле `stop_wave: Any`, путь до `proc_dict`, `main`/`None` не кладутся, WARNING реестра без значения | выполнен; дыра в `_pick` — m1 |
| 2 `presentation.yaml` | выполнен (REDS 5 читает настоящий файл) |
| 3 `_stop_waves`, `stop_wave(name)`, делегат PM через `getattr` + `isinstance(str)` | выполнен; пара `_stop_windows`/`_stop_waves` в `_create_process`/`remove_process` симметрична |
| 4 `poll`/`wait`, `join_until` через них, в `poll` только `time.monotonic` | выполнен; порядок проверок и пауза те же |
| 5 две сборки, `all_windows=True`, цикл, `wave`, `kill`/`close`/`result`/`signalled_at` | выполнен; пробел наблюдения — M1; крайний случай — m2 |
| 6 `stop_budget(has_last)`, шестой ключ последним, `pm_total_s` до `outer_s`, `budget_s` области | выполнен (литералы 7,0/8,5 и 9,0/10,5; область 7,0/5,0) |
| 7 `has_last` один раз в `__init__` PM и в `spawner.stop()`; `_ceiled_budget` не отдаёт `base` при `has_last` | выполнен |
| 8 слушатель вне лока, сдвиг `deadline_at` под `_system_stop_lock`, `signalled_at(name)` до снимка | выполнен; нет тестов на ветки — M2 |
| 9 ADR-PMM-043, строки в 031 и 042 | выполнены; в ADR нет двух ограничений — m2, M1 |
| 10 `LAST_WAVE_S` в одном месте | выполнен |

Отклонения исполнителя оцениваю так.
- `has_last_wave()` в `stop_budget.py`: принимаю. Одно выражение вместо двух копий, не бросает, добавлено в `__all__`.
- Область `children` берёт `last_wave_s` из словаря бюджета: принимаю. В настоящем PM словарь пересчитывает `_ceiled_budget` (страж С-корень читает `budget_s` открытой области: 7,0 / 5,0). В `WaveRig` словарь приходит через `attach_stop_budget`. Оба пути дают одно число, но сшивает их только пара тестов (см. «Что осталось открытым»).
- Страж С2 на уровне реестра: принимаю с оговоркой. Проверен срок группы 0,5 с; путь `system.shutdown` → `_escalate_system_stop` → `set_force_deadline` → `min(deadline, force_at)` не менялся.

## Правка лида в `test_stop_wave_last.py` (ячейка kill, REDS 2)

Оценка: отклонение от слепого теста законное, но запись о нём слабая.
- ACCEPTANCE REDS 2 требует `stop_event` `last` в [5,0; 5,1] в обеих ячейках. Старый слепой текст требовал `last.t_signal >= main.t_dead` и в ячейке kill (kill `main` в 6,0) давал красное при варианте (А). Правка снимает противоречие и приводит тест к DESIGN шаг 5.
- Сильнее ли стала проверка: диапазон [5,0; 5,1] теперь действует в обеих ячейках (был только в ячейке без kill); в ячейке kill стоит `last.t_signal < main.t_dead`. Эта строка дублирует страж С4 (`test_last_signalled_by_time_before_main_kill`).
- Слабость: докстринг теста (строки 238–240) всё ещё говорит «`stop_event` `last` сразу после его смерти» — устарел (m4).

## Находки

### Major

**M1. [process_registry.py:807–832 `_join_waves`] [IPC] Смерть ребёнка волны `last` в основной волне не наблюдается до сигнала `last`: метка ReaderGone и итог запаздывают до 5 с.**
- Вход: `worker` (main) выходит через 3,0 с после сигнала; `gui` (last) гибнет сам на 0,5 с; `children_stop(mark_reader_gone=True)`, `join_until(t0 + 7,0)`.
- Наблюдаемо (`scratchpad/e1.py`): `marks (s from start): {'worker': 3.04, 'gui': 3.04}`. Метка `gui` — на 3,04 с, момент сигнала `last`, а не на 0,5 с. До 1.3 одна группа метила его на ≈0,55 с.
- Причина: пока `last` не сигналили, цикл его не опрашивает (нельзя звать `poll`: `_name_escalate` считает `term_at` от `_stop_requested_at`, а до `request_stop` это время создания сборки).
- Следствие: DESIGN шаг 5 «метка ReaderGone — как сейчас, по воплощению» и принцип Task 1.1 (О2: смерть соседа и её метка видны сразу) нарушены для `last`. Писатели в очередь мёртвого GUI не знают об этом до конца основной волны. Тяжесть для писателей зависит от их политики `put` (блокирует ли на полной очереди) — я не проверял.
- Правка: в `_join_waves`, пока `not self._last_signalled`, звать на `last` наблюдение без сигналов и без эскалации. Готовый публичный метод — `last.survivors()` (один `_observe()`, сигналов не шлёт); либо добавить `ChildProcessStop.observe()`. Вызывать на каждом проходе цикла рядом с `main.poll`. Тест: `gui` гибнет на 0,5 с при `main` 3,0 с — метка и итог `exited` до сигнала `last`.

**M2. [test_stop_wave_last*.py] [tests] Явные требования DESIGN без единого теста.**
Не покрыто ни слепым набором, ни стражами; мутант остаётся зелёным (предсказание по чтению кода, в дерево не вносил):
1. Шаг 8: сдвиг `deadline_at` не делается при `mode == "force"` и при `phase == "done"` (`process_manager_process.py:636–648`, условие `info["phase"] == "done" or info["mode"] == "force"`). Снять условие — все тесты зелёные.
2. Шаг 8: исключение слушателя — ERROR в лог, стоп идёт (`process_registry.py:849–853`). Теста с падающим слушателем нет. То же для `_on_last_wave`, когда `_shift_system_stop_deadline` бросает.
3. Шаг 5: `survived` для сборки `last` в снимке после `kill()` (`process_registry.py:798–803`, цикл `for build in (group, last)` на :800). Нет теста с `last`, переживающим `kill`; заменить кортеж на `(group,)` — зелёное.
4. Шаг 5: `kill()` группы зовёт `self._last.kill()` только после сигнала (`:854–859`). Сценарий «зависший `last`» (мои пробы B и C ниже) ни в одном тесте не идёт; без `self._last.kill()` сценарий C тоже зелёный (`last` получит `terminate` и `kill` от окна имени), значит ветка либо мёртвая, либо не защищена.
5. Шаг 8: `set_wave_listener(None)` и поведение при повторном `join_until` (фаза 3) — слушатель не зовётся второй раз (`_last_signalled` защищает) — не проверено.
- Пробы вручную (не коммитить как тесты): `scratchpad/p3.py B` — `worker` выходит на 0,52 с, `gui` игнорирует всё: сигнал 0,55 / `terminate` 5,55 / `kill` 6,55, корень закрылся за 6,71 с, итог `killed`. `p3.py C` — оба игнорируют `terminate`: `worker` терминирован 5,01, убит 6,01; `gui` сигнал 5,01, `terminate` 7,01, `kill` 8,01, корень закрылся за 8,17 с (< `pm_total_s` 9,0). Цепочка работает; защиты тестами нет.
- Правка: добавить авторские тесты в `test_stop_wave_last_guards.py` — (а) зависший `last` (игнорирует `stop_event`/`terminate`): `terminate`/`kill` в окнах, итог `killed`, корень в 9,0; (б) падающий слушатель: стоп идёт, ERROR в логе; (в) `_shift_system_stop_deadline` при `force` и после `done` — `deadline_at` не меняется; (г) `last`, переживший `kill`, — `survived`.

### Minor

**m1. [blueprint.py:339–345 `_pick`, process_manager_module] [spec] Значение `stop_wave` попадает в WARNING `_pick` при конфликте typed/extras.**
- Вход: `ProcessConfig(process_name="p", process_class="m.C", stop_wave="late", extras={"stop_wave": "x"}).as_generic_config()`.
- Наблюдаемо (`scratchpad/leak.py`): `["ProcessConfig[p]: typed-поле 'stop_wave'='late' перекрывает extras['stop_wave']='x' (typed-приоритет)."]`.
- DESIGN шаг 1/TRAPS: «тексты WARNING без значения поля». Общий механизм `_pick` старый (так же ведёт `stop_window_s`), исполнитель его заметил и не менял, но слепой REDS 10 этот путь не проходит. Правка: для ключей `STOP_WAVE_KEY` (и `STOP_WINDOW_KEY`) писать в WARNING только имя ключа, без `!r` значений; тест на этот путь.
- Побочный факт: сырое значение доходит до `proc_dict` как есть (`" Last "` → `" Last "`, `["last"]` → `['last']`); реестр отвергнет и пошлёт WARNING без значения — как задумано.

**m2. [process_registry.py:765–771 `request_stop`, else-ветка (:767)] [architecture] `has_last`, но живых `last`-имён при стопе нет и самого `last` нет в реестре: прежний путь без окон, область 7,0 вместо 5,0.**
- Вход: `WaveRig(5.0)` с бюджетом `has_last=True`, один зависший `main` без ключа окна (`gui` в реестре нет), `stop_event`.
- Наблюдаемо (`scratchpad/p3.py A`): `hung: terminate=7.02, kill=None, dead=7.02, outcome=terminated`. До 1.3 `terminate` шёл на 5,0. `deadline_at` в `supervision.status` и `stop_deadline_at` главного имени остаются на 5,0 (занижены на 2,0 с).
- Если `gui` в реестре, но мёртв, срабатывает `all_windows=True` и `terminate` идёт на 5,0 — исполнитель описал верно.
- Это ограничение, а не дефект кода (`has_last` по DESIGN считается один раз). В ADR-PMM-043 «Известные ограничения» его нет. Правка: дописать пункт в ADR; при желании — в else-ветке брать `all_windows=True`, если в `_stop_waves` есть хоть одно значение `last`.

**m3. [test_stop_wave_last_guards.py:177–204] [tests] Страж С5 не различает зажим `deadline − kill_confirm_s` (инъекция (11) осталась зелёной, исполнитель это признал).** При `until = t_kill + 2,0` оба варианта дают kill на +1,0 с. Правка: второй параметр `until = t_kill + 1,5` — kill ожидается на +0,5 с.

**m4. [test_stop_wave_last.py:238–240, 202–203] [quality] Докстринги REDS 2 и модульный текст описывают порядок «`last` сразу после смерти `main`» — устарели после правки лида.** Привести к варианту (А): «`stop_event` `last` в [5,0; 5,1]; после смерти `main` без kill, до смерти — с kill».

**m5. [process_registry.py: `_last_names: List[str]`, `pauses: List[float]`, `_register_stop_wave(..., Dict[str, Any])`] [quality] Новый код использует `typing.List`/`Dict`; правило проекта — `list[...]`/`dict[...]` в новых строках.** Остальной файл не трогать.

**m6. [module README.md ~стр. 542, STATUS.md] [quality] README не описывает ключ `stop_wave`, волну `last` и то, что `system_stop.deadline_at` в фазе `last_wave` сдвигается на срок области.** Контракт модуля — public-api-change; строка в README «Public API/Boundaries» и фраза про `deadline_at` нужны (файл вне FILES задачи — решение лида/tech-writer).

**m7. [process_manager_process.py:1119–1129, 5072–5078] [quality] Откат `except TypeError: getter()` скроет настоящий `TypeError` внутри геттера, который принимает `name`: повторный вызов без аргумента вернёт другой ответ.** Теоретически; на коде сегодня `TypeError` внутри `_ChildrenGroupStop.signalled_at` невозможен. Если двойникам нужен откат, проверять сигнатуру (`inspect.signature`) один раз, а не ловить `TypeError`.

**m8. [process_registry.py:209–219 `_register_stop_wave`] [IPC] `pop` перед `set` не атомарен: читатель `stop_wave(name)` в этот момент получит `main`.** Окно микросекунды, но пересоздание `gui` (рестарт, `topology.apply`) идёт на потоке исполнителя, а группа читает в `request_stop`. Правка: убрать `pop`, присваивать сразу. Тот же шаблон у `_register_stop_window` (старый код).

## Проверки без находок

- Конкуренция. `_signal_last` ставит флаг под `self._lock`, зовёт `request_stop`, лог и слушатель вне лока; слушатель берёт `_system_stop_lock` только внутри `_shift_system_stop_deadline`/`_set_system_stop_phase` — взаимной блокировки нет. `kill()`/`close()`/`join_until` фазы 3 идут с одного потока области (`lifetime._phase3`), поэтому гонки «флаг есть, `request_stop` ещё нет» между `kill()` и `_signal_last` не будет. Ранг итогов и `_stop_outcome_lock` не тронуты; `_confirm` в сборках `ChildProcessStop` прежний: метка, затем итог.
- Умерший до стопа ребёнок: `done` объединяется, итог `exited` пишется в `request_stop`; ветка `last` с `last = None` (все мертвы) идёт прежним путём.
- Порядок проверок `supervision.status`: `signalled` читается до `_system_stop_snapshot()`; набор имён один на оба прохода. Видимая фаза `last_wave` всегда идёт после того, как `signalled_at(gui)` стал числом (сигнал → лог → слушатель).
- Бюджет: `stop_budget(5.0)` — пять ключей, 3,0/1,0/5,0/7,0/8,5; `has_last=True` — шесть, 9,0/10,5, `last_wave_s` последний. Ребёнку `last_wave_s` не уходит (`child_stop_budget` в PM остаётся пятиключевым). `_ceiled_budget` при `has_last` не отдаёт `base`.
- Слои: `blueprint.py`/`process_registry.py` импортируют из `core/stop_budget.py` того же пакета; `process_launch_config.py` — литерал (обратной зависимости нет); обратных импортов framework → prototype в коде нет (тест REDS 5 читает prototype, как другие framework-тесты). `sentrux check .` не запускался — граница проверена чтением и grep.
- Двойники в существующих тестах читаются через `getattr`; сигнатура `children_stop` не менялась; `test_child_stop_idle_acceptance` (подмена `time`) зелёный.
- Утечка приватного: публичные имена `poll`, `wait`, `wave`, `set_wave_listener`, `signalled_at(name)`, `stop_wave(name)`, `has_last_wave`; остальное с подчёркиванием.

## Что осталось открытым / ненадёжно

- Живой пункт ACCEPTANCE (GUI-стенд: exitcode `gui` 0 пять из пяти, строки лога «волна last» и «окно скрыто», замер штатного выхода `gui` для `LAST_WAVE_S`) не выполнялся; я его не проверял.
- Нет одного сквозного теста с настоящей проводкой: `processes_config` → `_has_last` → `_ceiled_budget` → реальный стоп с таймингами. REDS 7/8/9 идут через `WaveRig`, где бюджет с `last_wave_s` ставит `attach_stop_budget`, а `_has_last` у PM `False`. Звенья (число области, сигнал по времени, фазы) каждое защищено, склейки одним тестом нет (правило 9 «fake-harness suite needs one test that wires the real objects»). Не блокирую, но рекомендую.
- Тесты привязаны ко времени (допуски ±0,1 с, двойник опрашивает событие каждые 2 мс). На общей машине при загрузке возможна флакость; у меня три прогона зелёные.
- Не проверено: сочетание потолка окон `C > g` с `has_last` (в тестах нет); поведение писателей в очередь мёртвого GUI (M1); `sentrux check .`; свежесть индекса qex не смотрел (поиск — Grep/Read).
- Реестр `_stop_waves` при ошибке посреди `_create_process` оставляет запись до `remove_process` — так же, как `_stop_windows` (не новое).
- Цель задачи («свое окно `last_wave_s` до `terminate`») на деле: поздний сигнал (в `D − 2,0`) даёт `last` окно 2,0 с до `terminate` (= `D`); ранний сигнал (когда `main` пуст раньше) даёт окно `g` (проба B: сигнал 0,55 → `terminate` 5,55). Это DESIGN шаг 5 (`min(сигнал + g, D)`), но формулировка Goal в задаче этого не говорит.

---

# Раунд 2 из 2

HEAD `0987ba9fd` (правки `3b4e4caf1` + автоформат). Смотрел `git diff 10c1a168e..HEAD`. Код не правил, не коммитил.

## Вердикт: APPROVED

Блокеров и major нет. Все пункты r1 закрыты, кроме m1 (оставлена по решению лида). Новых дефектов выше minor не найдено;
два новых nit записаны ниже (n1, n2).

## Закрытие пунктов r1

| пункт | итог | чем проверено |
|---|---|---|
| M1 | закрыт | `_join_waves` зовёт `last.survivors()` до сигнала (process_registry.py:822–826). Скретч `scratchpad/e2.py` (E1): `gui` гибнет на 0,5 с — `marks={'gui': 0.55, 'worker': 3.04}` (в r1 было 3,04); `gui`: signal=None, term=None, kill=None, итог `exited`. Тест `test_last_child_death_during_main_wave_marked_at_once` проверяет эффект (метка в [0,5; 0,7], 0 `terminate`/`kill`, `stop_event` мёртвому не взведён, сигнал волны ≥ 3,0 с), а не шпиона. |
| M2 (а)–(д) | закрыт | Все пять тестов есть и проверяют наблюдаемый эффект. (а) `deadline_at` не меняется при `force`/`done`, а при graceful уезжает на ≥ 50 с. (б) слушатель бросает — ERROR «слушатель волны last», итог `exited`; сбой сдвига PM — фаза `last_wave`. (в) бессмертный `gui` — итог `survived`. (г) `kill()` до сигнала — `last` не тронут; после — `terminate` в [1,0; 1,2]. (д) зависший `last` через область PM — `terminate` ≈ 5,0 после сигнала, `kill` ≈ +1,0, `killed`, корень < 9,0 (мои пробы B/C r1 дают те же числа). Инъекции лида раунда 3 совпали с предсказаниями; я их не повторял. |
| m2 | закрыт | ADR-PMM-043, «Известные ограничения»: текст совпадает с моей пробой A (`terminate` главного на 7,02 с, `deadline_at`/`stop_deadline_at` занижены на 2,0 с; мёртвое имя `last` в реестре — `all_windows`, 5,0). |
| m3 | закрыт | С5 параметризован `until` 2,0 / 1,5; ожидание kill на 1,0 и 0,5. Инъекция (m3) лида красная на С5[1,5] и на acc-тесте. |
| m4 | закрыт | В `test_stop_wave_last.py` изменён только докстринг REDS 2 (7 строк, `git diff`); ассерты не тронуты. |
| m5 | закрыт | `list[...]`/`dict[...]` в новых строках (`_stop_waves`, `_last_names`, `pauses`, `_register_stop_wave`). `ruff check` чисто, `ruff format --check` по 4 файлам — без правок. |
| m6 | закрыт с nit | README модуля описывает `stop_wave`, две волны, `has_last`, фазу `last_wave`, сдвиг `deadline_at`, `stop_deadline_at` имени `last`; текст совпадает с кодом. Nit n2 ниже. |
| m7 | закрыт | `_takes_argument` (inspect.signature до вызова). Проба `scratchpad/ta.py`: двойники `signalled_at(self)` → зовутся без аргумента, `signalled_at(self, name=None)` / `*a, **k` / `MagicMock` → с аргументом, kw-only → без аргумента; настоящий `TypeError` внутри геттера теперь не маскируется (WARNING «signalled_at() упал: real bug», ответ `None`). |
| m8 | закрыт | `_register_stop_wave` пишет одной записью, без `pop`. |
| m1 | оставлена по решению лида | Общий механизм `_pick` (так же ведёт `stop_window_s`), вне задачи. Условие закрытия: запись в `docs/claude/OPEN_QUESTIONS.md`. Её в дереве `op-1.3` пока нет (`git grep "_pick" docs/claude/OPEN_QUESTIONS.md` пусто) — проверить при слиянии. |

## Проверка новых дефектов

- `last.survivors()` до сигнала не эскалирует: `survivors()` = `_observe()` (опрос `is_alive`, `_confirm` только для мёртвых) + кортеж имён; сигналов нет. Скретч E2/E3: живой `gui` при `main` 3,0 с получает `stop_event` на 3,01 с, `terminate`/`kill` нет; при зависшем `main` — сигнал на 5,01 с (правило `D − 2,0` сохранилось), `main` терминирован на 5,01. Лишних меток нет: метятся только умершие, ровно по разу (`_dead`), порядок «метка, затем итог» прежний. Лок только сборки `last`, не лок группы: взаимной блокировки с `_signal_last` нет.
- E4 (все `last` умерли до сигнала, `main` 2,0 с): метка `gui` на 0,54 с, `gui` сигнал/`terminate`/`kill` — нет, итог `exited`, `ok=True`.
- Стоимость: до сигнала один дополнительный `is_alive()` на каждого `last`-ребёнка на проход (≤ 20 раз в с).
- `_takes_argument` двойники не ломает: 20 файлов соседних наборов с двойниками `children_stop`/реестра/`signalled_at` — 290 passed, 1 xfailed (`test_child_process_stop`, `test_child_stop_idle_acceptance`, `test_lifecycle_fifo_hazards`, `test_per_child_stop_window_*`, `test_pm_responsive_during_children_stop`, `test_process_root_pm_hazards`, `test_process_spawner`, `test_stop_budget*`, `test_supervision_status_system_stop*`, `test_root_stop_outcome_*`, `test_system_shutdown_force*`, `test_process_root_pm_acceptance`, `test_stop_outcome_acceptance`, `test_blueprint_pick_nan_*`).
- Волновые файлы на HEAD: `test_stop_wave_last.py` + `test_stop_wave_last_guards.py` — 27 passed.
- `test_cv_threads.py`: на HEAD 6 failed / 9 passed; на чистом `009e35f86` (извлечён `git archive` в `scratchpad/base009`, запуск из него) те же шесть (`test_recipe_value_four_is_applied_in_child`, `test_default_is_two_when_key_absent`, `test_threads_set_before_process_class_init`, `test_top_level_key_is_fallback_for_flat_configs`, `test_recipe_to_child_chain_via_real_build`, `test_introspect_status_reports_effective_cv_threads`; в ассерте `cv_threads: 12`, `init: 12`). Красные не наши.
- Флейк (д): объяснение исполнителя («гипотеза не доказана») я разбираю арифметикой. Двойник замечает `stop_event` опросом до 2 мс позже `request_stop`, а `terminate` уходит от момента `request_stop` + 5,0: разность `t_terminate − t_signal` = 5,0 − (до 2 мс) < 5,0. Старая нижняя граница 5,0 была ложным красным по построению; граница 4,95 это закрывает. Аналогично `kill`: `kill_at = now + 1,0`, а `t_kill` пишется позже `now`, но `t_kill − t_terminate` измеряется от `terminate()`, который тоже идёт после `now` — граница 0,95 допускает этот сдвиг.

## Новые замечания (minor, не блокируют)

- **n1. [process_registry.py `_signal_last`, `_last_names`]** Если `last`-ребёнок умер до сигнала (E1/E4), строка INFO «stop: волна last — сигнал: [gui]» всё равно называет его, а слушатель объявляет фазу `last_wave`, хотя сигналить уже некому. Имена в строке — снимок `request_stop`, не живые на момент сигнала. Безвредно (`stop_event` мёртвому не взводится: `request_stop` пропускает мёртвых). Правка по желанию: брать для лога `last.survivors()` в момент сигнала.
- **n2. [README.md модуля, абзац «Волны стопа», перенос строки]** Строка начинается с `+ 2,0 с, область…` (перенос после `` `pm_total_s`/`outer_s` ``). В Markdown `+ ` в начале строки превращает остаток абзаца в маркированный список. Правка: перенести перенос так, чтобы строка не начиналась с `+`.

## Что осталось открытым / ненадёжно

- Живой пункт ACCEPTANCE (GUI-стенд, 5 из 5 `exitcode` 0, замер штатного выхода `gui` для `LAST_WAVE_S`) не выполнялся ни исполнителем, ни мной. Число `LAST_WAVE_S = 2,0` по-прежнему не подкреплено замером.
- Нет одного сквозного теста «`processes_config` → `_has_last` → реальный стоп с таймингами»: звенья защищены порознь (страж С-корень читает `budget_s` открытой области; REDS 7/8/9 идут через `WaveRig` с `attach_stop_budget`). Не блокирую.
- Тесты привязаны ко времени (верхние границы 5,1 / 1,1 / 0,7 и 4,95…5,1 в (д)). На загруженной общей машине возможны ложные красные сверху; у меня два прогона обоих файлов зелёные (27 passed, 19 passed в r1), у исполнителя 13 прогонов (д) без падений.
- Инъекции раундов 1–3 лида я не повторял и новых в дерево не клал; их результаты принимаю из отчёта исполнителя (`docs/reviews/2026-11-08_task-1.3-teamlead.md`) и сверил с составом тестов, но не воспроизводил.
- `sentrux check .` не запускался (границы слоёв проверены чтением: framework → framework, обратных импортов в prototype нет).
- Тяжесть M1 для писателей в очередь мёртвого GUI (блокирует ли `put`) я так и не проверил: исправление закрывает метку независимо от этого.
- m1 (значение `stop_wave` в WARNING `_pick` при конфликте typed/extras) остаётся в коде; закрытие — запись в OPEN_QUESTIONS (в дереве её пока нет).
- Сочетание потолка окон `C > g` с `has_last` по-прежнему не покрыто тестами.
