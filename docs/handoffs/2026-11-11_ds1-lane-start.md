# Старт полосы DS-1 (первая волна) — промпт для нового чата

Вставить в новый чат целиком. Первая строка — название вкладки.

```
ВКЛАДКА: Полоса DS-1 · первая волна 0.1/1.1a/1.1b/2.1 истина сима в sidecar
ROLE: lead of lane DS-1, plan plans/2026-11-11_dataset-sidecar-truth/plan.md (утверждён 2026-11-11, contract.lock).
  Ветка плана docs/ds-1-sidecar-truth (не влита в main), worktree /Users/twokrai/Project_code/Inspector_bottles_ds1.
READ FIRST: plan.md, design.md, amendments.md, tasks/1.1a.md, 1.1b.md, 2.1.md, 0.1.md; этот файл.
GOAL: сим пишет журнал истины, frame_saver пишет в .json ответ сети, точку съёма и source, ml_inference отдаёт
  model_id и angle_symmetry, и всё это готово к сведению (1.1c) на данных стенда 0.1.
ACCEPTANCE: литералы REDS в задачах 1.1a (8 тестов), 1.1b (6), 2.1 (3); существующие тесты модулей зелёные без правки;
  break-injection по предсказаниям лида; отчёт docs/reports/2026-11-11_ds1_<задача>.md по шаблону.
PIPELINE: как в .claude/CLAUDE.md «Task launch convention»; stage 0 по планам уже пройден (r1, r2), по задачам не повторять.
  Порядок: слепой tester (по ACCEPTANCE и design.md §4, без DESIGN-шагов и без кода плагинов; один раз на механизм, до кода,
  в worktree от коммита до реализации) → developer sonnet (REDS → GREEN) → break-injection → reviewer sonnet stage 5.
  Первая волна: 1.1a, 1.1b, 2.1 параллельно, не больше трёх писателей, у каждого свой worktree от docs/ds-1-sidecar-truth
  (ветки feat/ds1-1a, feat/ds1-1b, feat/ds1-2-1). Субагенты только диагностика и файлы; коммитит лид (protect-branch).
  Task 0.1 (разведка стенда: задержка, e_capture, имена классов, байты на вырез, п.7 доля верных) — investigator,
  нужно окно heavy/stand через machine_gate.sh; отчёт возвращается сообщением, файл reports/0.1.md пишет лид.
  Task 1.1c и 2.3 — только после результатов 0.1, 1.1a, 1.1b, 2.1.
BOUNDARIES: твои файлы — Plugins/io/frame_saver, Plugins/sim/scene_source, Services/ml_inference, Services/line_sim/tools,
  рецепт letter_robot_sim (только 2.3). Чужое: Атлас (ветка docs/atlas-pilot-1111, отдельный чат) не трогать; plans/queue/ORDER.md
  и backlog.md правит сессия Атласа; plans/2026-11-11_draw-universal утверждён (contract.lock) — править только через
  amendments.md + plans_ledger.py amend. Правка чужого теста test_letter_robot_sim_diff.py разрешена DS-В3, только в 2.3.
  Ловушка: основной чекаут Inspector_bottles может стоять на чужой ветке; перед коммитом git branch --show-current; работа в worktree.
LOAD: координатор — inspector-bottles-a2. Первое сообщение ему — имя своей сессии (первая строка твоего ListAgents).
  Каждая тест/стенд-команда через gate: bash "$(git rev-parse --path-format=absolute --git-common-dir)/../scripts/machine_gate.sh" ...
  (абсолютный путь основного чекаута); heavy — только в своём окне (request/wait/release); слияние — merge-begin/merge-end.
  Имя сессии передавать в каждый бриф агента.
COMMITS: Conventional Commits + Why:/Layer:/Refs: plans/2026-11-11_dataset-sidecar-truth/plan.md; stage явных путей;
  заголовок ≤ 72; слияния — git merge --no-ff -F <файл>. Перед слиянием в main: rebase на main, validate.py + тесты модулей.
LIMITS: 2 итерации на петлю, на третьей — вверх (teamlead); вопросы владельцу — списком, не угадывать.
REPORT: по-русски, числа, непустое «что осталось открытым», таблица agentId; по задаче — файл отчёта; в конце — handoff и /clear.
LESSONS: (1) порог оракула метки 0,7 и формула --time-offset-ms — оценки, не замеры: проверить в 0.1/2.3; (2) расчёт «9 строк enc»
  и ecap == 500 сделан арифметикой, не запуском — слепой tester должен подтвердить; (3) lint-хук требует в брифе
  DESIGN/FILES/REDS/REPORT или BRIEF-OVERRIDE: <причина> (для слепого tester и investigator — override).
```

## Решения владельца (приняты 2026-11-11, «давай»)

DS-В1 журнал истины в симе + офлайн-сведение; DS-В2 порог угла 5,0°; DS-В3 допуск узла `dataset_saver` в тесте
рецепта сима (только Task 2.3); DS-В4 реальные кадры (2.2, 2.4, 3.1, 3.2) в DEFERRED.
