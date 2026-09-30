# Хендофф: перемер после T1, робот T1.2/T1.3 слит в main — дальше 4.8a → 4.7 — 2026-09-30 (вечер, 5)

**Ветка основного дерева:** `feat/qr-code-reader` (перемер `ee22e620`, открытый вопрос `b195c5e1`, хендофф — этот
коммит). **main:** `4fd912cc` (робот слит поверх `023198d6` соседа, push не делали). **Предыдущий:**
[`2026-09-30_transport-f4-handoff-4.md`](2026-09-30_transport-f4-handoff-4.md).
**Планы:** [`transport-single-policy` Ф4](../../plans/transport-single-policy/phase-4-redesign.md) (`task-4.7.md`,
`task-4.8.md`), [`robot-protocol-v2`](../../plans/robot-protocol-v2/tasks.md).

## Выбор владельца (этот чат): вариант (a)

Перемер → робот T1.3 → 4.7. Перемер и робот сделаны. **Следующий шаг — Ф4 по порядку владельца: 4.8a → 4.7 → 4.8b.**
Модели (указание владельца): код — **Sonnet** (`developer`/`tester`, `model: "sonnet"`), ревью — **Opus**
(`reviewer`), **Fable** (`cto`) — только на сложных/спорных местах.

## Сделано

| Что | Итог |
|---|---|
| Перемер стенда после T1 | `ee22e620`, таблица в `task-4.7.md` «Перемер стенда после T1». 1080p 100 fps, 2×30 с на `a0457ee8` |
| robot-v2 T1.2 | замечания m1–m3, n1 внесены `7904f6d6`; **m4 отклонено** — выбор TLM по адресу делает проверку вакуумной (зона 64 слова < READ_MAX 125) |
| robot-v2 T1.3 | tester 9 слепых RED (`59155446`) → developer 3 итерации (`99a1dc8d`, `731dc8d4`, `c8494eef`) → инъекции лида 14 + 9 + 2, все по прогнозу → ревью Opus ×2 APPROVE_WITH_NITS. 3-е ревью (по мелочам итерации 3) не запускал — гарантии проверены инъекциями P1/P2 |
| Слияние робота в main | `4fd912cc` (договорено с соседом), радиус robot_comm 893 passed / 5 skipped / 2 xpassed, `build_fw --check` rc 0 |

## Числа перемера — главное для 4.7/4.8

- processor: `queue_wait_ms` 1098–1102 (было 1110), stale+torn ≈ 1800–1900 за 30 с (было 2068) — **T1 узкое место
  4.7 не сдвинула**.
- `color_mask` 11.5 + `blob_detector` 1.9 = 13.4 мс в живом процессе против 4.1–4.7 мс у `bench_t1` — **причина не
  найдена** (кандидаты: `cv_threads`, соседи по ядрам, другой вход).
- **renderer — новое узкое место:** `render_overlay` 11.6 → 39 мс, 21 Гц, `queue_wait_ms` 3.05 с. `overflow: latest`
  для renderer обязателен.
- camera `pacer_late` 42 → 456/497 за прогон — не разбирал.
- Инструмент: `scripts/capacity_bench/seed_stand45.py <tag> 1080 100 30 <port>`, cwd = стенд-worktree,
  `PYTHONPATH=cwd`, python из основного `.venv`. Результат — `%TEMP%/s45_<tag>.json` + `s45_<tag>_<proc>_levels.json`.

## Открыто

- **Вопрос владельцу** (`OPEN_QUESTIONS.md`, `b195c5e1`): FW_BUILD = CRC исходников до подстановок, не зависит от
  `delta_v2.yaml` → PING не отличит прошивку на старой карте. Контракт не менял.
- GATE-0 робота (из хендоффа 4): старшие половины широких параметров из 112..127 — годятся только id ≤ 124;
  беззнаковые с max ≥ 32768 — дыра −32768 в W (xfail).
- T1.3: реальный luacheck ни разу не запускался (нет в PATH); `.luacheckrc` минимальный (`allow_defined_top`),
  стабы DRAS — T4.x. Каталог с именем `20_x.lua` тестом не закрыт (мутация выживает, принято).
- PC-5, PC-6, PC-7 (тест T1 зависит от порядка, фикстура `all_real_plugins`) — открыты.
- `feat/qr-code-reader` ещё не сведена с новым main `4fd912cc` (ожидаемые конфликты — документы и метки timeout R-6).

## Стенд и worktree'ы

- `stand.lock` снят; стенд-worktree `.claude/worktrees/stand` detached на `a0457ee8` (соседу сказано).
- `.claude/worktrees/rv2-merge` — detached на `4fd912cc`, можно удалить. `rv2-t12`, `rv2-t13-tester` — ветки слиты,
  можно удалить (и ветки `feat/robot-v2-t12-t13`, `tests/robot-v2-t13-blind`). `pnt-t1-impl` — тоже.
- Сосед `inspector-bottles-79` поведёт свои правки поверх main `4fd912cc`; ему нужен SHA при каждом движении main.

## Скрипты (scratchpad `3d7f6165…/scratchpad`, временные)

`inject_t13.py` (L1–L14), `inject_t13b.py` (N1–N9), `inject_t13c.py` (P1–P2), `t13_predictions.md`.
