# Task 1.4m — предсказания инъекций (лид, 2026-11-09, ДО запуска)

Набор: 8 слепых тестов (reds1, 2, 3, 4a, 4b, 4c, 5, 6) + golden `test_build_characterization.py` (2 параметра: phone_sketch, hikvision_letter_robot). Инъекции — по закоммиченному коду ветки `feat/gui-close-1.4m`, откат из копии файла. Исполнитель прогона — haiku по этой таблице; факт пишется рядом с предсказанием.

| № | Инъекция | Ожидаемый красный набор | Почему |
|---|---|---|---|
| I1 | `schemas.py`: убрать validator `None → []` | reds6 | `pre_stop:` без значения → `ValidationError` при загрузке; остальные не читают `None` |
| I2 | `schemas.py`: `default_factory=list` → общий `= []` без фабрики | пусто (0 красных) | pydantic v2 копирует изменяемые значения по умолчанию; слабость reds1, названная тестером, — ожидаю, что она непроверяема |
| I3 | `system.yaml`: убрать секцию `shutdown` | reds2, reds3, reds4a, reds4b, reds6 + golden ×2 | ни одна ячейка с непустой базой не переживёт; reds1, reds4c, reds5 зелёные (база пуста — `[]` как ожидалось) |
| I4 | `system.yaml`: `timeout_s: "35"` (строка) | reds2, reds3, reds4a (+ возможно reds4b, reds6 по предусловию) + golden ×2 | литерал `35` ≠ `"35"`; strict-схема PM отвергает строку; точный набор по предусловиям тестера — уточнить фактом |
| I5 | `launch.py`: убрать ключ `pre_stop` из `orchestrator_config` | reds4a, reds4b, reds4c + golden ×2 | ключа нет |
| I6 | `launch.py`: `copy.deepcopy(...)` → `[dict(s) for s in ...]` | reds4b | вложенный `args` общий; остальные видят равенство значений |
| I7 | `launch.py`: ключ только если список непуст | reds4c | golden зелёный: в снимках список непустой |
| I8 | `launch.py`: `"pre_stop": []` безусловно | reds4a + golden ×2 | reds4c зелёный (слабость 4в, названная тестером) |
| I9 | `system.yaml`: поле `shutdown.pre_stop` → `shutdown.prestop` (опечатка в ключе) | reds2, reds3, reds4a, reds4b, reds6 + golden ×2 | схема молча отбрасывает лишний ключ (extra) — база пуста; reds1, reds4c, reds5 зелёные |

Ожидание суммарно: 9 инъекций, из них совпадение по набору — цель ≥ 7; расхождение — запись «ФАКТ» с датой, а не молчаливая правка. Дополнительно (не инъекция, а проверка слабости): после GREEN прогнать reds5 на базе без шага — зелёный, как предсказал тестер (предусловия базы нет в 5; закрыто reds6).

## Дополнение 2026-11-09 (после ревью стадии 5, ДО запуска) — база `5f4e2cf12`, набор из 4 файлов

Добавлен авторский hazard `test_shutdown_section_author.py` (M3). Набор прогона — 4 файла: `test_shutdown_section.py`, `test_shutdown_section_author.py`, `test_launch_pre_stop.py`, `test_build_characterization.py`. Авторский тест читает только литерал через `SystemConfig.model_validate`, от `system.yaml` и `launch.py` не зависит.

| № | Инъекция | Ожидаемый красный набор | Почему |
|---|---|---|---|
| I10 | `schemas.py`: `list[Any]` → `list[dict[str, str]]` | reds2, reds3, reds4a, reds4b, reds6, author, golden ×2 | настоящий `system.yaml` (`args: {}`, `timeout_s: 35`) перестаёт грузиться; reds1 и reds4c зелёные (`[]` валиден); reds5 зелёная — загрузка идёт после слияния файлов, итог `[]` |
| I1–I9 | как выше | как выше + author зелёный во всех | author не зависит от yaml/launch; при I1 (валидатор) тоже зелёный (литерал без `None`) |

Откат правки — копией файла (cp из резервной копии), не `git checkout`.
