# rel1_truth — независимый эталон набора `rel1`

Эталон набора `../rel1.json` строится БЕЗ Атласа: `ast` по `git archive 1e085652f` плюс ручная сверка чтением.
Набор оценивается как множество адресов (`scripts/nav_bench/relset.py`).

| файл | что это |
|---|---|
| `spec.json` | вход: вопрос → отношение, цель, область, ручные решения (`manual_include`, `manual_notes`), «разумный grep» |
| `truth.py` | скрипт эталона: 8 отношений (`callers`, `subclasses`, `structural`, `importers`, `threads`, `env_reads`, `self_callers`, `uses`); правила включения — в докстринге |
| `truth.json` | выход `truth.py` (81 запись на 10 вопросов) |
| `crosscheck.py` | сверка с `git grep`: каждая прод-строка `[T]`/`[ ]` для ручного решения и счёт «разумного grep» (строк, верных, ложных) |
| `atlas_targets.json`, `atlas_ceiling.py` | потолок Атласа до прогона: id идеальные и из текста вопроса; Атлас — только сравниваемый, не источник |

## Как перепроверить (из корня worktree, без платных вызовов)

```
python scripts/nav_bench/questions/rel1_truth/truth.py --root . --check scripts/nav_bench/questions/rel1.json   # расхождений 0
python scripts/nav_bench/questions/rel1_truth/crosscheck.py --root .            # список [ ] прочитать глазами
python scripts/nav_bench/bench.py verify-set --questions scripts/nav_bench/questions/rel1.json                # проблем 0
python scripts/nav_bench/relset.py lint --questions scripts/nav_bench/questions/rel1.json --root . \
    --truth scripts/nav_bench/questions/rel1_truth/truth.json                                                 # проблем 0
python scripts/nav_bench/questions/rel1_truth/atlas_ceiling.py --atlas-root <клон с scripts/atlas и кэшем>
```

`truth.py` ~40 с (разбор 4 388 файлов), `relset.py lint` ~35 с (`git grep` по каждому слову вопроса).

## Ручные решения (приняты до разметки, записаны в `spec.json`)

- A1: однофамилец `Services/robot_comm/store.py::compute_rev` — другая функция, не входит; вызовы через реэкспорт
  `recipe.service` (Plugins) — тот же объект, входят.
- B1: транзитивно, абстрактные промежуточные классы входят; 32 тестовых подкласса — нет.
- B2: однофамилец `shared_resources_module/.../config_store.py::ConfigStore` — другой класс.
- C2: файлы, получающие имена пакета через третий модуль (`telemetry_view_model`), не входят.
- D2: добавлены руками `log_paths.py:21` (цикл по кортежу литералов + `os.environ.get(key)`) и `launch.py:54`
  (`env.get(...)` по переданному окружению); не входят: таблица алиасов `app_module/env.py:37`, записи в окружение
  (`launch.py:682`, `:684`), документация, `backend_ctl/probes`, `tools/`.
- E1: `process_manager_process.py:233` (`stop_abort = self._pm_stopping` — ссылка на потом, не вызов) не входит.

Все строки `[T]` и `[ ]` вывода `crosscheck.py` прочитаны 2026-11-11; каждая запись `rel1.json` помечена
`source` (`ast`/`manual`) и `manual_check: true`.
