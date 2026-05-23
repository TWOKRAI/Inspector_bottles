---
description: Отношение объёма тестов к коду на каждый модуль (LOC-based)
---

Запусти подсчёт test-ratio:

```bash
python scripts/test_ratio/test_ratio.py
```

> Скрипт ставится автоматически через `claude-kit new` (из `.claude/templates/scripts/test_ratio/`).

Что считает: на каждый модуль в `scan.module_roots` (настраивается в TOML; разумные дефолты: `src/`, или конкретные подпакеты типа `src/<package>/auth`, `src/<package>/api`) — LOC файлов в `tests/` (или совпадающих с `test_*.py`/`*_test.py`/`conftest.py`) ÷ LOC остального production-кода.

Конфиг: [scripts/test_ratio/test_ratio.toml](../../scripts/test_ratio/test_ratio.toml). Детали в [README.md](../../scripts/test_ratio/README.md).

**Health-маркеры:**
- `ok` — ratio ≥ `warn_threshold` (по умолчанию 0.3)
- `!` — тесты есть, но мало
- `x` — тестов нет

Полезные варианты:
- `python scripts/test_ratio/test_ratio.py --sort-by ratio --limit 10` — топ-10 слабейших.
- `python scripts/test_ratio/test_ratio.py --format json` — для CI/трендов.

**Когда использовать:**
- Дополнение к `/sentrux-gaps`: sentrux показывает «есть/нет тестов», `test_ratio` — **насколько**.
- Перед рефакторингом большого модуля: оценить риск.

**Ограничение:** LOC ≠ покрытие. Для настоящего coverage — `pytest --cov`.

$ARGUMENTS
