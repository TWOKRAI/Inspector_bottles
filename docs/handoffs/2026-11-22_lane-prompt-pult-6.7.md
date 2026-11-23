# Промпт полосы Пульт — Task 6.7 (координатор inspector-bottles-30, 2026-11-22)

```
ВКЛАДКА: Пульт · 6.7 «Домой»/«Серво ВКЛ» в β-рецепт
ROLE: lead of lane Пульт, plan plans/pult-control-panel-phase6.md. 6.1–6.6 и повтор приёмки при `run_gate: true` в main. R4 влит `dc7883ce6`: β (`hikvision_letter_robot.yaml`) теперь на `delta_v2` и камере `camera_device`; «Домой» и «Серво ВКЛ» в β было нельзя «до R4» — теперь можно. Статус — из git.
READ FIRST: docs/handoffs/2026-11-22_camera-R4-merge-request.md и 2026-11-22_camera-lane-K-after-R4.md (строки для Пульта); docs/reports/2026-11-22_pult_recheck-run-gate.md; `multiprocess_prototype/recipes/letter_robot_sim.yaml` (блок `pult`: 10 контролов — образец), `multiprocess_prototype/recipes/tests/test_letter_robot_sim_diff.py` (`_EXPECTED_DIFFS`, запись `controls[len=8 vs 10]`), тест `test_beta_has_no_home_servo_before_r4`.
GOAL: в β-рецепте блок `pult` равен симовскому по контролам: добавить «Домой» (`robot_park`) и «Серво ВКЛ» с теми же аргументами, что в `letter_robot_sim` (device_id робота β — по рецепту β, не копировать слепо); сторож сим-против-β больше не ждёт расхождения.
ЗАДАЧИ:
  1. Правка рецепта: два контрола в блок `pult` β (controls 8 → 10).
  2. Снять запись `controls[len=8 vs 10]` из `_EXPECTED_DIFFS` и тест `test_beta_has_no_home_servo_before_r4` (его смысл «до R4» исчерпан).
  3. Golden β — `UPDATE_BUILD_SNAPSHOTS=1`, в диффе ТОЛЬКО блок `pult`; дифф просмотреть вручную.
  4. Предсказания инъекций ДО прогона: например, вернуть запись `_EXPECTED_DIFFS` — тест краснеет; убрать контрол — краснеет сторож; опечатка `device_id` — краснеет проверка рецепта.
ACCEPTANCE: `recipes/tests` + `test_recipe_1_0.py` + golden β зелёные (числа из радиуса К: recipes + golden 266 passed, control_panel/tests 95 passed — пересчитать); инъекции совпали с предсказаниями. НЕ заявлять работу β на реальном роботе: v2 на железе не проверен.
PIPELINE: «Task launch convention»; стадия 0 не нужна (рецепт и сторож, solo-trivial — сказать вслух), слепой tester не нужен, стадии 3 (инъекции, механический прогон — haiku по предсказаниям лида) и 5 (reviewer sonnet) обязательны; субагенты не коммитят.
BOUNDARIES: твои — вкладка «Пульт», Services/control_panel, блок `pult` в рецептах и ТОЛЬКО он в `hikvision_letter_robot.yaml` (К закончил R4 и в рецепт больше не пишет); golden β. Не трогать: остальные узлы β (камера, драйвер, `use_linear`, `first_y` — R4 влит), Plugins/hub/device_hub и вкладку «Робот» (Р2), PM/spawner/state_store (Ф). Свой worktree от main, `git branch --show-current` перед коммитом.
LOAD: координатор inspector-bottles-30; первое сообщение — имя своей сессии (первая строка твоего ListAgents); ВКЛАДКА + имя в первой строке каждого ответа владельцу; `machine_gate.sh` по абсолютному пути.
COMMITS: feat(recipes) + Why:/Layer:/Refs: plans/pult-control-panel-phase6.md; Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>; stage явных путей; в main не коммитить, заявка файлом docs/handoffs/<дата>_pult-6.7-merge-request.md.
LIMITS: 2 итерации; красный вне plans/queue/defects.md — регистрировать.
REPORT: docs/reports/<дата>_pult_6.7.md ≤ ~12 строк, по-русски, непустое «Открыто» (что не проверено без железа); в конце handoff и /clear.
LESSONS: golden β правят К, Ф и Пульт — после rebase пересобирать, вручную не мёржить; повтор приёмки 22.11: лента в `ready` мгновенна, лагает метрика (C-103); старая вкладка «Робот» на v2 шлёт 16 операций v1 — известная, не твоя (К передал вопрос Р2/владельцу).
```
