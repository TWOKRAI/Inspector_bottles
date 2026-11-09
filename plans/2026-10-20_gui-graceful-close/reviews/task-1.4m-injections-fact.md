# Task 1.4m — факт матрицы инъекций (прогон 2, 2026-11-09)

База `5f4e2cf12` (реализация `f1f904d6e` + hazard M3), worktree `op-1.4m-inj2` (одноразовый; прогон 1 в `op-1.4m-inj` остановлен на I1 отказом в `git checkout --` — там висит грязная I1, дерево не трогалось). Набор — 4 файла: `test_shutdown_section.py`, `test_shutdown_section_author.py`, `test_launch_pre_stop.py`, `test_build_characterization.py` (11 тестов). Откат правок — копированием из резервных копий; после каждого отката `git status` и `git diff --stat` пусты. Предсказания — `task-1.4m-injections-predictions.md` (коммиты `db2085796`, `89ea97a4a`, до прогона). Исполнитель — haiku `a326e8a76995f17d1`; I1–I9 собраны лидом по сохранённым выводам `run_I1..I9.txt`, I10 прогнана по отдельной просьбе. Нулевой прогон: 11 passed.

| № | Инъекция | Красные (факт) | Итог pytest | Предсказание |
|---|---|---|---|---|
| I1 | `schemas.py`: убран `None → []` | reds6 | 1 failed, 10 passed | совпало |
| I2 | `default_factory=list` → `= []` | — | 11 passed | совпало (0 красных; pydantic копирует умолчания) |
| I3 | `system.yaml`: убрана секция `shutdown` | reds2, reds3, reds4a, reds4b, reds6, golden ×2 | 7 failed, 4 passed | совпало |
| I4 | `timeout_s: "35"` | reds2, reds3, reds4a, reds6, golden ×2 | 6 failed, 5 passed | совпало (reds4b зелёная — из неточных) |
| I5 | `launch.py`: ключ `pre_stop` удалён | reds4a, reds4b, reds4c, golden ×2 | 5 failed, 6 passed | совпало |
| I6 | поверхностная копия `[dict(s) …]` | reds4b | 1 failed, 10 passed | совпало |
| I7 | ключ только при непустом списке | reds4c | 1 failed, 10 passed | совпало (golden зелёный) |
| I8 | `"pre_stop": []` безусловно | reds4a, **reds4b**, golden ×2 | 4 failed, 7 passed | **расхождение:** ждали без reds4b |
| I9 | опечатка ключа `prestop` в `system.yaml` | reds2, reds3, reds4a, reds4b, reds6, golden ×2 | 7 failed, 4 passed | совпало |
| I10 | `list[Any]` → `list[dict[str, str]]` | reds2, reds3, reds4a, reds4b, reds6, author, golden ×2 | 8 failed, 3 passed | совпало |

**Итог: 9 из 10 совпали по набору красных** (цель — не менее 7).

**ФАКТ 2026-11-09 по I8 (расхождение):** `reds4b` краснеет и при `"pre_stop": []`, потому что его предусловие читает `orchestrator_config["pre_stop"][0]["args"]`, а при пустом списке это `IndexError`; предсказание не учло, что `reds4b` проверяет глубину копии через элемент. Вывод: `reds4a` и `reds4b` вместе красные при любой константе; «безусловный `[]`» ловят три ячейки, не одна. Свойство «ключ есть всегда при пустом списке» держит reds4c (I7).

Слабости ячеек, названные тестером и ревьюером, подтверждены инъекциями: reds1 слепа к общему изменяемому умолчанию (I2 — 0 красных, непроверяемо); reds5 зелёная при пустой базе (I3, I9) — закрыта reds6 и пустой базой в других ячейках; ограничение типа (I10) закрыто только авторским hazard (M3).

## Что осталось открытым / ненадёжно

- Каждая инъекция прогнана один раз, повторов нет.
- Прогон 1 оставил грязный worktree `op-1.4m-inj` (I1 в `schemas.py`) — откат запрещён правами, решение за владельцем; одноразовый worktree, на код ветки не влияет.
- Хук ruff показал F401 (`copy` не используется) при I5, I6, I8 — побочный эффект инъекций, не дефект кода.
- Путь «`launch.py` → `ProcessSpawner` → `PM.get_config("pre_stop")`» инъекциями не покрыт (проверен только живьём, `task-1.4m-live-fact.md`).
