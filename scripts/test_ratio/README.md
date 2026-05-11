# test_ratio

Отношение LOC тестов к LOC продакшен-кода на каждый модуль.

## Алгоритм

1. Из `scan.module_roots` берутся корни, в которых каждый прямой подкаталог = модуль.
2. Внутри модуля .py-файлы делятся на:
   - **test** — путь содержит `detect.test_dir` (по умолчанию `tests`) **или** имя совпадает с `detect.test_file_patterns` (`test_*.py`, `*_test.py`, `conftest.py`).
   - **code** — всё остальное .py.
3. `ratio = test_loc / code_loc`.

LOC считается в `count.mode`:
- `non_blank_non_comment` (по умолчанию) — без пустых строк и комментариев `#`
- `non_blank` — без пустых
- `all` — все физические строки

## Колонка health

- `ok`  — ratio ≥ `output.warn_threshold` (по умолчанию 0.3)
- `!`   — ratio < threshold (тесты есть, но мало)
- `x`   — тестов нет вовсе

## Запуск

```bash
python scripts/test_ratio/test_ratio.py                       # все модули
python scripts/test_ratio/test_ratio.py --sort-by ratio       # от худших к лучшим
python scripts/test_ratio/test_ratio.py --format json
python scripts/test_ratio/test_ratio.py --limit 10            # топ-10 «слабейших»
```

## Когда полезно

- Дополнение к `/sentrux-gaps`: sentrux показывает «есть/нет тестов», `test_ratio` — **насколько** покрыто по объёму.
- Перед рефакторингом большого модуля: оценить риск «много кода, мало тестов».
- Тренд во времени (запускать в CI, складывать в JSON, рисовать график).

## Ограничения

- LOC ≠ покрытие. Это объёмная метрика. Для настоящего coverage — `pytest --cov`.
- Не различает unit/integration тесты.
- Считает все `.py` в `tests/`, даже если они не запускаются (фикстуры/хелперы) — это намеренно: они тоже «вес» поддержки тестов.
