# Порядок работ и контроль планов

> **Единственное место порядка.** Сверено по git 2026-10-01 (`main` = `23f872bce`); прежние сверки — 2026-09-26
> (`main` = `76cfa48f`), полосы Р и С — 2026-09-29 (`main` = `3fd359d1`); статусы планов — по
> `git merge-base --is-ancestor`, не по шапкам (шапки врали минимум в пяти планах — см. таблицу).
> **Как смотреть прогресс:** `python scripts/plans_progress/plans_progress.py --html` → `data/plans_progress.html` (шкала и ячейка на задачу по каждому плану;
> формат строки задачи — [`plans/README.md`](../README.md#формат-задачи-и-прогресс)). Счётчики считает скрипт из самих планов, здесь их вручную не пишем.
>
> Прочее в папке — справочники, порядок в них не пишется:
>
> | Файл | Что там |
> |---|---|
> | **`ORDER.md`** (этот) | приоритеты, полосы, очередь задач, таблица всех планов, открытые решения |
> | [`defects.md`](defects.md) | реестр дефектов и находок `L-*` `K-*` `W-*` `T-*` `S-*` `D-*` (ID стабильны — на них ссылаются тесты и ADR) |
> | [`backlog.md`](backlog.md) | кандидаты без плана: доказательный контур `P-*` `B-*` `N-*`, опциональные |
> | [`decisions.md`](decisions.md) | журнал решений владельца №1–15 (открытые и закрытые) |
> | [`history.md`](history.md) | прежние порядки и шапки сверок 08-10 … 09-26, досье треков наблюдаемости |
>
> `plans/QUEUE.md` оставлен указателем сюда: на него ссылаются 83 файла.

## 1. Приоритеты — решение владельца 2026-09-26

**Мерило — практическая польза:** что можно запустить, показать или измерить. Архитектура — когда её
тянет продукт (правило маятника 2026-08-18 в силе).

1. **Р — робот, `robot-protocol-v2`.** Главная полоса. Порядок 09-09 «line-sim → наблюдаемость → робот»
   выполнен в своей первой части: line-sim Ф3 и Ф5 закрыты целиком, числа P-1 есть. Робот поднимается на
   первое место.
2. **С — слои симулятора** (`line-sim-layer-editor` + остаток `line-sim`). Вторая главная полоса.
3. **И — интерфейс** (`gui-constructor`, `gui-service`) — постольку, поскольку он на пути С (вкладка
   «Симулятор») и Р (панель параметров робота, T6).
4. **Ф — фреймворк** — одна задача между продуктовыми, выбор по пользе для Р и С.
5. **Д — датасет** (`dataset-annotation`) — в паузах, пока нет доступа к роботу. Бэкенд-срез без GUI.

**Лимиты WIP.** Кодом одновременно — не больше двух полос: **Р и С**. И стартует, когда С упирается в
GUI (шаг С5). Ф — одна задача в паузе между продуктовыми. Д — когда Р ждёт железа, а С — интерфейса.

## 2. Очередь задач

`▶` — можно начинать сейчас. `⛔` — ждёт условия (указано). `🔧` — нужно железо. Номера — задачи планов.

### Р — робот ([`robot-protocol-v2`](../robot-protocol-v2/plan.md) ред. 2, брифы — [`tasks.md`](../robot-protocol-v2/tasks.md) + [`tasks-2.md`](../robot-protocol-v2/tasks-2.md))

Факт на 2026-10-01: **T0.1–T2.W в `main`** (слияние `0dcffc5e`, `Services/robot_comm/tests` — 803 passed на 09-29) и **T1.2/T1.3**
(`4fd912ccd`, 09-30): YAML
`delta_v2.yaml`, ADR RC-009..014, кодоген, инварианты, сборщик прошивки, геометрия, ядро sim v2 (mailbox, параметры, движение, стоп), модель
робота, суставы как состояние sim, окно-вид с Z и RZ. Работа идёт по команде владельца, но **формально GATE-0 не
оформлен**: шапка плана — «ждёт ревью владельца», ADR RC-009..014 — «Предложено» (О-1). Ред. 2 от 09-27 — цели
владельца: всё с ПК без перезаливки, программы точек, калибровка, несколько роботов, пакет GUI. Проба платформы
`robot/pc_platform_probe/` готова (`288a8d69`, `1ce186cb`). Передача — [`2026-09-27_robot-v2-t2j2-merged.md`](../../docs/handoffs/2026-09-27_robot-v2-t2j2-merged.md).

| Шаг | Задачи | Условие | Польза |
|---|---|---|---|
| Р0 ⚠ | Владелец: ревью ред. 2 = GATE-0 (решение О-1) — де-факто пройден (T0.1–T2.W сделаны), формально не оформлен | — | снимает «по команде владельца»; ADR RC-009..014 → «Принято» |
| Р1 ▶🔧 | **GATE-1** визит: `pc_probe.py all` (шаг 0 — Virtual Robot DRAStudio дома) → **T0.3** отчёт в YAML | проба ✓ | факты платформы вместо догадок; возможно — официальный стенд без железа |
| Р1 ∥ ✅ | **T0.1** YAML `delta_v2.yaml` (`527f471e`) → **T0.2** ADR RC-009..014 (`e00e623b`) | Р0 | одна карта вместо четырёх копий |
| Р2 ✅ | **T1.1** кодоген (`22900de7`) → **T1.2** инварианты → **T1.3** сборщик прошивки — все три в `main` (T1.2/T1.3 — слияние `4fd912ccd`, 09-30) | GATE-0 | Python, Lua и форма GUI из одного YAML |
| Р3 ✅ | **T2.0–T2.2** геометрия и ядро sim v2, **T2.K** модель, **T2.V/T2.W** окно-вид, **T2.J/T2.J2** суставы | T1.1 | робот без железа |
| Р3a ⛔ | **T2.3** сценарий, `CVT_JOB`, таймер, мост ПЧ. RED готов — `origin/red/robot-v2-t23` (`66406656`), но писался до T2.J2: точки сценариев сверить с \|J1\| ≤ 100, закрыть допущения тестеров A1–A5 | **О-10** (хостинг по правилу «фреймворк как конструктор») | сценарии и конвейер на sim v2 |
| Р3b ⛔ | **T2.4** `robot_host` v2 в симуляторе линии; тест «буква ровная» | T2.3 (или вместе, по О-10); долг **С0** закрыт (`09604ce86`) — 4 красных теста `robot_host` починены, приёмка «зелёные без правок» достижима; перед стартом — сообщение сессии С | числа P-1 на новом протоколе |
| Р4 | **T3.1–T3.2** `client_v2` → **T3.3** программы (teamlead) → **T3.4** генераторы → **T3.5** e2e | Р3 | весь цикл на ПК против sim |
| Р5 | **T4.0** стенд сухого прогона → **T4.1–T4.4** прошивка (один teamlead) → T4.5, T4.6 | GATE-1 + T0.3 | 12 находок закрыты и доказаны тестом против sim и прошивки |
| Р6 | **T5.1** `RobotDriverV2` → **T5.2** хранилище → **T5.3** команды → **T5.4** калибровка → **T5.5** плагины | Р4 | приложение с v2 без GUI (Пульт, `backend_ctl`) |
| Р7 | **T6.0–T6.5** пакет `robot.*` + ручки Пульта | Р6 + gui-constructor 1.0/1.5 | вкладки параметров, jog, программ, калибровки |
| Р8 🔧 | Ф7 bring-up (чек-лист firmware-architecture §11) | Р5, Р6 | поведенческое доказательство |

Смежные планы получили обратные ссылки 2026-09-27: `robot-place-pose` (ось «R» → «RZ», P3 на v2),
`letter-robot-cycle` и `draw-mode-rework` (переписываются на программы v2), `camera-robot-calibration`
(форма телеметрии сохраняется), `device-tree-recipe` (данные робота вне `devices.yaml`), `line-sim` (T2.4),
`gui-constructor` и `frontend-constructor` (потребитель пакетов и форм).

### С — слои симулятора ([`line-sim-layer-editor`](../line-sim-layer-editor/plan.md), [`line-sim`](../line-sim/plan.md))

Факт на 2026-10-01: контракт слоя 3.1a в коде (`Services/line_sim/{interfaces.py, core/preset.py, core/layered_object.py}`).
line-sim Ф0–Ф3 и Ф5 закрыты (5.5 DEFERRED), Ф6: 6.1 и 6.2 закрыты. Редактор — APPROVED 09-27: HTML и Qt над одними
бэкенд-командами. 6.1 и 1.2h влиты в `main` 09-29 (`2d680cfb`, `f8d39a89`); вся ветка `feat/line-sim-layer-editor` (1.3h-a…d) — в `main`
(`79dda66a9` 09-29, `c2a3b876a` 09-30).

| Шаг | Задачи | Условие | Польза |
|---|---|---|---|
| С1 ✅ | редактор **1.0** [DONE 09-27] (дефект С2): `ScenePreset.from_yaml` делает пути абсолютными, `to_yaml` пишет путь этой машины | — | пресет переносится Mac ↔ ПК ↔ Orin |
| С2 ✅ | редактор **1.1b** [DONE 09-27] диск-буква из слоёв: слой класса, цвет (и ахроматичный), шрифты; **1.1** бутылка — отложена (нет картинок) | С1 | объект любой сложности из слоёв; диск и буква варьируются раздельно |
| С3 ✅ | редактор **1.2a** [DONE 09-27]: команды пресета с ревизией по образцу `recipe.*`, превью по seed, горячая подмена пресета в `scene_source` — **закрыть до T2.4 робота** | С2 | слои правятся на живой ленте без рестарта |
| С4 ✅ | line-sim **6.1** [DONE 09-28] — 6.1a команды потока, брака, паузы у `scene_source`; 6.1b те же ручки на веб-пульте готовым механизмом маршрутов. В `main` — `2d680cfb` | — | сценарии испытаний инспектора и робота |
| С5 ✅ | редактор **1.2h** [DONE 09-29] HTML-клиент на `pult_web`: маршруты `preset.*`, форма из пресета, превью, undo, код ошибки в HTTP-статус. В `main` — `f8d39a89` | С3 | редактор мышью без ожидания И2–И5 |
| С5a ✅ | редактор **1.3h-a** [DONE 09-29] команда `preset.layout` + маршрут `/api/preset/layout`: слои пресета по отдельности с `origin_px` (`d6225d81`, `82fc47db`, ревью APPROVE_WITH_NITS). В `main` — слияние `79dda66a9` | С5 | бэкенд для канвы |
| С5b ✅ | редактор **1.3h-b** [DONE 09-29, принята владельцем на живом стенде] канва мышью на странице `pult_web`: перетаскивание готовых спрайтов, выбор по альфе, одна правка = одна запись undo; B1 (фокус) найден в живом Chrome. В `main` — `79dda66a9` | С5a | редактор «как в Paint» без ожидания Qt |
| С5c ✅ | редактор **1.3h-c** [DONE 09-29] слои и PNG: `preset.sprites`, добавить / заменить / удалить / выше / ниже; F1/F2 из живого Chrome закрыты (`d82161e4`), ревью APPROVE_WITH_NITS. В `main` — `79dda66a9` | С5b | состав слоёв мышью |
| С5d ✅ | редактор **1.3h-d** [DONE 09-30] загрузка PNG из браузера (`preset.sprite_put`), ревью ит.2 APPROVE_WITH_NITS, живой Chrome пройден. В `main` — слияние `c2a3b876a` | С5c | свои PNG-слои без правки файлов руками |
| С0 ✅ | долг [DONE 09-29]: 10 стабильно красных тестов sim + 12 в `robot_comm` + флики delay_ms, jog, drop, p6, pult_web 10053 — починены по причинам, без skip (`09604ce8`, `25cbd7e3`, `2272b466`); передача — [`2026-09-29_failing-tests-and-b1-handoff.md`](../../docs/handoffs/2026-09-29_failing-tests-and-b1-handoff.md) | — | зелёная база для приёмки T2.4 |
| С6 ⛔ | редактор **1.2b** Qt-вкладка `sim.*` → **1.3** канва; 2.1 налив — по вопросу 1 плана | С3 + И3 → И5 | тот же редактор внутри GUI, паритет с HTML |
| — | line-sim Ф4 камера — файл под ред. 1, переписать перед исполнением; 5.5 — по вопросу 1 line-sim | ⛔ | — |
| С7 | **фронт полосы С — план [`layer-render`](../layer-render/plan.md)** (DRAFT; один механизм слоёв для сима и генератора обучения, буквы — первый потребитель). Волна 1 (Task 1.1 стек фона ∥ 1.2 `--gap-alpha`) влита в `main` 2026-10-01 (`4acca4687`); волна 2 ({1.3 ∥ 2.1}) ждёт ответа владельца | — | сим и обучение на одном механизме слоёв; закрывает 0.1 `letters-retrain` |

Решения владельца 2026-09-27 (О-2 по редактору, О-3, О-5) и новые задачи 1.0/1.1b/1.2a/1.2h — в плане
редактора, раздел «Решения 2026-09-27». Ветка `feat/line-sim-layer-editor` влита в `main` (`79dda66a9`, `c2a3b876a`), worktree `.claude/worktrees/ls-layer`.

### И — интерфейс ([`gui-constructor`](../gui-constructor/plan.md), [`gui-service`](../2026-09-22_gui-service/plan.md))

| Шаг | Задачи | Условие |
|---|---|---|
| И1 ▶ | gui-service **1b.2c** вердикт бэкенда до формы; ~~1b.2d~~ DONE 10-02 (правила описанием + откат отвергнутого значения, `task-1b2d.md`) | — (заполнитель пауз) |
| И2 | gui-constructor Ф1: **1.0** правила слоёв → 1.1 характеризация (**вход: ~20 красных тестов фронта** sandbox/dashboard на main 09-29, видел ревьюер, не разбирались — сначала отделить давние от регрессий) → 1.2 разборка `run_gui` (**`app.py`**) → 1.3 → 1.4 → 1.5 | approve плана (О-2); до 1.3 — явные Р-A/B/C/D/F |
| И3 | gui-constructor **2.1** оболочка `host/` → **2.2** `inspector.classic` → gui-service **1.4** `apps/gui_client` → 2.4 `minimal_gui` | И2. 2.3 (minimal_app) и 4.1 (KnobAddress) — заполнители в любой момент |
| И4 | gui-service **1b.2b** (`app.py` — строго после И2) → 1b.3 → 1b.4 auth | И2 |
| И5 | gui-constructor **3.1 ∥ 3.2** + gui-service **3.1/3.2** → **3.3** пакет `sim.*` → **3.4** черновик + ревизия | И3 |
| И6 | gui-constructor Ф4 Пульт: 4.1 → 4.4 | И3 |

### Ф — фреймворк (одна задача между продуктовыми, по пользе для Р и С)

| # | Задача | План | Для чего |
|---|---|---|---|
| Ф1 | Ф4: **4.0** разведка ✅ → **4.1** claim check ✅ (`dd1491e3`, 4.1-fix `e70c05df`, 09-29) → 4.4, 4.5, 4.6, 4.8a, 4.7a, 4.7c в `main`; дальше **4.7b** один режим shm → **4.7d** overflow → живой A/B (4.7c — `375bbb4b2`, ADR-173, 10-01) | [`transport-single-policy`](../transport-single-policy/plan.md) Ф4 | С: симулятор — второй поставщик кадров; разблокирует lifecycle Ф2 |
| Ф2 | **4.5** `ServiceContext`; миграция `robot_comm`, `vfd_comm`, `modbus` названа в задаче | [`observability-closure`](../observability-closure/plan.md) | Р: `robot_comm` дал 0 записей ошибок на 2336 строк журнала |
| Ф3 | **2.1** развести глаголы `record_metric` (counter/gauge по сборке) | [`framework-architecture-rework`](../framework-architecture-rework/plan.md) | Р: до того, как `client_v2` начнёт публиковать метрики; от codemod не зависит |
| Ф4 | Условия CTO: ~~юнит-тест severity~~ (DONE 09-29, `97bdcf9b`), флейк `children_exit_hook`, прогон `--backend-live`; **ещё два флейка graceful stop на Windows** (давние, замер 09-29: база 6/12 и 5/12, main 1/8 и 1/8) — `test_graceful_stop_acceptance::…test_message_to_live_reader_is_delivered_before_exit`, `test_pm_marks_gone_reader_hazards::test_stop_many_unblocks_writer_of_dead_reader_gracefully`; затем Ф2 перемер | [`lifecycle-stop-ownership`](../lifecycle-stop-ownership.md) | Ф2 перемер ⛔ Ф1 |
| Ф5 | Ф1 — четыре P0 «правда не агрегируется» | [`backend-ctl-review-remediation`](../backend-ctl-review-remediation.md) | Р: отладка mailbox/ACK инструментом, который не прячет потери |
| Ф6 | остаток closure: 4.3b → 4.6 нейтральный словарь → 4.15 хоп-лаг → 4.14 ретенция по байтам; 4.3, 4.12, 4.16; Ф5 | observability-closure | С: сим как второе приложение не наследует словарь инспектора |
| Ф7 | 2.5, Ф3–Ф4 | [`otel-export`](../otel-export.md) | после closure 4.3b |
| Ф8 🔧 | D1: проверка lifecycle 1.5 на Linux/Orin; gui-service на Linux не проверялся; **L-7** (`defects.md`) — сторож смерти родителя на Windows не срабатывает никогда, на редкой ветке шлёт Ctrl+C — чинить вместе с D1 (один механизм, две ОС), железо для Windows-части не нужно | lifecycle-stop-ownership | Р и линия, если хост — Orin (О-6) |
| — | Окно codemod (rework Ф3–Ф6) → frontend-constructor Блок В | rework | ⛔ решение Р-1 rework и естественная пауза; условия входа — [`history.md`](history.md), «Жёсткие условия» |

### Д — датасет ([`dataset-annotation`](../dataset-annotation/plan.md)) — в паузах

Д1 ▶ **1.1** вертикальный срез (DatasetStore + фрагмент `topology/dataset.yaml`) → 1.2 → 1.3 файлы по id → 1.4
(approve плана, О-2). Д2 — 4.3 сплит + 4.4 экспорт YOLO/zip. Д3 (Ф2 разметка) ⛔ gui-constructor 1.0/Ф1.
Д4 (Ф3 сбор с линии) — живой стенд 8765. Канал «файлы по id» (Д 1.3) нужен и редактору слоёв — кто
первый, решается при постановке С6.

## 3. Правила исполнения

- **Канон задачи:** тестер в worktree до кода → реализация → инъекции лида → стенд → ревьюер синхронно.
- **Живой стенд — один трек на бэкенд:** 8765 инспектор, 8766 симулятор. Пульт входит в окно обоих.
  Логи двух приложений — в разные `MULTIPROCESS_LOG_DIR`.
- **`frontend/app.py` — один писатель:** gui-constructor 1.2 → gui-service 1b.2b строго по очереди.
- **Р и С в разных файлах**, кроме `Plugins/sim/robot_host` (задача Р3+) — её не вести параллельно с С3; С3 закрывается до T2.4 (договорённость сессий 2026-09-27).
- **Любой план, живущий дольше дня, получает строку в таблице ниже.** Новый план ставится среди соседей
  (память `a-new-plan-must-be-placed-among-its-neighbours`).
- **Сверка — по git, не по шапке.** Изменил статус — обнови строку и дату в заголовке.
- **Прототип не обрастает универсальным:** вынос во framework / `Services` / `Plugins` — по тесту слоя.
- Планировать не дальше одной фазы вперёд. Сессия целиком в планах — сигнал, а не работа.

## 4. Контроль планов — все 58 планов `plans/`

Колонка **Полоса** — буква из §2. **Статус** сверен git'ом 2026-09-26; строки Р и С — 2026-09-29; строки, тронутые 2026-10-01, — по `main` = `23f872bce`.
Счёт: `ls plans/` без `queue/`, `_archive/`, `README.md`, `QUEUE.md` (файлы и каталоги планов).

### 4.1 Активные — в работе или следующие

| План | Полоса | Статус | Следующий шаг |
|---|---|---|---|
| [robot-protocol-v2](../robot-protocol-v2/plan.md) | Р | T0.1–T2.W в `main` (`0dcffc5e`), T1.2/T1.3 в `main` (`4fd912ccd`); GATE-0 не оформлен ⚠ шапка «ждёт ревью» | О-10 → T2.3 |
| [line-sim-layer-editor](../line-sim-layer-editor/plan.md) | С | APPROVED 09-27; 1.0, 1.1b, 1.2a, 1.2h, 1.3h-a…d в `main` (`79dda66a9`, `c2a3b876a`); осталось 1.2b → 1.3 (Qt, ждёт И3), 1.1 DEFERRED, 2.1 необязательно | 1.2b после И3 |
| [line-sim](../line-sim/plan.md) | С | Ф0–Ф3, Ф5 DONE в `main`; Ф6: 6.1 в `main`, 6.2 DONE 09-27; Ф4 на переписывание; 5.5 DEFERRED. Метка `[BLOCKED]` у 1.1 устарела | 6.3 ROI мышью: условие ORDER «после 1.3h-b» снято (`79dda66a9`), но шапка `phase-6-pult-gui.md` держит 6.3 DEFERRED до GUI-загрузки generic-приложений — расхождение, снять при постановке |
| [gui-constructor](../gui-constructor/plan.md) | И | DRAFT, ревью CTO: ACCEPT WITH CONDITIONS | approve → 1.0 |
| [2026-09-22_gui-service](../2026-09-22_gui-service/plan.md) | И | APPROVED ред. 2; 1.1–1.3b, 1b.1, 1b.2a, 1b.2b-pre, 1b.5, 1b.2d (10-02) в `main` | 1b.2c |
| [frontend-constructor](../frontend-constructor/plan.md) | И | Блок А DONE; Ф4/Ф5 ушли в gui-constructor; Блок В ⛔ окно codemod | — |
| [transport-single-policy](../transport-single-policy/plan.md) | Ф | Ф4: 4.0, 4.1, 4.4, 4.5, 4.6, 4.8a (`95093b966`), 4.7a, 4.7c (`375bbb4b2`, ADR-173) в `main`; 4.8c (бенч из GUI, спека `d3a1c3d11`) — кода нет, владельцем не подтверждена | 4.7b → 4.7d → живой A/B |
| [pipeline-node-timing](../pipeline-node-timing.md) | И | заведён 09-30 (владелец): время узлов в GUI; дефекты PC-1..4; T1 DONE (`b611e7a7`, слияние `5a83c232` 10-01) | T2 — время узла на графе |
| [observability-closure](../observability-closure/plan.md) | Ф | Ф0–Ф3 DONE, Ф4: 4.4, 4.11, 4.13 DONE; ветка в `main` | 4.5 / 4.3b |
| [lifecycle-stop-ownership](../lifecycle-stop-ownership.md) | Ф | Ф1 DONE (merge `ae0eebde`), CTO с условиями | юнит-тест severity |
| [backend-ctl-review-remediation](../backend-ctl-review-remediation.md) | Ф | не начат; Ф3 сделана в gui-service 1.3a, 3.2 = `8fae4034` | Ф1 |
| [otel-export](../otel-export.md) | Ф | Ф0–Ф2 почти целиком, Ф3 наполовину; в `main` | 2.5 |
| [framework-architecture-rework](../framework-architecture-rework/plan.md) | Ф | DRAFT ред. 3, ревью 7/10, решения Ф0 не приняты | 2.1 отдельно; остальное ⛔ Р-1 |
| [dataset-annotation](../dataset-annotation/plan.md) | Д | DRAFT, ревью CTO: ACCEPT WITH CONDITIONS | approve → 1.1 |
| [code-reader-sdk](../code-reader-sdk.md) | — | дочерний к qr-code-reader (трек B); Task 6.1–6.3 DONE, 6.3 — 09-29 (`909ae5c0f` спека, `f99835753` плагин, `f25ad852b` итог стенда) | простаивает: следующие пункты без номера — `Services/code_reader/STATUS.md:243` («Открыто по коду»: защита от склейки, пустой `bad_code_text`, `last_error` после переподключения) |
| [layer-render](../layer-render/plan.md) | С | волна 1 (1.1 ∥ 1.2) в `main` (`4acca4687`); волна 2 ждёт владельца | волна 1 → 1.3 (фон слоями, границы в `.sentrux/rules.toml`) |
| [letters-retrain](../letters-retrain/plan.md) | — | IN PROGRESS: 0.2 (`50df705f`), 0.3 (`5ed21461`, `87d50a0f`) в `main`; 0.1 передана в layer-render; 0.4 ждёт layer-render 1.3. Вне полос §2 — задача владельца 10-01 | 0.4 базовая линия сети на исправленном симе |
| [qr-code-reader](../qr-code-reader.md) | — | Шаг 0 (ingest мануалов) DONE; правка по документам закрыта. Вне полос §2 — новое железо | Ф0 на стенде: IDMVS → ModBus Mode, три Space/Offset/Size, версия прошивки |

### 4.2 Ждут триггера — не трогать до условия

| План | Остаток | Триггер |
|---|---|---|
| [robot-place-pose](../robot-place-pose.md) | P3 + прошивка укладки (в v2 это `CVT_JOB` с place-аргументами) | Р4 — делать на v2 |
| [robot-calibration](../robot-calibration.md) | hardware E2E; ops переедут на v2 | Р8 |
| [camera-robot-calibration](../camera-robot-calibration.md) | Часть 2 px→mm | 🔧 железо |
| [device-tree-recipe](../device-tree-recipe.md) | Фаза E: удалить `data/devices.yaml` — **конфликт с v2**, который хранит там tool-state, teach-точки, `robot_params` | решение О-7 до Р7 |
| [word-layout](../word-layout.md) | Phase 3 (проводка `robot_io` на железе), Phase 4 | 🔧 железо |
| [storage-stack-embedded-first](../storage-stack-embedded-first.md) | этапы 1–3 (поглотил `sql-insert-many-atomic`; дефект `base_repository.py:80` — вставка без транзакции — жив) | долгие прогоны сима / нужда в ретенции |
| [2026-07-06_constructor-master](../2026-07-06_constructor-master/plan.md) | H.3 Registers⇄StateStore, H.5, H.6 закрытие; два месяца без движения | закрыть таблицей по H.6; H.3 — отдельным планом по нужде |

### 4.3 Закрыты или поглощены — кандидаты в `_archive/` (решение О-8)

Сверено git'ом: ветки в `main` или план поглощён. **Шапка врёт** — помечено ⚠.

| План | Факт |
|---|---|
| [lifecycle-graceful-stop](../lifecycle-graceful-stop.md) | DONE, долги → lifecycle-stop-ownership |
| [observability-roadmap](../observability-roadmap.md) | DONE как управляющий; этап 9 (fingerprint ошибок, stderr, JSON-сток) → [`backlog.md`](backlog.md) |
| [observability-unified-routing](../observability-unified-routing.md) · [observability-review-remediation](../observability-review-remediation.md) · [observability-f1-hardening](../observability-f1-hardening.md) | DONE / DONE / SUPERSEDED → roadmap |
| [observation-port](../observation-port/plan.md) | DONE Ф0–Ф5 ⚠ шапка «черновик» |
| [observability-dx](../observability-dx.md) | не начат, треки поглощены closure (А.2 = 4.5, В = 4.3); Д.1 `run_all_gates.py` → backlog |
| [telemetry-stage6](../telemetry-stage6.md) | DONE (`ff0308f4`); переприёмка гейта Ф6 = closure 5.4 |
| [telemetry-coherence-remediation](../telemetry-coherence-remediation.md) · [telemetry-dashboard](../telemetry-dashboard.md) · [telemetry-publish-control](../telemetry-publish-control.md) | DONE |
| [telemetry-delivery-simplification](../telemetry-delivery-simplification.md) · [telemetry-pull-on-demand](../telemetry-pull-on-demand.md) | SUPERSEDED |
| [gui-telemetry-read-model](../gui-telemetry-read-model.md) | DONE 07-16 (ADR-136) |
| [truth-holes-closure](../truth-holes-closure.md) · [backend-ctl-proof-discipline](../backend-ctl-proof-discipline.md) | DONE |
| [supervisor-alerting](../supervisor-alerting.md) · [supervisor-backoff-jitter](../supervisor-backoff-jitter.md) · [supervisor-strategies](../supervisor-strategies.md) · [depends-on-readiness](../depends-on-readiness.md) | DONE |
| [framework-layer-grouping](../framework-layer-grouping/plan.md) | SUPERSEDED → rework; ветка `refactor/framework-layer-grouping` — 3 коммита не в `main`, проверить перед удалением |
| [2026-06-05_sql-insert-many-atomic](../2026-06-05_sql-insert-many-atomic.md) | SUPERSEDED → storage-stack |
| [2026-05-29_constructor-maturity](../2026-05-29_constructor-maturity/plan.md) · [current-path](../current-path/plan.md) | SUPERSEDED: constructor-master и эта очередь |
| [pipeline-color-inspection](../pipeline-color-inspection.md) | ⚠ DONE 06-01 (`5a13f24f`, `6985ac7e`, `4bf240da`), прежняя очередь писала «отложено» |
| [proto-frontend-carve](../proto-frontend-carve.md) | SUPERSEDED → frontend-constructor; по своей шапке — справочник, не архив |
| [pult-control-panel](../pult-control-panel.md) | Phase 1–3 DONE, Phase 4 — доки |
| [line-sim-belt-look](../line-sim-belt-look/plan.md) | DONE: 1.1–1.3 (09-30), слияние `c5168660d` в `main` |
| [sim-lateral-offset](../sim-lateral-offset.md) | ⚠ DONE 10-01 (`97dcfed0a`), шапка плана ещё «IN PROGRESS» |
| [undo-restores-selection](../undo-restores-selection.md) | DONE 09-30 (Task 1.1, `ddc610ddd`) |
| [letter-robot-cycle](../letter-robot-cycle/plan.md) | выставочный план 06-16; RETURN/TOOLCHANGE в v2 — сценарии; остаток переписать под v2 |
| [draw-mode-rework](../draw-mode-rework/plan.md) | A, C, D DONE; B-хвост (`clamp_to_zone` в коде есть) проверить; механика рисования в v2 → T3b.2 |
| [dataset-circle-capture](../dataset-circle-capture.md) | Часть 1 DONE; Часть 2 (hand-eye) ≈ camera-robot-calibration |

**Устаревшие строки и ветки** (чистка — вместе с О-8): `plans/README.md` — ledger с датами 09-20 и 0/0 у половины
планов, пересобрать `plans_ledger.py status`; ветки `feat/robot-protocol-v2` (в `main`), `feat/robot-comm-sim-monitor`
(перенесена как `dfdb1891`), `docs/line-sim-red4-input` (вход ред. 4, по сути заменён 09-26), `test/line-sim-task-*`,
`test/gui-service-*` (RED-остатки); старые worktree `gui-1b2b-pre*`, `lso-1.4…1.6-*`, `lso-hotfix`.

## 5. Открытые решения владельца

Новые (2026-09-26). Старые открытые — №2, 2b, 3–9, 10 (worktree), 13–15 — в [`decisions.md`](decisions.md).

| # | Решение | Блокирует | Рекомендация |
|---|---|---|---|
| О-1 | Старт `robot-protocol-v2`: ревью ред. 2 (GATE-0) — де-факто принят (работа до T2.W сделана), осталось оформить | ничего; гигиена | шапку плана и ADR RC-009..014 перевести в «Принято» |
| О-10 | Хостинг sim v2 по правилу «фреймворк как конструктор» (09-27): T2.3 отдельно, потом T2.4 — или T2.3+T2.4 одним шагом на процессах, воркерах и роутере фреймворка | T2.3, T2.4 | одним шагом: бриф T2.3 (`sim_robot.py --protocol v2` отдельным Modbus-сервером) писался до правила |
| О-2 | Approve `line-sim-layer-editor` — **принято 2026-09-27**; `gui-constructor`, `dataset-annotation` (+ их открытые вопросы) — открыто | И2, Д1 | approve; Д — в паузах |
| О-3 | ~~Какой слой зависит от класса~~ — **закрыто 2026-09-27:** отмеченный слой, сейчас буква (диск и буква — раздельные слои, редактор 1.1b) | — | — |
| О-4 | `draw_circle`/`square` на v2: полилиния или отказ | Р4 | полилиния с ПК — принято в ред. 2 (T3.4) |
| О-5 | ~~HTML или Qt~~ — **закрыто 2026-09-27:** оба, тонкими клиентами одних бэкенд-команд; HTML первым (редактор 1.2h), Qt — после И3 (1.2b) | — | — |
| О-6 | Хост робота — Orin или ПК | Ф8, Р8 | — |
| О-7 | `data/devices.yaml`: удалять (device-tree Фаза E) или хранить там состояние v2 | Р7 | хранить; Фазу E сузить |
| О-8 | Перенос ~25 закрытых планов в `_archive/` (расширение №9); ссылки чинить скриптом | нет, гигиена | да, одним коммитом через `plans_ledger.py close` |
| О-9 | Поправить корневой `CLAUDE.md`: Ultralytics не установлен и не в `pyproject.toml` | нет | да |

## Прогресс планов (генерирует скрипт)

Блок между маркерами пишет только `python scripts/plans_progress/plans_progress.py --sync-order` (лид, в `main`, в точке слияния); руками не править. На `main` `--check` краснеет, если блок устарел. Порядок лида при слиянии: `git merge --no-ff --no-commit <ветка>` → `--sync-order` → `git add plans/queue/ORDER.md` → `git merge --continue` (на ветках `--sync-order` не запускать).

<!-- progress:begin -->
- robot-protocol-v2 — 5 из 21 · 24%
- line-sim-layer-editor — 0 из 9 · 0%
- line-sim — 24 из 28 · 86%
- gui-constructor — 0 из 21 · 0%
- 2026-09-22_gui-service — 10 из 21 · 48%
- frontend-constructor — 0 из 24 · 0%
- transport-single-policy — 1 из 31 · 3%
- pipeline-node-timing — 0 из 4 · 0%
- observability-closure — 26 из 52 · 50%
- lifecycle-stop-ownership — 6 из 9 · 67%
- backend-ctl-review-remediation — 0 из 16 · 0%
- otel-export — 9 из 21 · 43%
- framework-architecture-rework — 0 из 11 · 0%
- dataset-annotation — 0 из 17 · 0%
- code-reader-sdk — 2 из 3 · 67%
- layer-render — 5 из 20 · 25%
- letters-retrain — 2 из 3 · 67%
- qr-code-reader — 0 из 19 · 0%
- robot-place-pose — 0 из 0
- robot-calibration — 0 из 0
- camera-robot-calibration — 0 из 0
- device-tree-recipe — 0 из 0
- word-layout — 0 из 0
- storage-stack-embedded-first — 0 из 11 · 0%
- 2026-07-06_constructor-master — 0 из 0
- lifecycle-graceful-stop — 1 из 2 · 50%
- observability-roadmap — 0 из 0
- observability-unified-routing — 21 из 32 · 66%
- observability-review-remediation — 7 из 20 · 35%
- observability-f1-hardening — 0 из 16 · 0%
- observation-port — 22 из 24 · 92%
- observability-dx — 0 из 0
- telemetry-stage6 — 11 из 13 · 85%
- telemetry-coherence-remediation — 11 из 12 · 92%
- telemetry-dashboard — 6 из 6 · 100%
- telemetry-publish-control — 10 из 10 · 100%
- telemetry-delivery-simplification — 2 из 6 · 33%
- telemetry-pull-on-demand — 0 из 0
- gui-telemetry-read-model — 11 из 11 · 100%
- truth-holes-closure — 14 из 15 · 93%
- backend-ctl-proof-discipline — 8 из 16 · 50%
- supervisor-alerting — 0 из 0
- supervisor-backoff-jitter — 0 из 0
- supervisor-strategies — 0 из 0
- depends-on-readiness — 0 из 0
- framework-layer-grouping — 0 из 0
- 2026-06-05_sql-insert-many-atomic — 0 из 5 · 0%
- 2026-05-29_constructor-maturity — 0 из 1 · 0%
- current-path — 0 из 0
- pipeline-color-inspection — 0 из 0
- proto-frontend-carve — 0 из 6 · 0%
- pult-control-panel — 0 из 0
- line-sim-belt-look — 0 из 3 · 0%
- sim-lateral-offset — 1 из 1 · 100%
- undo-restores-selection — 1 из 1 · 100%
- letter-robot-cycle — 0 из 6 · 0%
- draw-mode-rework — 0 из 0
- dataset-circle-capture — 0 из 0
- 2026-10-02_plans-progress-dashboard — 4 из 10 · 40%
в архиве: 86
<!-- progress:end -->
