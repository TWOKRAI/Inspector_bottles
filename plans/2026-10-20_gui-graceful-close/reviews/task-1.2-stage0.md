# Ревью стадии 0 — Task 1.2 (итог по процессам на пути корня)

- **Режим:** `MODE: plan` на одном файле задачи `plans/2026-10-20_gui-graceful-close/tasks/1.2.md`; reviewer, раунд 1 из 2.
- **Дерево:** `main` = `a5eb6d382` (1.2a влита: merge `7465a5d4e`, код `38333f9fc`). Чтение и `git grep`, ничего не запускалось.
- **Вердикт: CHANGES REQUESTED** (12 пунктов: 5 блокеров `spec`, 4 `architecture`/`tests`, 3 `quality`).

## 1. Чек-лист (для файла задачи: a, d, f, i, ii, iii)

| Пункт | Ответ | Где |
|---|---|---|
| (a) приёмка несёт команду/литерал | частично | ACCEPTANCE: у пунктов 2 и 3 есть команда; у `stop_deadline_at` и `stop_wave` в пробе числа нет (п. 11) |
| (d) `Module contract`, `Handoff`, `Gate`, `Dependencies` заполнены | да | шапка; строку `Handoff` обновить (п. 12) |
| (f) `OUT OF SCOPE` не пуст и не повтор `Goal` | да | F1 в нём не назван (п. 9) |
| (i) у каждого решения DESIGN есть причина | нет | шаг 4: «PM фиксирует… либо геттер» — выбор не сделан (п. 5) |
| (ii) решение не ломает инвариант модуля | нет | шаг 1 (лок), шаг 2 (`_stop_many`), правило «стоп = не `null`» (пп. 1, 2, 3) |
| (iii) тексты ошибок без входных значений | да | новые WARNING несут только имя процесса |

## 2. Якоря: пересчитано по `main` `a5eb6d382`

| В брифе | Сейчас | Примечание |
|---|---|---|
| `process_manager_process.py:894` (`stop_outcome` на записи) | **:1055** | запись процесса — :1045–1056; `_cmd_supervision_status` — :1000–1065 |
| (1.2a) `_cmd_supervision_status` :839–896 | **:1000–1065** | `system_stop` берётся ПОСЛЕ цикла по процессам (:1057–1065) — см. п. 6 |
| `_cmd_system_shutdown` (design: :666–680; 1.2a: :773) | **:919–987** | |
| `_ChildrenStop` (1.2a: :4631) | **:4807–4968** | `request_stop` :4855, `set_force_deadline` :4906, `join_until` :4915, `kill` :4941, `close` :4947; ветка F1 — **:4927–4928** |
| `_system_window_s()` «(:131)» | **`process_registry.py:131`** (метод реестра, не PM) | якорь верен, файл в брифе не назван |
| `child_process_stop.py:100,175` | :100, :175 — **не сдвинулись** | `_stop_requested_at` — `time.monotonic()` |
| `process_registry.py:638-700` | **:638–709** (`result()` :696–709) | |
| `process_registry.py:593` (`_stop_outcomes`) | :593 — не сдвинулся | рядом :594 — канал вызова `_stop_call.outcomes`, его трогать нельзя |
| `DECISIONS.md:2056` | :2056 — не сдвинулся | строка «Не входит… стоп корня (`_ChildrenGroupStop` `stop_outcome` не пишет)» |
| `backend_ctl/AGENTS.md:145-147` | :145 (`supervision_status`), :147 (`system_shutdown`) — не сдвинулись | файл вне FILES, как задумано (Task 1.4) |
| ADR-PMM-042 | **свободен**: `git grep ADR-PMM-042` в коде и `DECISIONS.md` — 0; последний — ADR-PMM-041 (:2169–2230) | ADR-PMM-042 дописать ПОСЛЕ :2230 |
| Новые, нужные брифу | `_build_child_stop` :499–549 (конструктор :540); `children_stop` :551; `_stop_many` :560–605; `add_process` :106–111; `stop_outcome` :113; `_stop_outcomes` :88; `MockProcessRegistry` `tests/conftest.py:73` (`stop_outcome` :92) | |

## 3. Находки

**1. [`child_process_stop.py:144-156`] [spec] Шаг 1 расходится с кодом: колбэк «под уже взятым локом» невозможен, а вставка после `callback is None: return` теряет итог.**
`_confirm` держит `self._lock` только на `if name in self._dead` / `self._dead.add(name)`; метка `on_confirmed_dead` вызывается ПОСЛЕ выхода из лока (:150-156). Лок — `threading.Lock()` (не реентерабельный, :93). Колбэк под ним блокирует `kill()` (:218, :224) и `_pending()`, а любой вызов `outcomes()`/`survivors()` из колбэка — самоблокировка. Второе: ранний `return` на :151-152 (`if callback is None: return`) срабатывает при `mark_reader_gone=False` (путь рестарта, тесты `children_stop(mark_reader_gone=False)`), и `on_outcome` после него не вызвался бы никогда.
Вход → выход: `ChildProcessStop(..., on_confirmed_dead=None, on_outcome=cb)`, ребёнок умер → `cb` не вызван.
Замена шага 1 (текст в DESIGN): «`_confirm`: итог считается ВНУТРИ существующего `with self._lock:` после `self._dead.add(name)` — `"killed" if name in self._killed else "terminated" if name in self._terminated else "exited"` (множества пишутся под тем же локом: :235, :259, :336, :346). Метка и колбэк зовутся ПОСЛЕ выхода из лока, без раннего `return`: сначала `on_confirmed_dead` (если задан), затем `on_outcome(name, outcome)` (если задан), каждый в своём `try/except Exception` с `self._emit("warning", …)`. Порядок «метка → итог» нужен, чтобы `stop_outcome != null` означал: метка читателя уже стоит (ADR-PMM-030, «True ⇒ метка»). Добавить kwarg `on_outcome` в `__init__` (:54-67), строку в docstring «Public API» (:12-14) и в «Инварианты» (:16-24): «`on_outcome` — не более одного вызова на имя».»

**2. [`process_registry.py:106-115`, :593] [architecture] Шаг 2: «два писателя» без атомарности и без порядка между подтверждёнными итогами.**
(а) Правило «`handed_over`/`survived` не перезаписывают подтверждённый» — это «прочитать-сравнить-записать». Писателей два потока (исполнитель `_stop_many` и поток области корня), чтение «dict-get под GIL» (D3 1.10) покрывает только читателя. Вход → выход: писатель A читает пусто, писатель B пишет `terminated`, A пишет `handed_over` → в реестре `handed_over` поверх `terminated`. Нужен листовой лок ТОЛЬКО на сравнение-и-запись (`self._stop_outcome_lock = threading.Lock()` в `__init__` реестра рядом с :88); читатель `stop_outcome()` остаётся без лока.
(б) Правило не говорит, кто выигрывает между двумя подтверждёнными. Реально: исполнитель прерван системным стопом, но его объект `ChildProcessStop` в `outcomes()` (:383) вызывает `_observe()`; если ребёнка к этому моменту убил `terminate()` группы корня, объект исполнителя сам подтверждает смерть и считает `exited` (он сигнала не слал, `child_process_stop.py:106-107`). Последний писатель выигрывает: `exited` поверх `terminated`. Это ложь «как умер».
Замена шага 2 (правило): «Ранг: `handed_over` 1 < `survived` 2 < `exited` 3 < `terminated` 4 < `killed` 5. `_record_stop_outcome(name, outcome)` под `_stop_outcome_lock` пишет, только если ранг нового ≥ ранга сохранённого (нет записи — ранг 0). Следствия: неподтверждённый не затирает подтверждённый; `survived` затирает `handed_over`; подтверждённый затирает неподтверждённый; из двух подтверждённых остаётся более «сигнальный».» `add_process` по-прежнему делает `pop` (без лока достаточно: спавн на системном стопе отвергнут, см. п. 10).

**3. [`process_registry.py:499-549`, :590-595] [architecture] Шаг 2: «путь `children` (`_build_child_stop`)» — этот метод общий с `_stop_many`.**
Конструктор `ChildProcessStop` один (:540). Передав `on_outcome` там, получишь запись посреди стопа и на пути одиночного `process.stop` (ADR-PMM-039, 1.10) — в брифе это названо «правило действует и для `_stop_many`», но сама передача не оговорена. Замена: «`on_outcome=self._record_stop_outcome` передаётся в конструктор в `_build_child_stop` (:540) для обоих путей (при любом `mark_reader_gone`). Цикл :591-595 `_stop_many` остаётся, но запись в `_stop_outcomes` идёт через `_record_stop_outcome` (так `handed_over`/`survived` получают правило); строка :594 (`self._stop_call.outcomes[name] = outcome`, канал ответа вызова) — БЕЗ правила, как есть: это итог ЭТОГО вызова, не состояние воплощения.» Проверить прогоном стража: тесты 1.10 (`test_stop_outcome_acceptance.py`) не должны требовать `None` посреди одиночного стопа (я читал их только по `grep`).

**4. [`process_registry.py:638-709`] [spec] Правило потребителя «все остановлены = `stop_outcome` не `null`» неверно для ребёнка, умершего ДО стопа.**
`_build_child_stop` для уже мёртвого (:528-532) отдаёт `result[name] = True` и ставит метку, но итог не пишет; в группу такой не попадает. Вход → выход: ребёнок упал до закрытия окна (рестарт исчерпан) → `alive=false`, `stop_outcome=null` до самого `done`, GUI (Task 2.1) «все остановлены» не дождётся и покажет «не подтверждено». Строка таблицы ADR-PMM-039 «процесс уже мёртв → `None`» относится к ОТВЕТУ `process.stop` (канал вызова) и не противоречит.
Нужно решение лида (расширяет контракт): рекомендую писать `exited` для имён из `done` в `_ChildrenGroupStop.request_stop` (:667-673): после `self._done, self._group = done, group` — `for name in done: if self._registry.get_process_by_name(name) is not None: self._registry._record_stop_outcome(name, "exited")` (ранг защищает прежний `terminated` от одиночного стопа). Плюс RED `A::test_child_dead_before_root_stop_shows_exited` и строка в ADR-042: «`exited` = умер без нашего сигнала, включая упавшего до стопа». Если решение «не писать» — тогда в ADR и в `design.md` («Контракт хода», правило потребителя) заменить правило на «`alive == false` ИЛИ `stop_outcome` не `null`» и убрать довод про окно ≤ `STOP_POLL_S`.

**5. [`tasks/1.2.md:41-44`] [spec] Шаг 4: механизм момента сигнала не выбран, источники окон приватные.**
(а) «PM фиксирует его в `request_stop` либо геттер в `ChildProcessStop`» — два варианта. Выбери один: PM-часы в `_ChildrenStop.request_stop` ошибутся на ожидание исполнителя и паузу монитора (они ДО `group.request_stop()`, :4873-4878), поэтому выбор: геттер. Замена: «`ChildProcessStop`: `self._stop_requested_wall: float | None = None` (рядом с :100); в `request_stop` под тем же локом, что ставит `_stop_requested_at` (:172-175), — `self._stop_requested_wall = time.time()`; свойство `stop_requested_wall` (до `request_stop` — `None`). `_ChildrenGroupStop.signalled_at() -> float | None` (группа не собрана — `None`); `_ChildrenStop.signalled_at()` в PM делегирует в `self._group`; `_cmd_supervision_status` читает через `getattr(getattr(self, "_children_stop", None), "signalled_at", None)`.»
(б) Окно имени: PM не читает `registry._stop_windows` и `registry._system_window_s()` напрямую (приватные члены чужого класса), а зовёт новый публичный `ProcessRegistry.stop_window_s(name) -> float` = `self._stop_windows.get(name, self._system_window_s())` (чтение dict без лока — как D3). Двойники реестра: `tests/conftest.py:73` (`MockProcessRegistry`) и `MagicMock` реестр в `test_supervision_instance_truth.py:39`, `test_process_manager_process.py:234-295` вернут не число — PM проверяет `isinstance(x, (int, float)) and not isinstance(x, bool)`, иначе `None`.
(в) Зажим срока: настоящий `terminate` по имени идёт в `min(_stop_requested_at + окно, deadline)` (`child_process_stop.py:314`), а `deadline` группы фиксируется областью ДО фазы 1 (`base_manager/core/lifetime.py:394, :614`). Если фаза 1 заняла время (≤ `infra_s`), реальный срок раньше `сигнал + окно`. Для GUI это безопасная сторона (вопрос о зависании позже, не раньше), но формулировку в ADR-042 дать честную: «`stop_deadline_at` — верхняя оценка срока `terminate` по имени, не точный момент; превышение ≤ время фазы 1 (≤ `infra_s`)». Тест A3 фиксирует литерал при быстрой фазе 1.
(г) Что после подтверждения смерти: оставить значение без изменений (срок прошёл/не важен), `null` только до сигнала и вне стопа. Записать в ADR.

**6. [`process_manager_process.py:1057-1065`] [spec] Согласование с `system_stop.deadline_at` (1.2a) и откуда его брать.**
Форс-срез брать из того же снимка, что верхнее поле: `system_stop = self._system_stop_snapshot()` и ленивый `_begin_system_stop("graceful", "event", None)` (:1059-1064) ПЕРЕНЕСТИ ВЫШЕ цикла по процессам (:1031), внутри цикла: `if system_stop and system_stop["mode"] == "force": deadline_at = min(deadline_at, system_stop["deadline_at"])`. Иначе эскалация `force` между циклом и снимком даёт в одном ответе разные сроки. Значения совместимы: `deadline_at` у `force` = `started_at + deadline_s` при начале (`_begin_system_stop` :599-608) или `time.time() + deadline_s` при эскалации (:622-628) — тот же момент, что `set_force_deadline(time.monotonic() + deadline_s)` (:967); срез действует только пока не было `kill()` (`_ChildrenStop.join_until` :4929-4931) — после `kill()` срок `force` уже не режет, а `stop_deadline_at` остаётся прежним (дети добиваются фазой 3). Для `graceful` `system_stop.deadline_at` (= `started_at + pm_graceful_s`) НЕ использовать: он раньше реального срока (бриф это знает) — взял бы `min` и дал ложное «завис».

**7. [`tasks/1.2.md:65-77`] [tests] REDS: одна «красная» зелёная до правки, одна красная по лишней причине, счёт.**
- `H::test_message_processor_thread_does_not_confirm_death`: до правки `_cmd_supervision_status` уже читает только `registry.stop_outcome` (:1055) и `_observe()` с потока `message_processor` не зовёт — тест зелёный ДО правки; красным становится только под I4. Это страж, не RED. Перенести в «Страж» с пометкой «красный только под I4».
- `A::test_no_stop_gives_null_and_new_pm_does_not_crash`: красен до правки только если читает `rec["stop_deadline_at"]` и `rec["stop_wave"]` ИНДЕКСОМ (ключи отсутствуют); `.get(...)` даст зелёный. Вписать в REDS: «ключи присутствуют (`"stop_deadline_at" in rec`), значение `None`».
- `H::test_handed_over_does_not_overwrite_confirmed_terminated`: «два писателя `_record_stop_outcome`» — тест по имени приватного метода; по правилу «эффект, не имя API» вести через настоящих писателей (группа корня + `_stop_many` с прерыванием) и добавить случаи из п. 2: два потока на одном имени (`handed_over` против `terminated`, daemon-потоки, join с дедлайном) и `exited` против `terminated`.
- Счёт: сейчас 9 (A 5 + H 4). После правок: A1–A5 + **A6** (п. 4) + H-rank (п. 2) + H-not-reset + H-survived + **H-F1** (п. 9) = **10** красных; H-thread — страж. Предел 10 достигнут, больше добавлять некуда: следующее решение — резать.

**8. [`tasks/1.2.md:88-97`] [tests] Инъекции: нумерация и покрытие.**
- Столбец «Ожидаемо красные» ссылается на позиции («A 1», «H 7»); после п. 7 позиции сдвинутся. Писать ИМЕНА тестов.
- Сверка REDS ↔ I1–I6: по числу и позициям совпадают (I1→A1; I2→A2; I3→H7; I4→H6; I5→H9 и A1; I6→A1, A2), но: «I5 → и A 1» сомнительно — `survived` пишется на `False` фазы 2 (срок graceful), а A1 смотрит «посреди стопа», до этого срока; красным A1 станет, только если опрос после срока. Либо убрать «и A 1», либо зафиксировать момент опроса в A1. «I1 → только A 1» верно лишь если rig не зовёт `result()` после закрытия (я `test_pm_responsive_during_children_stop.py` не открывал).
- Без инъекций остаются заявленные свойства: A3 (`stop_deadline_at`: окно, окно по умолчанию, реальный сигнал, форс-срез), A4/A5 (ключи), H-not-reset, новые A6 и H-F1, лок и ранг (п. 2). Добавить: **I7** срок от `system_stop.started_at + pm_graceful_s` вместо момента сигнала → A3; **I8** игнорировать `stop_window_s` (всегда окно по умолчанию) → A3; **I9** не срезать форс-сроком → A3; **I10** убрать ключи `stop_wave`/`stop_deadline_at` с записи PM → A4, A5; **I11** не писать `exited` для умершего до стопа → A6; **I12** вернуть прежний `if self._group is None: return False` → H-F1; **I13** `_record_stop_outcome` без лока (если гонка не ловится — запись «не покрыто», не «невозможно») и **I3b** без ранга между подтверждёнными → H-rank. Против обоих наборов (слепого и авторского), как и сейчас.

**9. [`process_manager_process.py:4927-4928`] [spec] F1 (`docs/claude/OPEN_QUESTIONS.md:2133`) — ВКЛЮЧИТЬ в 1.2 шагом 7.**
Дефект подтверждён чтением: `join_until` на :4927-4928 (`if self._group is None: return False`) выходит раньше проверки `or self._killed` на :4933. Вход → выход (репро ревьюера 1.2a `edge_scope_nogroup.py`): реестр упал при старте (`_start_failed`), `kill()` звали → `system_stop.phase` и `system.stop.phase` остаются `children`, `done` не наступает. Для 1.2 это не посторонний дефект: контракт ADR-042 («после `phase == "done"` `null` = „PM не подтвердил“») на этом пути не исполняется — `done` никогда не придёт, потребитель ждёт вечно. Тот же файл (FILES п. 1), тот же класс `_ChildrenStop`, три строки; в OPEN_QUESTIONS владелец записал «сделать при Task 1.2». Отдельный коммит — допустимая альтернатива, но тогда исключить F1 из REDS и написать это в OUT OF SCOPE.
Шаг 7 (текст): «`_ChildrenStop.join_until` :4927-4928 → `if self._group is None:\n    if self._killed:\n        self._announce_phase("done")  # F1: группа не собрана, kill() звали — последний ход области\n    return False`. Тест `H::test_done_set_when_group_not_built_and_killed`: настоящая область, `_start_failed`, `kill()` → фаза и запись стора `done` ровно один раз; до `kill()` — `children`. F2–F4 ревью 1.2a в 1.2 не входят.» В ADR-042 — одна строка о F1; закрытие записи в `OPEN_QUESTIONS.md` — за лидом (файл вне FILES).

**10. [`tasks/1.2.md:33`] [quality] Неверная ссылка: «на системном стопе спавн отвергнут слоем спавна (ADR-PMM-040)».**
ADR-PMM-040 — порядок закрытия (`_own_work_late`). Отказ спавна — ADR-PMM-030, `create_and_register` `process_registry.py:394-400` (так сказано в комментарии :394 и в `design.md`, риск 3). Замена: «(ADR-PMM-030, `create_and_register` :397)». Оговорка для ADR: отказ проверяет только `system_stop_event`, а не `_children_stopping`; окно «корень начал, событие не взведено» закрывает `_stop_lifecycle_executor` (снимает очередь), H-not-reset его и держит.

**11. [`tasks/1.2.md:79-84`] [spec] ACCEPTANCE: у проба-пункта нет проверки новых полей.**
К пункту 2 (Darwin, `probe_slow.py` — файл есть в `docs/reports/2026-11-07_gui-graceful-close_1.1a_mac-probe/`) дописать: «в каждом ответе во время стопа `stop_wave == "main"` у всех записей; `stop_deadline_at` у живого ребёнка — число в диапазоне [момент команды; момент команды + окно + `infra_s`], у PM — `null`; до первого сигнала — `null`». К пункту 1 — «страж: `test_supervision_instance_truth.py`, `test_process_manager_process.py` (двойники реестра) зелёные».

**12. [шапка, FILES, шаг 6] [quality] Остатки.**
- FILES: добавить п. 7 `multiprocess_framework/modules/process_manager_module/tests/conftest.py` — заглушка `stop_window_s` в `MockProcessRegistry` (прецедент: 1.10 добавила `stop_outcome`/`call_stop_outcome`, :92-100). Если PM берёт всё через `getattr` + `isinstance` (п. 5б), файл не обязателен — тогда сказать это в DESIGN явно. Остальные тесты каталога вызывают `children_stop(...)` двойниками без `signalled_at` — PM читает через `getattr(..., None)`.
- `Handoff:` (шапка, п. 7): убрать «(стадия 0 на этом тексте после слияния 1.2a — якоря сдвинутся)», `Dependencies`: «Task 1.2a в `main` (`7465a5d4e`)».
- Шаг 6: строка-ссылка у ADR-PMM-039: заменить в `DECISIONS.md:2056` фрагмент «стоп корня (`_ChildrenGroupStop` `stop_outcome` не пишет);» на «стоп корня — см. ADR-PMM-042;». ADR-PMM-042 дописать после :2230; в нём — предел контракта, ранг (п. 2), `exited` для умершего до стопа (п. 4), верхняя оценка `stop_deadline_at` (п. 5в), F1 (п. 9), инвариант «колбэк из `_confirm` на потоке-владельце группы» (см. п. «открыто» 3).
- README модуля и `backend_ctl/AGENTS.md` до Task 1.4 не описывают `stop_wave`/`stop_deadline_at` — осознанный долг, упомянуть в ADR-042 «Последствия».

## 4. FILES: полнота

Нужно: 1–6 как в брифе + (по пп. 5, 12) `tests/conftest.py` либо явное «двойники не трогаем, PM защищён `getattr`/`isinstance`». Отдельный файл для rig'а не нужен: образец — `tests/test_pm_responsive_during_children_stop.py` (есть), живой rig с выжившим — `docs/reviews/2026-11-07_gui-graceful-close_task-1.2a-repro/survivor_rig.py` (образец для H-F1 и H-survived). `child_process_stop.py` в FILES есть (п. 1 и wall-time). `interfaces.py` модуля не затрагивается (приватные `core/`).

## 5. Итоговый список REDS (после правок, 10)

A: `dead_child_shows_exited_while_neighbour_still_stops`, `stubborn_child_terminated_and_killed_literals`, `stop_deadline_at_uses_window_and_real_signal_time` (окно, окно по умолчанию, форс-срез, до сигнала `None`), `stop_wave_main_for_all`, `no_stop_gives_null_keys_present_and_new_pm_does_not_crash`, **`child_dead_before_root_stop_shows_exited`** (п. 4).
H: `outcome_rank_and_two_writers` (п. 2; `handed_over`/`survived` против подтверждённого, `exited` против `terminated`, потоки), `outcome_not_reset_by_monitor_pause_or_refused_restart_during_stop`, `survived_only_after_kill_and_deadline`, **`done_set_when_group_not_built_and_killed`** (п. 9).
Страж (зелёный до и после; красный под I4): `message_processor_thread_does_not_confirm_death`.

## 6. Что я оставил открытым / ненадёжно

1. Ничего не запускал (по заданию). «Красная до правки / зелёная после» для каждого теста — по чтению кода, не по прогону; п. 7 — вывод из чтения `_cmd_supervision_status`, не из падения.
2. `base_manager/core/lifetime.py` прочитан по строкам `grep` (:394, :614, :581), не целиком. Вывод п. 5в («`deadline` группы фиксируется до фазы 1») — по этим строкам; величину перекоса на стенде не мерил.
3. Инвариант «`_terminated.add(name)` после `proc.terminate()`» (:231-236, :331-337) держится только договорённостью «`_confirm` зовёт поток-владелец группы»: `_confirm` достижим из `survivors()`/`outcomes()`/`close()` с любого потока. Сейчас вызовы идут с потока области (`_ChildrenGroupStop.result()` — :706; `_stop_many` — :590), читатель `supervision.status` их не зовёт. Предложение «`add` до `terminate`, откат при исключении» не вносил (меняет D2 1.10); ADR-042 должна назвать инвариант.
4. Тесты 1.10 (`test_stop_outcome_acceptance.py`) смотрел только `grep`: не проверил, требует ли какой-то из них `None` посреди одиночного `process.stop` (п. 3 это затрагивает).
5. Не проверил, равен ли `ProcessRegistry._system_window_s()` (из `_child_stop_budget`) `_budget()["pm_graceful_s"]` PM (:3782 по 1.2a) на всех путях; в брифе они подразумеваются равными.
6. Не открывал `test_pm_responsive_during_children_stop.py` целиком: утверждения о rig (звал ли он `result()`, п. 8) — не проверены.
7. Тело ADR-PMM-040 целиком не читал; п. 10 опирается на комментарий `process_registry.py:394` и `design.md`.
8. `memory hits:` — `scripts/memory/search.py` не запускал (бюджет контекста). qex не использовал: поиск `git grep` по путям; индекс не проверял.
9. Решение по п. 4 (писать ли `exited` умершему до стопа) расширяет контракт ADR-039/042 и принадлежит лиду/CTO; если не решится сейчас — это запись в `docs/claude/OPEN_QUESTIONS.md` (мне запись туда запрещена заданием).
10. Ревью шло по рабочему дереву `main` `a5eb6d382` (чистое, кроме постороннего `docs/reports/2026-10-26_stage0-eval.md`), не по зафиксированному SHA задачи; тело `tasks/1.2.md` — как в рабочем дереве.
11. Windows/heavy-пункты ACCEPTANCE не оценивал: ждут стенда. Видимость `survived` опросом (окно короче шага) принимаю на слово брифа.

---

# Раунд 2 (последний)

- **Читано:** `tasks/1.2.md` в рабочем дереве (не закоммичено, `git diff --stat`: +83/−47) при `main` `a5eb6d382`. Ничего не запускалось.
- **Вердикт: CHANGES REQUESTED (итерация 2 из 2).** Все 12 правок раунда 1 внесены и по существу верны; новых расхождений DESIGN с кодом нет (проверено, п. 4 ниже). Остаются **7 правок текста** `tasks/1.2.md` — ни одна не меняет дизайн; две из них (R2-2, R2-3) делают предсказания инъекций неверными или неполными, поэтому это не «косметика». Все замены даны дословно: если лид применит их как есть и проверит `git diff`, стадию 0 считаю закрытой без третьего раунда (эскалация по правилу «3-я итерация» — решение лида; я бы её не запускал).

## 1. Правки 1–12: отражены ли точно

| № | Правка раунда 1 | Статус | Замечание |
|---|---|---|---|
| 1 | `_confirm`: итог внутри лока, колбэки после, без раннего `return`, порядок метка → итог | да (шаг 1, :24-33) | фраза про wall-time в конце шага 1 содержит лишнее «после подтверждения смерти не менять» (R2-1) |
| 2 | ранг + листовой `_stop_outcome_lock`, читатель без лока | да (шаг 2, :36-41) | |
| 3 | `on_outcome` в `_build_child_stop` для обоих путей; :594 напрямую | да (шаг 2, :42-46) | |
| 4 | `exited` умершему до стопа | да (шаг 3б, A6, I11) | нет защиты «процесс есть в реестре» (R2-4) |
| 5 | геттер вместо PM-часов; `stop_window_s`; `isinstance`; верхняя оценка; (г) значение не менять | да (шаг 4, :57-68), кроме (г) | (г) попало в шаг 1, в шаг 4 его нет (R2-1) |
| 6 | снимок `system_stop` выше цикла; force-срез из снимка; graceful не использовать | да (:63-65) | |
| 7 | страж вместо RED; индекс ключей; через настоящих писателей; счёт 10 | да (REDS :95-106) | H2 без предусловия (R2-6) |
| 8 | имена тестов; I7–I13 | частично | предсказания I2, I6, I10 неполны (R2-2); у H2 инъекции нет (R2-3) |
| 9 | F1 шагом 7 | да (:69-72, H4, I12) | метка «шаг 7» стоит между шагами 4 и 5; образец `survivor_rig.py` — случай с группой, не `_group is None` (R2-7) |
| 10 | ADR-PMM-030, `create_and_register` :394-400 | да (:44-46) | |
| 11 | ACCEPTANCE: поля в пробе, страж с двойниками | да (:111-112) | |
| 12 | conftest.py в FILES, `Handoff`, `Dependencies`, :2056, содержимое ADR-042 | да (:7-8, :75-78, :91) | FILES п. 1–2 не называют `signalled_at` (R2-5); устаревший текст (R2-1) |

Проверка буквы ADR-039: фрагмент для замены «стоп корня (`_ChildrenGroupStop` `stop_outcome` не пишет);» совпадает с `DECISIONS.md:2056` символ в символ; ADR-PMM-042 по-прежнему свободен (`git grep` — только упоминания в планах); место «после :2230» верно.

## 2. REDS: ровно 10, красные ли до правки

Счёт: A1–A6 (6) + H1–H4 (4) = **10**; страж `test_message_processor_thread_does_not_confirm_death` в счёт не входит. Красные до правки (по чтению, не по прогону):
A1, A2, A6 — писателя итога на пути корня нет; A3, A4 — ключей нет; A5 — только при чтении ИНДЕКСОМ (в брифе так и сказано); H1 — нужен `terminated` от группы корня, которого сегодня нет; H3 — второй половине («после kill и срока `survived`») нечего пройти; H4 — `join_until` выходит на :4927-4928 без `done`.
Единственная неясность — **H2**: он красен до правки только если сначала записан итог корнем, а потом идёт пауза монитора/отказанный рестарт; без этого предусловия `stop_outcome` и до правки остаётся `None` и проверка «не сброшен» зелёная (R2-6).

## 3. Таблица инъекций против REDS

Сверка по именам: I1→A1, I2→A2, I3→H1, I3b→H1, I4→страж, I5→H3, I6→A1+A2, I7–I9→A3, I10→A4+A5, I11→A6, I12→H4. По числу совпадает, **по составу неполна** (R2-2):
- **I2** (колбэк всегда `exited`): H1 тоже станет красным — он ждёт `terminated`/`killed` от настоящей группы корня, а при I2 их не будет. Предсказано только A2.
- **I6** (колбэк не передан на пути `children`): H1 тоже красный (в реестре от корня ничего нет, останется `handed_over` исполнителя). A6 остаётся зелёным: его запись идёт из `request_stop` группы (шаг 3б), не через колбэк. Предсказано A1, A2.
- **I10** («убрать ключи с записи PM»): неоднозначно. Если ключи убираются со всех записей — красными будут A3, A4, A5 (A3 читает `stop_deadline_at`); если только с записи самого PM — A4 (если он проверяет и PM), A5. Предсказано A4, A5.
- **I1**: «только A1» верно лишь если область вызывает `result()` после закрытия и тот пишет итог; я `test_pm_responsive_during_children_stop.py` не открывал, поэтому предсказание ненадёжно (прогон решит).
- **H2** (`not_reset…`) не покрыт ни одной инъекцией — заявленное свойство без break-injection.

## 4. Новые расхождения с кодом

Проверено, **расхождений нет**: якоря шагов 1–4, 6, 7 совпадают с `a5eb6d382` (`_confirm` :144-156 и ранний `return` :151-152; `_terminated.add` :235-236/:336-337; конструктор :54-67; `_build_child_stop` :499-549 с конструктором :540; цикл :591-595, канал :594; `create_and_register` :394-400; `_cmd_supervision_status` :1000-1065, цикл с :1031, запись :1045-1056; `_ChildrenStop` :4807-4968, ветка F1 :4927-4928; `child_process_stop.py:314`; `lifetime.py:394, :614`). Лок `_stop_outcome_lock` листовой и берётся в `_ChildrenGroupStop.request_stop` под локом группы — инверсии нет (внутри `_record_stop_outcome` другие локи не берутся). Остатки — устаревший текст и мелкие пробелы описаны ниже.

## 5. Список правок раунда 2

**R2-1 [`tasks/1.2.md:19, 23, 35, 141`] [quality] Устаревший текст и фраза не на месте.**
- :19: «На `main` `50010cdb4`» → «На `main` `a5eb6d382`»; «`core/process_registry.py:638-700`» → «`core/process_registry.py:638-709`».
- :23: «Якоря пересчитать по `main` после слияния 1.2a.» → «Якоря — по `main` `a5eb6d382` (после слияния 1.2a).»
- :35: «Один `time.time()`; после подтверждения смерти не менять.» → «Ставится один раз (внутри `if not self._stop_requested`).» (фраза про «не менять» относится к `stop_deadline_at`, см. шаг 4.)
- Шаг 4, новый пункт после :68: «После подтверждения смерти ребёнка `stop_deadline_at` не пересчитывается и не обнуляется (срок прошёл, значение остаётся); `null` — только до сигнала и вне стопа. У умершего до стопа ребёнка (шаг 3б) значение = сигнал + окно, хотя в группе его нет; потребитель им не пользуется (`stop_outcome` уже `exited`) — записать в ADR.»
- :141 (TRAPS): убрать «; нумерацию ADR сверить после слияния 1.2a» (042 сверен).

**R2-2 [`tasks/1.2.md:121-133`] [tests] Предсказания инъекций.** Заменить строки:
`| I1 | запись только в конце (`result()`), не в `_confirm` | A1 (ненадёжно: верно, если область зовёт `result()` после закрытия; иначе также A2 — записать факт прогона) |`
`| I2 | колбэк всегда пишет `exited` | A2, H1 |`
`| I6 | колбэк не передан на пути `children` | A1, A2, H1 (A6 зелёный: запись идёт из `request_stop` группы, шаг 3б) |`
`| I10 | убрать `stop_wave` и `stop_deadline_at` со ВСЕХ записей процессов в ответе | A3, A4, A5 |`

**R2-3 [`tasks/1.2.md:133`] [tests] Свойство H2 без инъекции.** Добавить строку:
`| I13 | `remove_process(name)` (путь отказанного рестарта/паузы монитора) дополнительно делает `_stop_outcomes.pop(name, None)` | H2 |`
и фразу под таблицей: «Если H2 не доходит до `remove_process` и инъекция его не краснит — запись «не покрыто», не вывод «невозможно»». Также к I3 дописать «(последний писатель выигрывает)».

**R2-4 [`tasks/1.2.md:49-53`, шаг 3б] [spec] Защита от несуществующего имени.** `done` из `_build_child_stop` содержит и имя, которого нет в реестре (`result[name] = True`, :521-527). Дописать в 3б: «`for name in done: if self._registry.get_process_by_name(name) is not None: self._registry._record_stop_outcome(name, "exited")` — имя без объекта в реестре итог не получает».

**R2-5 [`tasks/1.2.md:9, 85-86`] [quality] FILES и контракт модуля.**
- FILES п. 1: «шаг 4 (в т. ч. `_ChildrenStop.signalled_at`) и F1 (шаг 7)».
- FILES п. 2: «шаги 2, 3 и `_ChildrenGroupStop.signalled_at()` (шаг 4; читает `getattr(self._group, "stop_requested_wall", None)` — фейковые группы в тестах свойства не имеют)».
- `Module contract:` дописать: «, новые публичные члены `ProcessRegistry.stop_window_s`, `ChildProcessStop.stop_requested_wall`».

**R2-6 [`tasks/1.2.md:103`] [tests] Предусловие H2.** Заменить на: «H2::test_outcome_not_reset_by_monitor_pause_or_refused_restart_during_stop (сначала корень записал `exited`/`terminated`; затем пауза монитора и отказанный рестарт того же имени; `stop_outcome` прежний — без предусловия тест зелёный до правки)».

**R2-7 [`tasks/1.2.md:69, 95, 105`] [quality] F1: нумерация и образец.** Заголовок «F1 (шаг 7, …)» стоит между шагами 4 и 5 — переименовать в «7. F1 (включён решением лида; ревью п. 9)» и перенести после шага 6 либо оставить, но пометить «(шаг 7, после 6)». В строке REDS (:95) образец для F1 — `docs/reviews/2026-11-07_gui-graceful-close_task-1.2a-repro/survivor_rig.py` — это случай «группа есть, выживший»; случая `_start_failed` / `_group is None` в каталоге нет (`edge_scope_nogroup.py` из `OPEN_QUESTIONS.md:2133` в git не отслеживается). Дописать в H4: «`_start_failed` собрать самому: `registry.children_stop` бросает».

## 6. Что я оставил открытым / ненадёжно (раунд 2)

1. Ничего не запускал; «красный до правки» и составы красных под инъекциями — вывод из чтения кода и описаний тестов, не из прогона. Состав для I1 прямо помечен ненадёжным.
2. Тексты тестов H1–H4 и A1–A6 ещё не написаны: предсказания R2-2 опираются на описания в брифе (в частности, что H1 получает `terminated`/`killed` от настоящей группы корня). Если слепой тестер/автор построит H1 иначе, состав красных под I2/I6 изменится.
3. Не проверял, что `remove_process` реально лежит на пути отказанного рестарта (R2-3 — предложение инъекции, не факт); не проверял тесты 1.10 на требование `None` посреди одиночного стопа (после правки п. 3 раунда 1 запись идёт и там).
4. Фейковые группы в `test_process_root_pm_hazards.py:292` (подмена `_build_child_stop`) и 5 двойников `children_stop` — читал только по `grep`; защита `getattr` в PM и в `_ChildrenGroupStop.signalled_at()` предписана, но не проверена прогоном стража.
5. Инвариант «`_confirm` зовёт поток-владелец группы» по-прежнему договорённость, не механизм (записан в ADR-042 по предписанию); корректность на живом Windows-стенде не оценивал (heavy-пункт ждёт стенда).
6. `memory hits:` не запускал; ревью по рабочему дереву (`tasks/1.2.md` не закоммичен, дерево чистое кроме `docs/reports/2026-10-26_stage0-eval.md`), SHA кода — `a5eb6d382`.
