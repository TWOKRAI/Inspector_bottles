# Контракт лида 5.1b — причина «те же X/Y» уходит из журнала робота в правду сцены (2026-09-23)

Исправление находки стенда 5.1 ([отчёт](../../docs/reviews/2026-09-23_line-sim-5.1-stand.md)).
Владелец 2026-09-23: «исправь все ошибки». Выбран вариант (3) из отчёта, рекомендация лида.

**Что сломано.** `SimJournal.repeats_frozen_xy` («те же X/Y с новым энкодером») сравнивает
задание с заданием. На линии с триггером разные диски снимаются в одной точке кадра, и тройка
`(x, y, ecap)` у них та же, что у повтора кадра. Замер: 8 разных дисков → 7 «повторов», 21 → 11.
Внутри журнала робота эти случаи не различить ничем.

**Почему правда различает.** Сцена знает, куда реально приехал объект. Разные диски у триггера
сопоставляются каждый со своим (`matched`). Повтор кадра с энкодером, прочитанным позже,
указывает туда, где объекта нет: трекинг ведёт от более позднего `ecap`, промах `Δenc × 0.144473`
мм. Исход — `no_object` (или `dup`, если промах меньше радиуса, — та же зона неразличимости, что
`dups_tracked` в 5.1). Значит, причину «те же X/Y» надо искать **только среди ложных тревог**.

## 1. `Services/robot_comm/server/sim_journal.py` — убрать категорию

- Ветка `repeats_frozen_xy` удаляется: такое задание — обычная строка `"job"`.
- `counters()` — без ключа `repeats_frozen_xy`; `jobs, dups, done, reads, dups_same_capture,
  dups_tracked` без изменений. Инвариант `dups == dups_same_capture + dups_tracked` остаётся.
- Литерал: `(10, 20, e=1000)`, затем `(10, 20, e=2000)` → `jobs 2, dups 0`, ключа
  `repeats_frozen_xy` нет, в `drain()` нет строки с тегом `"repeat"`.

## 2. `Services/line_sim/core/truth.py` — `TruthLedger`

- `on_match(result, job=None)`: `job` — `JobDone` задания (координаты, `ecap`, `t`). Без `job` —
  поведение 5.2 без изменений.
- Ledger помнит недавние задания (`x, y, ecap, t`) с окном `frozen_window_s` (конструктор,
  дефолт 10.0) по полю `job.t`, собственных часов нет. Порог `frozen_radius_mm` (дефолт 5.0).
  Память плоская: задания старше окна выбрасываются на каждом `on_match`.
- Исход `no_object` при заданном `job`: если среди недавних есть задание с
  `hypot(Δx, Δy) < frozen_radius_mm` и другим `ecap` → `false_alarm_frozen_xy += 1`. Это
  подмножество `false_alarm`, а не отдельный исход: `false_alarm_frozen_xy <= false_alarm`.
- Любой исход с `job` кладёт задание в недавние.
- `counters()` получает ключ `false_alarm_frozen_xy`; `reset()` обнуляет его и очищает недавние.
- Литералы (`r = 5`, окно 10 с):
  - `matched A` job `(0, 20, e=1000, t=0)`, затем `matched B` job `(0, 20, e=2190, t=1.6)` →
    `caught 2`, `false_alarm_frozen_xy 0` (разные диски у триггера — повтором не считаются);
  - `matched A` job `(0, 20, e=1000, t=0)`, затем `no_object` job `(0, 20, e=1362, t=0.5)` →
    `false_alarm 1`, `false_alarm_frozen_xy 1`;
  - тот же `no_object`, но `t=10.5` (за окном) → `false_alarm 1`, `false_alarm_frozen_xy 0`;
  - `no_object` job `(0, -500, e=3000, t=2)` без похожих недавних → `false_alarm 1`,
    `false_alarm_frozen_xy 0`.

## 3. Проводка

- `Plugins/sim/scene_source/plugin.py`: `_drain_jobs` передаёт `job` в `on_match`, включая
  ветку «движок не собран». Уровень `truth_false_alarm_frozen_xy` — рядом с остальными `truth_*`
  (то же прореживание).
- `Plugins/sim/robot_host/plugin.py`: уровень `repeats_frozen_xy` и его `declare_metric` уходят;
  `sim_robot.journal` / `sim_robot.status` отдают `counters()` журнала как есть.
- `Plugins/sim/pult_web/plugin.py`: из строки «Задания от прототипа» убирается сегмент «те же
  X/Y с новым энкодером C». Показ правды на пульте — Task 5.3, не здесь.
- README/STATUS `robot_comm/server`, `robot_host`, `pult_web`, `scene_source`: убрать категорию
  из журнала, описать новую причину в правде.

## Кто что пишет

- **Тестер** (worktree на коммите контракта): §1 и §2 по литералам; §3 — `truth.status` после
  `scene.job_done` → `produce()` содержит `false_alarm_frozen_xy`, ключа `repeats_frozen_xy` нет
  в `sim_robot.journal` (фейковый ctx), пульт не показывает «те же X/Y».
- **Автор** (hazard): окно по `job.t` при немонотонном `t`, дошедшем по сети; память недавних
  при потоке без `no_object`.
- **Существующие тесты 5.1, закрепляющие `repeats_frozen_xy`** (`test_sim_journal_causes.py`,
  `test_journal_commands.py`, `test_hazards.py` `robot_host`, `test_pult_journal_routes.py`),
  закрепляют ошибочный контракт. Автор переписывает их под §1 и явно называет каждую правку в
  отчёте. Не удалять молча.
- **Лид** — стенд: повтор сценариев 5.1 (а'), 8 дисков у триггера → `caught 8`,
  `false_alarm_frozen_xy 0`, в журнале нет `repeats`; (б2) три задания без `e_capture` с паузой
  0.5 с → `caught 1`, `false_alarm 2`, `false_alarm_frozen_xy 2`.
