# Самообслуживание окон и merge через гейт

Бриф: `docs/handoffs/2026-10-27_gate-self-service.md`. Полоса: tooling. Ветка: `feat/tooling-gate-self-service`
(worktree `.claude/worktrees/gs`). Сессия лида: `inspector-bottles-dd`. Координатор: `inspector-bottles-10`.
Контракт старых подкоманд: `plans/2026-10-13_tooling-machine-gate-hook/task-1.2.md`.
Стадия 0, итерация 1: `stage0-review.md` (CHANGES REQUESTED → правки внесены в этот текст, SHA ниже).

## Цель

Очередь окон, выдача, «ок» на merge и входящие в реестр делает скрипт `scripts/machine_gate.sh`, а не
координатор руками. Сообщения между чатами остаются только для решений владельца, владения файлом и находок в
чужом коде.

## Статус

- [x] Стадия 0, итерация 1 — reviewer sonnet: CHANGES REQUESTED (10 пунктов, приняты)
- [x] Стадия 0, итерация 2 — тот же reviewer: CHANGES REQUESTED (5 точечных правок текста тестов/часов/trap); применены лидом без 3-й итерации (лимит 2), проверку несут слепой tester и матрица инъекций
- [x] Стадия 1 — слепой `tester` (worktree gst, e4726fce0): 241 тест, 220 красных по делу, 21 зелёный (контроли); файл перенесён в gs
- [ ] Стадия 2 — реализация (`developer` sonnet по точному DESIGN; он же чинит свои красные и правки инъекций)
- [ ] Стадия 3 — матрица инъекций по обоим наборам тестов (предсказания лида до прогона; прогон — haiku)
- [ ] Стадия 5 — `reviewer` после задачи, синхронно
- [ ] Merge: «сливаю» координатору (последний раз по старому протоколу), ждать «ок»; в сообщении — что ручные `waiting:` в замке (сейчас `inspector-bottles-78 | stand`) координатору снять до слияния

## Task 1.1 — самообслуживание окон и merge-слота

**Level:** Senior (конкурентная запись замка); реализация — Sonnet по точному DESIGN.
**Assignee:** developer (sonnet); дизайн-решения по конкурентности — лид.
**Goal:** полоса сама встаёт в очередь, получает и отдаёт окно, занимает merge-слот; замок остаётся годным при
гонках.
**Один Task, а не три** (reviewer предлагал делить: 12 REDS > 10): всё — один файл, один путь записи замка
(`lock_edit`), один слепой тестер на механизм; части A (окна), B (merge-слот), C (inbox + правила) идут одним
исполнителем.
**Module contract:** n/a (скрипт, не модуль).
**Gate (зелёный):** `MACHINE_LOCK_DIR=<tmp> bash "$(git rev-parse --path-format=absolute --git-common-dir)/../scripts/machine_gate.sh" medium inspector-bottles-dd python -m pytest scripts/machine_gate_tests -q --tb=short`
(medium; боевой замок не трогается — тесты ставят `MACHINE_LOCK_DIR` сами) + `python scripts/validate.py`.
**Handoff:** `docs/handoffs/2026-10-27_tooling-gate-self-service-merged.md` (10–15 строк) в merge-коммите.

### DESIGN

#### Окружение (только для тестов; значения по умолчанию — боевые)

- `MACHINE_LOCK_DIR` — как сейчас.
- `MACHINE_GATE_NOW_EPOCH` — целые секунды, подменяет «сейчас» в расчётах `until`/остатка; нечисловое — игнорируется.
  Время суток считается `date -d "@<epoch>" +%H:%M` (тесты ставят `TZ=UTC`).
- `MACHINE_GATE_POLL_SEC` — шаг опроса `wait`, `^[1-9][0-9]*$`, иначе 15.
- `MACHINE_GATE_TMP_WAIT_SEC` — сколько ждать занятый `machine.lock.tmp`, `^[0-9]+$`, иначе 10.

#### Запись замка (`lock_edit`) — один путь для всех изменяющих новых команд

1. `now` читается ОДИН раз в начале вызова, до захвата tmp.
2. Быстрый путь без записи (идемпотентные ветки: свой `window`/своя `waiting` уже есть; отказы): tmp не берётся,
   inode замка прежний.
3. Захват `machine.lock.tmp` под `set -C` (O_EXCL). Занят — повтор каждые 0.1 с до `MACHINE_GATE_TMP_WAIT_SEC`;
   tmp старше 60 с (по mtime; возраст считается по РЕАЛЬНЫМ часам, `MACHINE_GATE_NOW_EPOCH` его не двигает; тест ставит mtime через `os.utime`) считается оставшимся от убитого держателя: удаляется, захват повторяется
   (остаточная гонка двух реклеймеров принята и записана здесь). Не вышло — отказ тем же текстом, что у `grant`
   (`machine.lock.tmp exists (another grant/close running, or a leftover)`), код 2, чужой tmp цел.
4. `trap` на EXIT/INT/TERM/HUP, снимающий tmp, ставится только ПОСЛЕ успешного захвата (флаг владения): иначе
   проигравший удалил бы tmp победителя. Сразу после `mv` или `rm` своего tmp флаг сбрасывается и trap снимается (долгоживущий `wait` после промоута иначе удалил бы чужой живой tmp при остановке).
5. Под защитой tmp замок читается и проверяется заново (`validate_lock`), решение принимается по свежему
   содержимому; результат пишется в tmp и подменяется `mv -f`. Не вышло (`Device or resource busy` у читателя) —
   5 повторов × 0.2 с, затем `cannot replace machine.lock (busy), retry`, tmp снят, код 2.
6. Один `mv` на вызов (запись заявки и автовыдача — одной записью). Результат в stdout печатается только после
   успешного `mv`.
7. `grant`/`close` и их мгновенный отказ при занятом tmp НЕ менять.

#### Порядок строк

Существующие строки не двигаются. Новая `window:` — сразу после `coordinator:`; новая `merging:` — сразу после
`window:` (если её нет — после `coordinator:`); новая `waiting:` — в конец файла (после `stand:` и прочего).
Автовыдача (`promote`) убирает выданную `waiting:` и вставляет `window:` по правилу выше.

#### `promote` (автовыдача)

Если `window:` нет и есть `waiting:` — ПЕРВАЯ по порядку `waiting:` становится
`window: <s> | <kind> | <what> | until ~<HH:MM(now+N)>`; N — из 4-го поля по шаблону `^~([1-9][0-9]{0,2}) min`,
N ≤ 600, иначе N = 60 (строка не пропускается и очередь не клинится). Выполняется в `request`, `release` и на
каждом опросе `wait` при отсутствии окна; в `grant`/`close` и в `merge-end` — НЕТ. Причина: старый
`test_close_removes_own_window` ждёт `waiting:` на месте; `merge-end` освобождает слот, окон он не трогает.

#### Время и просрочка

- Остаток окна (минут) = `HH:MM` из `until ~HH:MM` минус now, приведённый к интервалу [−13 ч, +11 ч)
  (свежее окно ≤ 600 мин всегда в плюсе, просрочка видна 13 ч, переход через полночь корректен). Арифметика —
  `10#` (иначе `08`/`09` ломают `$((…))`).
- Просрочено ⇔ остаток ≤ −1. `until` не вида `~HH:MM` (HH ≤ 23, MM ≤ 59) → окно не считается просроченным,
  `OVERDUE` не печатается, `extend` на нём — код 2.
- `status` (после строк замка, до `ram_free_mb`) печатает `OVERDUE <holder> +<N> min` для просроченного
  `window:` ТОЛЬКО если есть хотя бы одна `waiting:`. Иначе вывод `status` побайтно прежний. На битом замке
  `OVERDUE` не печатается.
- `wait` печатает ту же строку на опросе, если чужое окно просрочено (по строке на опрос, не чаще смены N).
- Окно не отбирается автоматически.

#### Тексты и порядок отказов (все — `machine_gate: <текст>` в stderr, код 2; usage — без префикса, как у `grant`)

Порядок проверок: usage → нет замка → битый замок → имя сессии → kind → минуты → what → branch → проверка
операции → tmp → перепроверка под tmp.

| Что | Текст |
|---|---|
| usage `request` | `usage: machine_gate.sh request <session> quiet\|heavy\|stand <minutes> <what...>` |
| usage `release` | `usage: machine_gate.sh release <session>` |
| usage `wait` | `usage: machine_gate.sh wait <session> [--timeout <minutes>]` |
| usage `extend` | `usage: machine_gate.sh extend <session> <minutes>` |
| usage `merge-begin` | `usage: machine_gate.sh merge-begin <session> <branch>` |
| usage `merge-end` | `usage: machine_gate.sh merge-end <session>` |
| нет замка | `no machine.lock` |
| битый замок | текст `validate_lock` (`malformed machine.lock:<n>: <line>` и т. п.) |
| имя | `bad session name` |
| kind | `window kind must be quiet, heavy or stand` |
| минуты | `minutes must be 1..600` |
| what | `what must not contain \| or line breaks` |
| branch | `bad branch name` (допустимо `[A-Za-z0-9._/-]+`) |
| `release`: нет ни окна, ни заявки | `no window or request of this session` |
| `wait`: нет ни окна, ни заявки | `no request of this session` |
| `wait`: заявка пропала посреди опроса | `request of this session disappeared` |
| `extend`: нет своего окна | `no window of this session` |
| `extend`: `until` не `~HH:MM` | `window has no valid until` |
| `extend`: остаток после продления > 600 | `extension too long (more than 600 minutes left)` |
| `merge-begin`: слот занят | `merge slot is taken by <session>` |
| `merge-begin`: открыто окно quiet | `a quiet window is open` |
| `merge-end`: слота нет | `no merge slot` |
| `merge-end`: слот чужой | `merge slot belongs to <session>` |
| tmp занят | `machine.lock.tmp exists (another grant/close running, or a leftover)` |
| `mv` не удался | `cannot replace machine.lock (busy), retry` |

`wait`: разбор `wait S` или `wait S --timeout N`, N `^(0|[1-9][0-9]{0,3})$`; иное — usage. Нечитаемый/битый замок на
опросе — 3 повтора × 0.5 с, затем код 2 с текстом отказа.

#### Подкоманды

1. `request <session> quiet|heavy|stand <minutes> <what...>`
   - Своё окно уже есть → замок не тронут, `GRANTED until ~<тот же HH:MM>`, код 0.
   - Своя `waiting:` уже есть → `promote` (если окна нет) и затем `GRANTED until ~HH:MM`, если окно стало своим,
     иначе `QUEUED position <N>`; код 0; если ничего не изменилось — замок не тронут.
   - Иначе дописывает `waiting: <s> | <kind> | <what> | ~<minutes> min`, затем `promote`; печать `GRANTED until ~HH:MM`
     или `QUEUED position <N>`, N = номер её строки среди `waiting:` (1 = первая).
2. `release <session>`: свое окно → строка снята, `promote`, печать `RELEASED` (+ вторая строка
   `NEXT <session> until ~HH:MM`, если окно выдано следующему); иначе своя `waiting:` (при любом чужом окне) →
   сняты все `waiting: <s>`, `CANCELLED`, окно чужого цело; иначе отказ (таблица). Код 0 / 2.
3. `wait <session> [--timeout <min>]`: по умолчанию 120 мин, `0` — одна проверка. Каждый опрос: своё окно →
   `GRANTED until ~HH:MM`, код 0; нет окна → `promote` под tmp; чужое просрочено → `OVERDUE …`; истёк дедлайн
   (по реальным часам, `MACHINE_GATE_NOW_EPOCH` его не двигает) → `TIMEOUT`, код 124.
4. `extend <session> <minutes>`: только своё окно; новое `until` = max(now, старое until) + минуты; остаток после
   продления не более 600; печать `EXTENDED until ~HH:MM`.
5. `merge-begin <session> <branch>`: отказ, если слот занят (любой сессией, и своей) или есть `window:` вида
   `quiet`; иначе `merging: <s> | <branch> | since <HH:MM>`, печать `MERGE SLOT TAKEN`. Quiet-окно при открытом
   слоте выдаться МОЖЕТ (замер перезапускается) — симметрии нет сознательно.
6. `merge-end <session>`: владелец слота ИЛИ имя из `coordinator:` (снять застрявший слот без ручной правки замка);
   иначе отказ. Печать `MERGE SLOT FREE`.
7. `validate_lock`: строка `merging: <s> | <branch> | since <текст>` — ровно 3 поля, `is_name`, branch по шаблону,
   третье поле с префиксом `since `, не более одной такой строки; иначе код 2 с прежним текстом
   `malformed machine.lock:<n>: <line>`. Битый замок остаётся rc=2 для всех подкоманд (прежний контракт).

#### Входящие реестра

`plans/queue/inbox/README.md`: файл `<YYYY-MM-DD>_<session>_<N>.md`; первая строка `registry: defects.md|ORDER.md|backlog.md`
(целевой реестр), далее одна строка таблицы реестра целиком, номер C-NN не присвоен; кладётся в merge-коммит
полосы; сворачивает в реестр одним коммитом координатор или любая сессия раз в полдня, номера присваиваются при
свёртке. Скрипта свёртки не делать.

#### Правила (английский, model-read; источник `.claude/plugins/dev/…`, затем копия байт в байт в зеркало)

skill `coordinator` §2 (грамматика `merging:`), §4 (сигналы: окна и merge — через скрипт; сообщения только: вопрос
владельцу, владение файлом, находка в чужом коде; без «принято» и подтверждений; отчёт координатору не нужен —
итог в файле полосы), §5 (шаблон старт-промпта: LOAD/REPORT); `project-rules` §8 и `.claude/CLAUDE.md` →
«Shared machine» — кратко те же команды. Отдельные строки правил: `request` только когда полоса готова стартовать
СЕЙЧАС (иначе автовыдача откроет окно впустую); ручные `waiting:` координатора до слияния снимаются; `release`
отменяет и заявку (`CANCELLED`).

### FILES

- `scripts/machine_gate.sh`
- `scripts/machine_gate_tests/test_machine_gate_self_service.py` (приёмка тестера),
  `test_machine_gate_self_service_hazards.py` (hazard-тесты автора)
- `plans/queue/inbox/README.md`
- `.claude/plugins/dev/skills/coordinator/SKILL.md` + зеркало `.claude/skills/coordinator/SKILL.md`; `project-rules`
  (источник в `.claude/plugins/…`, зеркало — найти `git grep -l "Shared machine"`); `.claude/CLAUDE.md`
- Хук `machine-gate-guard.sh` — НЕ менять (reviewer воспроизвёл rc=0 на `request … pytest -q …`).

### Вне объёма

Классификация (`classify`, `machine_gate_timed.txt`); автоотбор просроченного окна; свёртка inbox скриптом;
боевой `machine.lock` (тесты — только `MACHINE_LOCK_DIR` на временный каталог); `grant`/`close`.

### REDS (приёмка; литералы для тестов — `TZ=UTC`; `MACHINE_GATE_NOW_EPOCH=1798329600` = 00:00, `1798330200` = 00:10; R10/R11 — now = 00:10)

R1. Замок `coordinator` без окон: `request s1 heavy 5 a` → stdout `GRANTED until ~00:05`, код 0; в замке
    `window: s1 | heavy | a | until ~00:05` сразу после `coordinator:`. Затем `request s2 heavy 10 b` →
    `QUEUED position 1`, код 0, последняя строка замка `waiting: s2 | heavy | b | ~10 min`.
R2. После `release s1` (stdout `RELEASED` + `NEXT s2 until ~00:10`): `window: s2 | heavy | b | until ~00:10`, строки
    `waiting: s2` нет; `wait s2 --timeout 0` → `GRANTED until ~00:10`, код 0.
R3. `release s3` (нет ни окна, ни заявки) при окне s1 → код 2, `no window or request of this session`, байты замка прежние.
R3b. `release s2` (s2 в очереди, окно у s1) → `CANCELLED`, код 0, `window: s1` и остальные строки цел, `waiting: s2` снята.
R4. FIFO: окно s1, `request` s2, s3, s4 → `QUEUED position 1/2/3`; после `release s1` окно у s2 (не у s3).
R5. Повторный `request s2` → замок побайтно тот же (inode не менялся — mtime/ino), `QUEUED position 1`.
R6. Две параллельные `request` (разные сессии, окон нет) → замок годен (`status` rc=0), обе сессии присутствуют,
    ровно одно `window:`. Тест в daemon-потоках с дедлайном. Детерминированный вариант: функция `mv` через `BASH_ENV` — первый вызов
    создаёт маркер и ждёт go-файл; второй `request` стартует, через ~1 с тест даёт go; ожидается rc 0 у обоих и обе
    сессии в замке (краснит и снятие `set -C`, и пропуск перечитывания под tmp). Приём slow-`date` — не годится
    (`now` читается до замка).
R7. `merge-begin s1 feat/x` → `MERGE SLOT TAKEN`, `merging: s1 | feat/x | since 00:00` сразу после `window:`/`coordinator:`;
    `merge-begin s2 feat/y` → код 2, `merge slot is taken by s1`; при `window: … | quiet |` → код 2,
    `a quiet window is open`; `merge-end s2` при слоте s1 → код 2, `merge slot belongs to s1`; `merge-end c1`
    (имя координатора) → слот свободен; `merge-end s1` → слот свободен.
R8. `validate_lock`: `merging: s1 | feat/x` (2 поля), две строки `merging:`, не `is_name`, 4 поля, без `since `, плохой
    branch → код 2 `malformed machine.lock:<n>: <line>`.
R9. `wait s9` без заявки → 2 `no request of this session`; `wait s2 --timeout 0` при ЧУЖОМ окне → `TIMEOUT`, 124;
    `wait`, запущенный до `release` другим процессом, завершается кодом 0 (`MACHINE_GATE_POLL_SEC=1`).
R10. `status` при просроченном окне (`until ~23:50`, now 00:10) и одной `waiting:` → строка `OVERDUE s1 +20 min`;
     без `waiting:` и на битом замке — вывод прежний.
R11. `extend s1 30` на окне `until ~00:20` при now=00:10 → `EXTENDED until ~00:50`; `extend s2 30` при окне s1 → код 2
     `no window of this session`; продление, дающее остаток > 600 → код 2.
R12. Строка `waiting: s | heavy | x | after owner` (без `~N min`) → `promote` при now = 00:00 выдаёт `until ~01:00`; `~900 min` — `until ~01:00`;
     `~3 min` — `until ~00:03`.
R13. Ожидание tmp: чужой свежий tmp существует, `MACHINE_GATE_TMP_WAIT_SEC=1` → `request` отказывает кодом 2, tmp цел;
     tmp старше 60 с (mtime через `os.utime`) → удаляется, `request` проходит.
R13c. Чужой tmp занят, тест снимает его через ~0.5 с, `MACHINE_GATE_TMP_WAIT_SEC=5` → `request` rc 0, окно выдано
     (отличает ожидание от мгновенного отказа).
R13d. После выданного окна запущен `wait`, подложен «чужой» tmp, `wait` остановлен (TERM) → чужой tmp цел.
R15. Замок: `waiting: s2 | heavy | b | ~10 min`, окна нет (как после `close` координатора). `wait s2 --timeout 0` →
     `GRANTED until ~00:10`, rc 0, `window: s2` в замке. Тот же замок: повторный `request s2 heavy 10 b` → `GRANTED`.
R14. Старые `grant`/`close`/`status` и существующие тесты `scripts/machine_gate_tests` — зелёные без правки литералов.

#### Инъекции (предсказания записываются ДО прогона; имена тестов — после стадии 1)

(а) `release` снимает любое `window:` (без проверки владельца) → R3/R3b; (б) FIFO — брать последнюю `waiting:` → R4;
(в) убрать `set -C` (O_EXCL) → R6 (детерминированный, через `mv`) и R13; (г) убрать проверку слота/quiet в `merge-begin` → R7;
(д) пропустить `merging:` с 2 полями → R8; (е) `extend` без проверки владельца → R11; (ж) ожидание tmp → мгновенный
отказ → R13c; (з) N жёстко 30 → R2/R12; (и) арифметика без `10#` → R10-вариант с now = 09:08 и `until ~09:08`-окрестностью (литерал: окно `until ~08:50`, now 09:08 → `OVERDUE s1 +18 min`); (к) убрать `promote` из
`wait` → R15; (л) `CANCELLED` снимает чужое окно → R3b; (м) `trap` без флага
владения или без сброса после `mv` → R13 (проигравший удаляет tmp победителя) и R13d.

### Решения лида по вопросам слепого тестера (после стадии 1)

1. `QUEUED position N` при автовыдаче внутри `request`: N считается ПОСЛЕ `promote` (вышедшая в окно строка уже снята).
2. `TIMEOUT` печатается в stdout. 3. `request` без `<what...>` — usage, как `grant`.
4. `OVERDUE` в `wait`: одна строка, пока N не меняется. 5. `wait` при занятом tmp — по общим правилам `lock_edit`.
6. `release` своей заявки (`CANCELLED`) `promote` НЕ вызывает. 7. Новые команды пишут замок с LF и без ``, как `grant`.
8. `mv` при сбое: до 5 попыток всего (допустимо 5..6 вызовов `mv` у теста).

### Открытые вопросы — закрыты стадией 0

Q1 принято + правило и шаг «Merge» (координатор снимает ручные `waiting:`; в живом замке сейчас
`waiting: inspector-bottles-78 | stand …` — упомянуть в «сливаю»); Q2 «нет»; Q3 `merge-end` допускает координатора;
Q4 принять оба.
