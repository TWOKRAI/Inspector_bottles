# depends-on-readiness (В5 · задача 3.9)

**Ветка:** `feat/depends-on-readiness`
**Refs:** `plans/2026-07-06_constructor-master/plan.md` (задача 3.9), `plans/current-path/plan.md` (В5)
**Слой:** framework
**Уровень:** Senior (Opus)

## Цель

`depends_on` у процесса → порядок старта на boot по **готовности апстрима**: процесс с
`depends_on: [A]` стартует только после того, как `A` сообщил ready. Предусловие Ф8
(supervision-tree). Аддитивно, откат через feature-флаг.

## Опора (что уже есть)

- `_wait_processes_ready(names, timeout, reason)` (Ф3.2) — примитив ожидания self-reported
  ready (event + death-watch, ранний выход). **Переиспользуем как гейт волны.**
- `_wait_boot_ready()` — boot-барьер, ждёт ready всех boot-детей ПОСЛЕ старта.
- `_create_processes_from_config()` — стартует все процессы в порядке dict, разом.
- Реестр `FW_*` (`config_module/feature_flags.py`) — `ctor > env > default`.

## Дизайн

1. **Схема.** Поле `depends_on: list[str] = []` в:
   - `ProcessConfig` (`process_manager_module/topology/blueprint.py`) — рецепт/blueprint;
   - `ProcessLaunchConfig` (`process_module/configs/process_launch_config.py`) — launch-конфиг;
   - проброс в `as_generic_config` (base_kwargs при непустом) и вынос на верхний уровень
     `proc_dict` в `build()` (по образцу `restart_policy`).
2. **Boot волнами.** В `_create_processes_from_config`: если флаг ON и хоть у одного
   процесса непустой `depends_on` — построить граф, топосорт (Kahn) на волны; стартовать
   волна за волной, ПЕРЕД каждой волной >0 гейтить readiness её апстримов через
   `_wait_processes_ready(upstreams, boot_ready_timeout_s, "boot-deps")`.
3. **Guard'ы (boot не блокировать никогда):**
   - цикл в графе → ERROR + фолбэк на плоский старт (прежнее поведение);
   - `depends_on` на несуществующий/невалидный процесс или сам на себя → WARNING + ребро отброшено;
   - пустой `depends_on` везде → одна волна = бит-в-бит прежнее поведение (и порядок dict).
4. **Feature-флаг** `FW_DEPENDS_ON_BOOT_ORDER` (default **True**, инертен без `depends_on`;
   env `=0` → плоский boot). Группа «супервизор/живучесть».

## Acceptance

- [x] `depends_on` доходит от рецепта до `proc_dict` верхнего уровня — проверено ДВАЖДЫ:
  framework `assemble_proc_dicts` + **реальный прототипный** `build_headless_launcher`
  на webcam_sketch (proc_dict[seg].depends_on=['camera_0'], lines←seg, points←lines).
- [x] Топосорт: `B depends_on A` → гейт `_wait_processes_ready([A])` ВЫЗВАН между
  `A.start()` и `B.start()` (тесты chain/diamond, последовательность start/wait).
- [x] Цикл `A↔B` → ERROR, плоский фолбэк, boot не виснет (тест).
- [x] Missing/self dep → WARNING, ребро отброшено, старт идёт (тесты).
- [x] Провал create апстрима → гейт его не ждёт (`d in started`), откат ресурсов (тест).
- [x] Backward-compat: без `depends_on` порядок/поведение прежние (1528+ существующих зелёных).
- [x] `FW_DEPENDS_ON_BOOT_ORDER=0` → плоский старт даже при заданном `depends_on` (тест).
- [x] Профильные + framework-suite зелёные (16 depends_on / 1528 модульных).
- [~] Live proto boot: webcam_sketch headless **реально поднялся** (6 процессов, gui strip,
  мой depends-рецепт) и proc_dict в launcher несёт depends_on. Строку-маркер `boot:
  depends_on-порядок` из живой observability.db снять НЕ удалось — INFO фильтруется из
  консоли + батч БД не сбрасывается на graceful-stop terminate (ортогональный observability-
  плюмбинг, не логика фичи). Доказательство порядка = launcher-proc_dict + 16 юнит-тестов.

## Out of scope

- NEW-6 (стратегии рестарта rest_for_one/one_for_all) — следующий инкремент.
- Динамический `depends_on` при hot-apply/switch (сейчас только boot-порядок).
- GUI-редактор поля `depends_on`.
