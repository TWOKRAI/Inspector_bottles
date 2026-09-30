# Хендофф: Ф4 транспорта + pipeline-node-timing — 2026-09-30 (вечер, 3)

**Ветка:** `feat/qr-code-reader`. **Предыдущий:** [`2026-09-30_transport-f4-handoff-2.md`](2026-09-30_transport-f4-handoff-2.md).
**Планы:** [`transport-single-policy`](../../plans/transport-single-policy/phase-4-redesign.md) (Ф4 разбита по
файлам `task-4.5/4.7/4.8.md`), новый [`pipeline-node-timing`](../../plans/pipeline-node-timing.md).

## Состояние

| Что | Состояние |
|---|---|
| **4.5** наблюдаемость пути кадра | ✅ слита `14fdf123` в `feat/qr-code-reader`; статус и числа стенда — `task-4.5.md` («Статус 4.5») |
| **pipeline-node-timing T1** цепочка находит объекты (дефект PC-1) | ✅ код `917ec7ed` в ветке `feat/pipeline-node-timing` (worktree `.claude/worktrees/pnt-t1-impl`); tester 7/7, плагины 394 passed, инъекции лида 4 (I2–I4 по прогнозу, I1 — ошибка моей модели, тест верный). **Ревью НЕ проведено**, в `feat/qr-code-reader` НЕ слито |
| 4.8a переносимый бенч | план в `task-4.8.md`; затравка `scripts/capacity_bench/seed_stand45.py` (Windows-only, из замера 4.5) |
| 4.7 один режим | ждёт; порядок владельца: **4.8a → 4.7 → 4.8b** |
| pipeline-node-timing T2 время узла в GUI | ждёт T1; T3 геометрия, T4 фильтр шума — после |

## Первым шагом в новом чате

1. **Ревью T1** (reviewer синхронно, `git diff 284e6536..917ec7ed` в `pnt-t1-impl`) → слить
   `feat/pipeline-node-timing` в `feat/qr-code-reader` (слияние — сообщение из файла, `-F -` не работает).
   Отметить PC-1/PC-2 закрытыми в `plans/queue/defects.md`.
2. **4.8a** — бриф по `task-4.8.md` («Решение владельца… 4.8a»): tester до кода, developer на Sonnet. Затравка —
   `seed_stand45.py` (уже читает топологию из репо, а не из scratchpad). Требование владельца: одна команда на
   любом железе, линия — Orin NX (Linux ARM) → CPU через `/proc`, паспорт машины, самопроверка часов 1.0 ± 5 %.
3. Затем 4.7 (разрез на a–f набросан в чате: a — предусловия P-1/P-2, b — имена + кэш handles, c — zero-copy +
   blob_detector копирует (часть уже сделана в T1!), d — глубина 8 и очередь ≤ кольцо−2, e — `overflow`, f — loan).

## Что сказали поля 4.5 на стенде 1080p 100 fps (сырьё для 4.8b и T2)

processor `color_mask` 8.4 + `blob_detector` 6.7 мс при бюджете 10 мс; `queue_wait_ms` у processor 1110 мс;
`render_overlay` 11.6 мс; цепочка 54–58 Гц; машина занята на ~4.5 ядра из 16. **Все замеры Ф4 до T1 мерили цепочку
без детекций** (PC-1). Микробенчмарк: три полнокадровых преобразования 10.1 мс → одно 4.6 мс → 960×540 1.7 мс;
переписывать на Rust/Numba бессмысленно — время внутри OpenCV C++ (записано в память о цели мощностей).

## Договорённости (в памяти, повторять не нужно)

- **Протокол стенда и тестов между сессиями** — `.claude/memory/feedback_shared_stand_and_tests_protocol.md`
  (замок `measure`/`functional`, стенд-worktree `.claude/worktrees/stand` detached на SHA, A/B в одном окне,
  данные вне git скопированы). Сосед — сессия `inspector-bottles-79` (line-sim R-5); перед `measure` писать ей.
- Сосед подготовил слияние main → `feat/qr-code-reader` в своём worktree `merge-qr`, ветка `merge/main-into-qr`
  от `89336393`; брать после слияния T1, сказать ей.
- Бенч мощности — одна команда на любом железе: `.claude/memory/project_portable_capacity_bench.md`.

## Ловушки

- **Инъекции — только по закоммиченному коду** (повторил сегодня, память дополнена двумя проверками `git diff`).
- `git merge -F -` не читает stdin — сообщение из файла.
- Папка `.claude/worktrees/t45-merge` не удалилась (Permission denied — держит процесс); из `git worktree` снята.
- Флак: `test_t45b_plugin_ms_alpha_is_a_tenth_first_sample_seeds` падает под параллельной нагрузкой (отдельно 6/6).
- Радиус process+router: 3 известных падения socket HOL (C-2).
- На малой нагрузке (0.05–0.2 ядра) `state.cpu` ниже внешнего замера на 2–9 % — причина не найдена.
- `~MHz` проверена только на i5-12500H; на другом CPU — самопроверка часов в 4.8a.

## Скрипты (scratchpad `29239a1a…/scratchpad`, временные)

`inject45.py` — матрица 25 инъекций 4.5; `stand45.py` + `s45_*.json` — замер A/B (копия в репо —
`scripts/capacity_bench/seed_stand45.py`); репро ревьюера `r_gate.py`, `r2b.py`, `r5.py`, `r6.py`, `r_bp45d.py`,
`r_msg45d.py`.
