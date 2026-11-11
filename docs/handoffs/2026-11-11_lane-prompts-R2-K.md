# Стартовые промпты полос Р2 и К (координатор inspector-bottles-a2, 2026-11-11)

Состояние сверено по `main` (`15546209f`), а не по `ORDER.md`: он отстаёт. Вставлять в новый чат целиком; первая строка — вкладка.
Полоса DS-1 — отдельный файл `2026-11-11_ds1-lane-start.md`.

## Что в `main` уже есть (расхождения с ORDER.md)
- Р2: T5.3e.5 влита `9eb384633`, T1.4 `558a7c138`, T5.5 `009e35f86` (REVIEW-5 `cto` WITH CONDITIONS), T5.4 `9afe828be`.
  Строки 7, 8, 9 ORDER.md закрыты. Статусы `[PENDING]` в `plan.md:139` и `tasks/T5.5.md:3` устарели.
  Свободно по программе: T5.3e.6 (вкладка робота v2; стадия 0 пройдена, 2 раунда). T0.3/T4.0 ждут визита к роботу (GATE-1).
- К: влита только W1 (W1a `2b168d558`, W1b `c5f544611`). W2 (1.6, 1.8, 2.1, 2.2) не начата: коммитов нет.

## Полоса Р2 — T5.3e.6

```
ВКЛАДКА: Полоса Р2 · T5.3e.6 вкладка робота v2: дельты status и срок park
ROLE: lead of lane Р2, plan plans/robot-protocol-v2/plan.md, Task T5.3e.6 «вкладка робота v2: листовые дельты status.** и срок итога park»
  (после T5.3e.5 `9eb384633`, T5.4 `9afe828be`; статус из git main, не из шапок плана).
READ FIRST: docs/handoffs/2026-11-09_R2-T5.3e.6.md; plans/robot-protocol-v2/tasks/T5.3e.6.md, .acceptance.md (A1–A13, для слепого tester),
  .injections-predictions.md (J1–J14, tester НЕ читает), .neighbours.md.
GOAL: вкладка робота на v2 принимает листовые дельты `status.**` и показывает итог park в срок: QTimer.singleShot + токен _park_gen,
  запас 3,0 с + timeout_s из ответа robot_park, fallback 60 с.
ACCEPTANCE: литералы A1–A13; инъекции J1–J14 по предсказаниям лида (до прогона); Opus не нужен, reviewer stage 5 sonnet.
PIPELINE: как в .claude/CLAUDE.md «Task launch convention»; стадия 0 уже пройдена (2 раунда, третьей итерации нет). Дальше стадия 1: слепой tester
  в worktree .claude/worktrees/robot-v2-t53e6-tester (ветка tests/robot-v2-t53e6-blind, база 7ccb4d716; в нём только acceptance) —
  агент a02967f5e4ace2a05 остановлен до первой записи, можно возобновить SendMessage или запустить заново; затем developer sonnet
  (слой prototype: robot/controller.py + robot/tests/test_robot_controller.py), инъекции, reviewer sonnet stage 5, слияние --no-ff -F файл.
  Субагенты только диагностика и файлы; коммитит лид (protect-branch).
BOUNDARIES: файлы вкладки робота. Не трогать: Services/device_hub/* (T5.4 влита), plans/queue/ORDER.md (правит сессия Атласа), calibration/controller.py:117 и
  vfd/controller.py:126 (тот же дефект подписки — отдельная задача после T5.3e.6, вопрос В3). Основной чекаут может стоять на чужой ветке:
  работа в worktree, перед коммитом git branch --show-current.
LOAD: координатор — inspector-bottles-a2. Первое сообщение ему — своё имя сессии (первая строка твоего ListAgents). Машина — Mac, machine.lock нет:
  тесты через machine_gate.sh (абсолютный путь основного чекаута); в сумме не больше трёх писателей по всем полосам.
COMMITS: Conventional Commits + Why:/Layer:/Refs: plans/robot-protocol-v2/plan.md; stage явных путей; заголовок ≤ 72; слияние в main — отдельный коммит
  git merge --no-ff -F <файл> с темой feat(...) (хук режет merge(...)); перед слиянием rebase на main + validate.py + backend/tests.
LIMITS: 2 итерации на петлю, на третьей вверх; решения владельца — списком (см. «открыто» ниже).
REPORT: по-русски, числа, непустое «что осталось открытым», таблица agentId; файл отчёта docs/reports/<дата>_robot-protocol-v2_T5.3e.6.md; в конце handoff и /clear.
LESSONS: `< /dev/null` и без лишних cat в составных командах (33 минуты на зависшем коммите); тест с риском зависания — subprocess.run(timeout=…) или daemon-поток
  с join; lint-хук требует DESIGN/FILES/REDS/REPORT или BRIEF-OVERRIDE: <причина>; `git checkout --` в worktree может отклоняться — коммит по явным путям;
  сторож qtbot.addWidget + shiboken6.delete в одном тесте даёт ошибку teardown; второй QTimer() ломает страж G6/R2 (allowlist = 1).
ОТКРЫТО ДЛЯ ВЛАДЕЛЬЦА (из handoff п.4): (а) шаг pre_stop Оператора `{"process":"devices","command":"robot_park_all","args":{},"timeout_s":35}`;
  (б) принять потерю второго рисунка на v2; (в) robot_draw_abort на v2 нет; (г) запись контракта наблюдаемости status.
```

## Полоса К — W2 «ядро» камер

```
ВКЛАДКА: Полоса К · W2 ядро камер 1.6 ∥ 1.8, затем 2.1, 2.2
ROLE: lead of lane К, plan plans/2026-10-18_camera-device-service/plan.md, волна W2: Task 1.6, 1.8, 2.1, 2.2 (W1a/W1b влиты; статус из git main).
READ FIRST: plan.md «Режим исполнения — волны» и «W2»; wave-protocol.md; docs/handoffs/2026-11-01_К-W1b-merged.md;
  docs/reports/2026-11-01_camera-device-service_W1b.md; tasks/1.6.md, 1.8.md, 2.1.md, 2.2.md.
GOAL: ядро Services/camera_device: план записи (1.6), вертикальный срез `driver: fake` → item → дисплей → backend_ctl (1.8), поток-владелец (2.1),
  run/rest с проверкой чтением (2.2).
ACCEPTANCE: по tasks/*.md; шапки [PENDING] в plan.md обновлять только по git.
PIPELINE: режим волн плана (отступление от общей конвенции, решение владельца 2026-10-18): Sonnet код и тесты; стадия 0 reviewer sonnet у 2.1 и 2.2 (у 1.6, 1.8 нет);
  слепой tester до кода у 2.1 и 2.2; break-injection только по механизмам 2.1 (поток-владелец) и 2.2 (проверка чтением, run/rest); Opus reviewer сразу после 2.1 и 2.2
  и один на волну по общему diff. Порядок: 1.6 ∥ 1.8 (два писателя), затем 2.1 (после 1.5, 1.8), затем 2.2 (после 1.6, 2.1). Граница волны — handoff + /clear.
  После W2 — сверка токенов с оценкой (порог плана 14M; W1b ≈ 1,52M). Субагенты только диагностика и файлы; коммитит лид.
BOUNDARIES: Services/camera_device, Plugins камер (только по задачам). Задачи 1.3/1.4/1.7 — не W2; 1.7 строить поверх влитого 1.11 (spawner.py stop(), полоса Ф).
  ORDER.md правит сессия Атласа. Основной чекаут может стоять на чужой ветке: работа в worktree, перед коммитом git branch --show-current.
  Ветка feat/camera-device-service уже удалена: начинать новую от main.
LOAD: координатор — inspector-bottles-a2; первое сообщение — своё имя сессии. Жёстко: не больше трёх писателей по всем полосам; `--timed medium` — своё окно.
COMMITS: Conventional Commits + Why:/Layer:/Refs: plans/2026-10-18_camera-device-service/plan.md; stage явных путей; слияние отдельным коммитом, тема feat(...).
LIMITS: 2 итерации на петлю, на третьей вверх (cto только вердикт с SHA); вопросы владельцу — списком.
REPORT: файл docs/reports/<дата>_camera-device-service_W2.md по шаблону; открыто — непустое; в конце handoff и /clear.
LESSONS: W1b: стадия 0 нашла 5 blocker в 1.5 и 6 major в 1.1 — исправлять текстом до тестов; ревью ветки показало, что тесты не ловили `live` и порядок проверок;
  ложно красный стоп-хук pre_report_gate (запись в plans/queue/inbox/); PortContractSuite и фейк на железе не проверены (день с железом №1, Task 0.5).
```
