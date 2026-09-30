# Хендофф: transport-single-policy Ф4 — после слияния 4.4 — 2026-09-30 (вечер)

**Ветка:** `feat/qr-code-reader`, HEAD после `9b5b0697`. **План:** [`phase-4-redesign.md`](../../plans/transport-single-policy/phase-4-redesign.md).
**Предыдущий:** [`2026-09-30_transport-f4-handoff.md`](2026-09-30_transport-f4-handoff.md) (утро, до итерации 2).

## Состояние

| Task | Состояние |
|---|---|
| 4.4 ссылка на кадр | ✅ слита `d0901979`, ревью итерация 2 APPROVE ([отчёт](../reviews/2026-09-30_task-4.4-review-iter2.md)) |
| 4.6 cv_threads | ✅ слита `939be356` |
| 4.5 наблюдаемость | **следующая**, не начата; дополнена п. 8 `queue_wait_ms` и п. 9 экспорт `frame_restore_failures` |
| 4.7 один режим | ждёт 4.5; добавлены п. 7 `overflow: latest | every` и предусловия P-1 (join теряет `_shm_views`), P-2 (лишние дропы двери) |
| 4.8 отчёт о мощностях | черновик, после 4.5 и 4.7 |

## Первым шагом в новом чате

1. **Разбить план** — `phase-4-redesign.md` 32.8 КБ > лимит 32 КБ (doc-size-guard; qex/graphify не индексируют хвост).
   По одному файлу на Task (`task-4.5.md`, `task-4.7.md`, `task-4.8.md`), в `phase-4-redesign.md` оставить шапку,
   факты, порядок и ссылки.
2. **4.5 по конвенции:** tester до кода (worktree на текущем HEAD) → developer на **Sonnet** (решение владельца:
   код пишет Sonnet, лид проверяет) → инъекции лида → reviewer синхронно. Бриф по шаблону
   `.claude/plugins/dev/templates/executor-brief.md` (≤ 6 файлов, ≤ 10 REDS) — иначе хук `lint-brief` не пустит.

## Главная цель владельца (читать до дизайна 4.5)

[`project_capacity_planning_goal.md`](../../.claude/memory/project_capacity_planning_goal.md): наблюдаемость должна
отвечать, **какой этап не успевает и во что упёрся** (код → язык → железо → несколько ПК) — до закупки железа.

Известные слабые места (замеры, 1080p 100 fps): processor — потолок ~60 Гц (какой плагин — неизвестно, нужен
`plugin_ms`); перегон данных 2124 МБ/с записи (B-7, zero-copy); `render_overlay` ~10 мс заливки по всему кадру;
очередь 50 при кольце 3; open+copy+close 2.5 мс без кэша handles. Машина при этом свободна (~4.6 из 16 ядер).

## Ловушки

- **Стенды — по очереди с другой сессией:** замок `D:\PROJECT_INNOTECH\Inspector_vision\stand.lock` (имя сессии,
  время, что поднято); перед подъёмом проверить, после — удалить и написать соседу (`inspector-bottles-b4`
  принял протокол).
- **QR-прибор** возвращён в `TriggerMode=1`: свободный режим греет его. В ПК он отдаёт ~2.7 к/с в `Raw`/`Test` при
  сенсоре 60 — см. `Services/code_reader/docs/GENICAM.md`. Решение владельца по 60 к/с не принято (результаты
  распознавания с прибора vs отдельная камера).
- **Хук `pre_report_gate`** в worktree красный по окружению (`uv sync` запрещён — CPU torch). Радиус гонит лид из
  основного venv с `PYTHONPATH=<worktree>`.
- Радиус на `d0901979`: 4 известных падения (3 socket HOL C-2, `r2 track_true`) +
  `test_pacing_hazards::test_idle_cycle_duration_measured_with_fine_clock` — флаки под нагрузкой (допуск ±2 мс;
  один 5/5, модуль 3/3 зелёные).
- Скрипты сессии (scratchpad `77e53bb3…`): `inject44d.py` (матрица инъекций 4.4 A+B), `qr_set.py`, `qr_trigger.py`,
  `qr_fps.py`, `qr_nodes.py`, `id3013.xml` (GenICam XML прибора); репро ревьюера — `rev44b/r2.py`, `r2j.py`.
