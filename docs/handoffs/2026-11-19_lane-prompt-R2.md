# Стартовый промпт — Полоса Р2 — подготовка визита к роботу (≈ 2026-11-22), без кода (координатор inspector-bottles-9e, 2026-11-19)

Сводка веток, порядок слияния и общие правила — `2026-11-19_lane-prompts-index.md`. Вставлять блок ниже в новый чат целиком.

```
ВКЛАДКА: Полоса Р2 · день №2 робот: GATE-1 (T0.3) → T4.0, подготовка визита
ROLE: lead of lane Р2, plan plans/robot-protocol-v2/plan.md; код пишет только по слову владельца (слот писателя занят Ф + К + Д2).
READ FIRST: docs/handoffs/2026-11-15_R2-T5.3e.6-merged.md, docs/handoffs/2026-11-15_day2-robot.md, docs/reports/2026-11-15_R2_lane.md, plans/r2-env-isolation-defects/ (D1, D2 влиты), docs/handoffs/2026-11-15_day1-camera-checklist.md (общий чек-лист дней с железом).
ЧТО ЕСТЬ: T5.3e.1–6 и C-56 влиты, D1 (путь реестра устройств, `d0994e819`) и D2 (PID-реестр по checkout, `477573696`, ADR-PMM-046) влиты. T0.3 `[BLOCKED]` (GATE-1 — `pc_probe.py all` на контроллере), T4.0 `[PENDING]`. Сухой прогон дома: пара `pc_probe.py` + sim, 53 passed.
GOAL: к визиту (≈ 2026-11-22, слово владельца) комплект готов: команды, ожидаемый вывод, что записывать, что нельзя делать без владельца. Ничего не имитировать: T0.3 не закрывается без контроллера.
ЗАДАЧИ (без кода):
  1. Сверить `docs/handoffs/2026-11-15_day2-robot.md` с `main` на 2026-11-19: что устарело после слияний 11-16…17 (камера W3, Д, run-state) — исправить документом.
  2. Перенос `devices.yaml` и `robot/` из `Project_code/data/` в `Inspector_bottles/data/` (после D1 хаб читает новое место) — ТОЛЬКО по слову владельца; до него — проверка, что хаб без переноса даёт понятную ошибку, а не молчит.
  3. REVIEW-5 у cto (приёмка Ф5 без GUI) — подготовить вход (по плану), запуск — по слову владельца (CTO — только в тяжёлых случаях).
  4. Решения (а)–(д) из `docs/reports/2026-11-15_R2_lane.md` — список вопросов владельцу с рекомендацией каждого.
  5. Остаток C-60.b / T5.3e.5 (`robot_park_all` для `pre_stop`): сверить по `git grep` — влит ли; если нет, это задача под слот писателя, оформить бриф.
PIPELINE: только документы и проверки чтением/гейтом; `tech-writer` (sonnet) для документов, Haiku — для инвентарей; код — через `developer` по слову владельца и после слота.
BOUNDARIES: `Plugins/hub/device_hub`, `Plugins/sim/robot_host`, `Services/device_hub`, вкладка робота — их файлы; не писать в `Services/camera_device` (К), `process_manager_process.py`, `launcher/spawner.py` (Ф). Устаревший текст про `start_worker` (`Plugins/sim/robot_host/plugin.py:481-482`, `tests/test_v2_real_worker_manager.py:8,203-204`) — поправить только вместе с кодовой задачей.
LOAD: координатор — первая строка `ListAgents` координатора (сейчас `inspector-bottles-9e`); первое сообщение — своё имя сессии. Mac, `machine.lock` нет: тесты через `machine_gate.sh` (абсолютный путь); железо не трогать.
COMMITS: Conventional Commits + Why:/Layer:/Refs: plans/robot-protocol-v2/plan.md; только `docs(...)`; stage явных путей.
LIMITS: 2 итерации; не обещать «успеем» — только числа замеров на симе.
REPORT: `docs/reports/<дата>_R2_lane.md` (≤ ~15 строк), по-русски, непустое «что осталось открытым / ненадёжно».
ОТКРЫТО ДЛЯ ВЛАДЕЛЬЦА: слово на визит; перенос `devices.yaml`; REVIEW-5 у cto; решения (а)–(д).
```

