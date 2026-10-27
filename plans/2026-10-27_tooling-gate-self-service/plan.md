# Самообслуживание окон и merge через гейт

Бриф: `docs/handoffs/2026-10-27_gate-self-service.md`. Полоса: tooling. Ветка: `feat/tooling-gate-self-service`
(worktree `.claude/worktrees/gs`). Сессия лида: `inspector-bottles-dd`. Координатор: `inspector-bottles-10`.
Контракт старых подкоманд: `plans/2026-10-13_tooling-machine-gate-hook/task-1.2.md`.

## Цель

Очередь окон, выдача, «ок» на merge и входящие в реестр делает скрипт `scripts/machine_gate.sh`, а не
координатор руками. Сообщения между чатами остаются только для решений владельца, владения файлом и находок в
чужом коде.

## Статус

- [ ] Стадия 0 — `reviewer` (sonnet), синхронно, один раз на текст Task 1.1
- [ ] Стадия 1 — слепой `tester` в worktree на коммите до кода
- [ ] Стадия 2 — реализация (`developer` sonnet по точному DESIGN)
- [ ] Стадия 3 — матрица инъекций по обоим наборам тестов
- [ ] Стадия 5 — `reviewer` после задачи
- [ ] Merge: «сливаю» координатору (последний раз по старому протоколу), ждать «ок»

## Task 1.1 — подкоманды `request` / `release` / `wait` / `extend` / `merge-begin` / `merge-end`, входящие реестра, правила

**Level:** Senior (конкурентная запись замка; реализация — Sonnet по точному DESIGN, дизайн-решения по
конкурентности остаются за лидом/teamlead).
**Goal:** полоса сама встаёт в очередь, получает и отдаёт окно, занимает merge-слот; замок остаётся годным при
гонках.

### DESIGN

Общее.

- Все новые подкоманды пишут замок тем же способом, что `cmd_edit`: `machine.lock.tmp` под `set -C` (O_EXCL) +
  `mv -f`, проверки повторяются под защитой tmp. Отличие от `grant`/`close`: занятый tmp **ждётся** (повтор
  каждые ~0.1 с, до ~10 с), после чего отказ `machine_gate: machine.lock.tmp exists …` с кодом 2. Поведение
  `grant`/`close` (мгновенный отказ при занятом tmp) не менять.
- Нет `machine.lock` → отказ `machine_gate: no machine.lock`, код 2. Битый замок → код 2 с текстом
  `validate_lock`. Имя сессии — `is_name`, иначе `bad session name`, код 2.
- Порядок строк при записи: `coordinator`, `window`, `merging`, затем остальные строки в прежнем порядке;
  новые `waiting:` — в конец (FIFO = порядок строк `waiting:` сверху вниз). Прочие строки (`stand:` и т. д.)
  и пустые — как были.
- Время: `now` = `date +%s`; переопределяется `MACHINE_GATE_NOW_EPOCH` (только для тестов). `until ~HH:MM`
  считается `date -d "@<now+N*60>" +%H:%M`. Остаток окна в минутах = `HH:MM` из замка относительно now, приведённый
  к интервалу [−12 ч, +12 ч) (окна ≤ 600 мин, переход через полночь корректен).
- `what` не содержит `|`, `\r`, `\n` (как у `grant`); минуты 1..600 (как у `grant`).
- Автовыдача (`promote`): после изменения замка, если `window:` нет и есть `waiting:` — первая по порядку
  строка `waiting:` становится `window: <s> | <kind> | <what> | until ~<now+N min>`, где N берётся из `~N min`
  этой строки. Выполняется в `request`, `release`, `merge-end` и **не** выполняется в `grant`/`close`.

Подкоманды.

1. `request <session> quiet|heavy|stand <minutes> <what...>`
   - Своё окно уже есть → ничего не меняет, печатает `GRANTED until ~<тот же HH:MM>`, код 0.
   - Своя `waiting:` уже есть → ничего не меняет, печатает `QUEUED position <N>`, код 0.
   - Иначе дописывает `waiting: <s> | <kind> | <what> | ~<minutes> min`, затем `promote`. Если после этого у
     сессии `window:` — `GRANTED until ~HH:MM`; иначе `QUEUED position N`, где N = номер её строки среди
     `waiting:` (1 = первая в очереди).
   - Плохой kind/минуты/what — код 2, замок без изменений.
2. `release <session>`
   - Есть своё окно → строка снимается, `promote`, печать `RELEASED`; при выдаче следующему —
     вторая строка `NEXT <session> until ~HH:MM`. Код 0.
   - Окна нет, но есть своя `waiting:` → строка снимается (отмена заявки), печать `CANCELLED`, код 0.
   - Нет ни окна, ни заявки, либо окно чужое → `machine_gate: no window of this session`, код 2, замок не
     тронут.
3. `wait <session> [--timeout <min>]`
   - Нет своей `waiting:` и нет своего `window:` → код 2 (`no request of this session`).
   - Своё окно есть → печать `GRANTED until ~HH:MM`, код 0. Иначе опрос замка раз в `MACHINE_GATE_POLL_SEC`
     (по умолчанию 15). `--timeout` в минутах, целое ≥ 0, по умолчанию 120; `0` — одна проверка. Истёк →
     печать `TIMEOUT`, код 124.
   - На каждом опросе, если окно держит другая сессия, оно просрочено и сессия ждёт, печатается
     `OVERDUE <holder> +<N> min` (строка не чаще раза на смену N).
   - Замок пропал или стал битым во время ожидания → код 2.
4. `extend <session> <minutes>`: только своё окно (иначе код 2); новое `until` = max(now, старое until) +
   минуты; минуты 1..600. Печать `EXTENDED until ~HH:MM`.
5. Просрочка: окно **не** отбирается. `status` (после строк замка, до `ram_free_mb`) печатает
   `OVERDUE <holder> +<N> min` для просроченного `window:`, только если есть хотя бы одна `waiting:`. Иначе вывод
   `status` побайтно прежний.
6. Merge-слот: строка `merging: <session> | <branch> | since <HH:MM>` (ровно 3 поля, не более одной на замок).
   - `merge-begin <session> <branch>`: отказ (код 2), если слот занят (любой сессией, в т. ч. своей) или есть
     `window:` вида `quiet` (любой сессии). Иначе строка записывается, печать `MERGE SLOT TAKEN`. Branch =
     `[A-Za-z0-9._/-]+`.
   - `merge-end <session>`: только владелец слота, иначе код 2 и замок не тронут; печать `MERGE SLOT FREE`.
   - Освобождение слота `promote` не вызывает ограничений для `quiet` (см. «Открытые вопросы»).
7. `validate_lock`: правило `merging: <s> | <branch> | since <HH:MM-текст>`: 3 поля, `is_name`, branch по
   шаблону, третье поле начинается с `since `; не более одной такой строки. Иначе код 2 с прежним текстом
   `malformed machine.lock:<n>: <line>`.

Входящие реестра.

- Каталог `plans/queue/inbox/`, файл `README.md` (формат: имя `<YYYY-MM-DD>_<session>_<N>.md`, содержимое —
  одна строка таблицы реестра целиком, номер C-NN не присвоен, кладётся в merge-коммит полосы; сворачивает в
  `defects.md` / `ORDER.md` одним коммитом координатор или любая сессия раз в полдня, номера присваиваются при
  свёртке). Скрипта свёртки не делать.

Правила (английский, model-read; источник `.claude/plugins/dev/…`, затем копия байт в байт в зеркало).

- skill `coordinator` §2 (грамматика: `merging:`), §4 (сигналы: окна и merge идут через скрипт; сообщения —
  только вопрос владельцу, владение файлом, находка в чужом коде; без «принято» и подтверждений; отчёт
  координатору не нужен — итог в файле полосы), §5 (шаблон старт-промпта: LOAD/REPORT).
- `project-rules` §8 и `.claude/CLAUDE.md` → «Shared machine»: кратко те же команды.

### FILES

- `scripts/machine_gate.sh` — подкоманды, грамматика, `promote`, OVERDUE в `status`.
- `scripts/machine_gate_tests/test_machine_gate_self_service.py` (приёмка тестера),
  `test_machine_gate_self_service_hazards.py` (hazard-тесты автора).
- `plans/queue/inbox/README.md`.
- `.claude/plugins/dev/skills/coordinator/SKILL.md` + зеркало `.claude/skills/coordinator/SKILL.md`;
  `project-rules` (источник в `.claude/plugins/…`, зеркало — найти `git grep -l "Shared machine"`);
  `.claude/CLAUDE.md`.
- Хук `machine-gate-guard.sh` — только если новые подкоманды блокируются (проверить `classify` на строке
  `machine_gate.sh request s heavy 10 pytest …`: слово `pytest` в `what`).

### Вне объёма

Классификация (`classify`, `machine_gate_timed.txt`); автоотбор просроченного окна; свёртка inbox скриптом;
боевой `machine.lock` (тесты — только `MACHINE_LOCK_DIR` на временный каталог).

### REDS (приёмка; литералы уточнят стадия 0 и тестер)

R1. `request s1 heavy 10 a` в замке без окон → `GRANTED until ~HH:MM`, код 0, `window: s1 | heavy | a | until ~HH:MM`;
    затем `request s2 heavy 5 b` → `QUEUED position 1`, код 0, `waiting: s2 | heavy | b | ~5 min`.
R2. `release s1` → у s2 `window:`, строки `waiting: s2` нет; `wait s2 --timeout 0` → код 0.
R3. `release s2` при окне s1 → код 2, байты замка прежние.
R4. FIFO: s1 держит окно, `request` s2, s3, s4 по очереди → позиции 1, 2, 3; после `release s1` окно у s2, не у s3.
R5. Повторный `request s2` → замок побайтно тот же, `QUEUED position 1`.
R6. Две параллельные `request` (разные сессии, окон нет) → замок годен (`status` rc=0), обе сессии присутствуют, ровно
    одно `window:`. Тест — в daemon-потоках с дедлайном.
R7. `merge-begin s1 feat/x` → слот; второй `merge-begin s2 feat/y` → код 2; при `window: … | quiet |` → код 2;
    `merge-end s2` при слоте s1 → код 2; `merge-end s1` → слот свободен.
R8. `validate_lock`: `merging: s1 | feat/x` (2 поля) → код 2; две строки `merging:` → код 2.
R9. `wait` для чужой/отсутствующей заявки → 2; таймаут `--timeout 0` без окна → 124; `wait`, запущенный до
    `release` другим процессом, завершается кодом 0 (`MACHINE_GATE_POLL_SEC=1`).
R10. `status` при просроченном окне и одной `waiting:` → строка `OVERDUE s1 +<N> min`
    (`MACHINE_GATE_NOW_EPOCH`); без `waiting:` — вывод прежний.
R11. `extend s1 30` продлевает; `extend s2 30` при окне s1 → код 2.
R12. Старые `grant`/`close`/`status` и существующие тесты `scripts/machine_gate_tests` — зелёные без правки литералов.

Инъекции (предсказания записываются ДО прогона): (а) убрать проверку владельца в `release` → R3 красный;
(б) убрать FIFO (брать последнюю `waiting:`) → R4; (в) убрать O_EXCL (`set -C`) → R6; (г) убрать проверку
слота/quiet в `merge-begin` → R7; (д) пропустить `merging:` с 2 полями → R8; (е) `extend` без проверки владельца
→ R11. Точные имена тестов фиксируются после стадии 1.

### Открытые вопросы (для стадии 0)

1. `promote` при `release` откроет **любую** первую `waiting:` — в т. ч. `stand`-заявку, которую координатор вёл
   вручную «после готовности владельца» (в живом замке сейчас такая есть). Принять как есть или не выдавать
   `stand` автоматически?
2. Асимметрия merge/quiet: `quiet`-окно не выдаётся при открытом `merging:` — нужно ли (сейчас: нет)?
3. Застрявший `merging:` (сессия упала): снимает координатор правкой замка вручную — достаточно?
4. `wait` по умолчанию 120 мин и `release` как отмена заявки — не расширение ли сверх брифа?
