# Ревью Task 1.0 редактора слоёв — переносимые пути ScenePreset

**Вердикт:** CHANGES REQUESTED (итерация 1 из 2). Блокеров нет; три SHOULD (код, тест, документация), шесть NIT.
**Объём:** `git diff 4e000222..HEAD -- Services/` (f8687318, 3c37c41c, bb932b99), план `plans/line-sim-layer-editor.md`, решение LS-013.
**Ревьюер:** reviewer (Opus), синхронно, только чтение. qex недоступен (Ollama не запущен) — поиск через `grep`.

## Прогон

```
PYTHONPATH=$PWD .venv/bin/python -m pytest Services/line_sim/tests Plugins/sim/scene_source -q --tb=short
======================= 273 passed, 1 skipped in 10.10s ========================
ruff check -q <6 изменённых .py>  -> exit 0
```

Сценарии воспроизведены скриптами во временном каталоге сессии (`repro_1_0.py`, `i1_effect.py`, `post_claim.py`), в репозиторий они не попали.

## Что работает (проверено запуском)

- Сохранение в тот же каталог через симлинк, в обе стороны: `from_yaml(link A/p.yaml).to_yaml(link A/x.yaml)` и `from_yaml(real R/p.yaml).to_yaml(link A/x.yaml)` -> `catalog_dir: sprites`, ребейза нет.
- `to_yaml` с относительным аргументом: CWD=root, `to_yaml('B/rel.yaml')` -> `../A/sprites`, после перезагрузки фабрика собирается (`num_classes=2`); CWD=A, `to_yaml('same.yaml')` -> `sprites`.
- Плагин (`plugin.py:254`, `ScenePreset(catalog_dir=<abs>)`): `base_dir=None`, `resolve_path` отдаёт строку без изменений, `load_catalog` получает то же, что до правки. Тесты scene_source зелёные.
- Два переписанных старых теста сохранили своё свойство. В 3.1 (`test_preset_yaml_round_trip`) фикстура содержит только id `fixture://`, так что тест по-прежнему проверяет, что все поля переживают round-trip; относительные строки теперь проверяют новые тесты 1.0. В 3.2 проверяются три вещи: строка хранится как записана, `resolve_path` смотрит от каталога файла, и фабрика реально собирает 2 класса при CWD в другом месте — исходное свойство «от каталога YAML, а не от CWD» проверяется по-прежнему.
- Равенство: одинаковые файлы в A и B дают `False` (разный `base_dir`). Никто в `Services/line_sim`, `Plugins/sim` и `apps/line_sim` на равенство или хеш пресета не опирается: `grep` находит сравнения только в тестах. `hash(preset)` падает с `TypeError: unhashable type: 'list'` из-за поля `layers`, это было и до правки.

## Находки

### SHOULD-1 [код, переносимость] — `to_yaml` ребейзит от НЕразрешённого `base_dir`, хотя сравнивает с разрешённым
`preset.py`, `to_yaml` и `_rebase_value`: условие `base_dir.resolve() != target_dir` использует разрешённый путь, а `os.path.relpath(base_dir / value, target_dir)` — сырой.
- Вход: `ScenePreset.from_dict({"catalog_dir": "sprites", "base_dir": "/tmp/rv10_kts00oju/A"})` (на macOS `/tmp` — симлинк на `/private/tmp`), затем `to_yaml("/tmp/rv10_kts00oju/B/q.yaml")`.
- Наблюдалось: в YAML записано `catalog_dir: ../../../../tmp/rv10_kts00oju/A/sprites`, то есть относительная строка, которая поднимается до корня и хранит структуру машины. На месте файл открывается. После копирования A+B в другой каталог: `FileNotFoundError: Каталог классов не найден: /private/var/folders/.../rv10m_...`.
- `from_yaml` всегда ставит разрешённый путь, поэтому сейчас такой пресет можно получить только через `from_dict` или конструктор с `base_dir` от руки. Именно так его будет строить редактор слоёв.
- Исправление: в `to_yaml` `base_dir = Path(self.base_dir).resolve()`. Проверено в scratch: `_rebase_value("sprites", Path(".../A").resolve(), B)` -> `../A/sprites`. Добавить тест с неразрешённым `base_dir` (симлинк-каталог под `tmp_path`).

### SHOULD-2 [тесты] — `.resolve()` в `from_yaml` не закреплён ни одним тестом
Инъекция I1 (одноразовый pytest-плагин): `from_yaml` ставит `base_dir=str(p.parent)` без `.resolve()`.
- Предсказание: умрёт 0 тестов (на macOS `tmp_path` уже разрешён, а загрузки по относительному пути с последующим `chdir` в тестах нет).
- Факт: `273 passed, 1 skipped` — совпало с предсказанием, то есть свойство без теста.
- Чем это грозит: CWD=root, `from_yaml("A/p.yaml")`, затем `chdir("/")`. Настоящий код: `base_dir=/private/tmp/.../A`, фабрика собирается. С инъекцией: `base_dir=A`, `FileNotFoundError`.
- Исправление: тест «`from_yaml` по относительному пути, затем `monkeypatch.chdir` в другой каталог, фабрика собирается». `test_load_independent_of_cwd` этого не ловит: он грузит по абсолютному пути.

### SHOULD-3 [документация] — README утверждает, что `to_dict` переносим между машинами; это неверно
README: «`to_dict`/`to_yaml` поэтому переносимы между машинами». Но `to_dict()` = `{'catalog_dir': 'sprites', ..., 'base_dir': '/private/tmp/rv10_kts00oju/A'}`.
- Вход: этот dict с `base_dir` другой машины, `from_dict` на Orin.
- Наблюдалось: `resolve_path -> /home/orin/presets/A/sprites`, `FileNotFoundError`. Тот же dict без `base_dir`, при CWD=A, собирается.
- Довод из раздела «Отвергнуто» в LS-013 («модель… несла бы путь машины через `to_dict`… в журнал») частично относится и к выбранному решению: путь машины едет через `to_dict`, только отдельным полем.
- Исправление: в README и LS-013 записать явно, что `to_dict` годится только в пределах одной машины, а между машинами — только `to_yaml`, либо вырезать `base_dir` там, где dict уходит за пределы машины.

### NIT-1 — `base_dir=None` плюс относительные строки: `to_yaml` в каталог, отличный от CWD, меняет смысл строк
- Вход: CWD=X, `ScenePreset(catalog_dir="sprites")` (фабрика: `OK num_classes=2`), затем `to_yaml("Y/p.yaml")`.
- Наблюдалось: в YAML `catalog_dir: sprites`; `from_yaml(Y/p.yaml)` -> `FileNotFoundError: .../Y/sprites`.
- Было так и до правки, это не регрессия. Но докстринг класса объявляет `None` = «от CWD», а `to_yaml` от CWD не ребейзит. Нужно для «Новый пресет» в редакторе: `Path(self.base_dir) if self.base_dir is not None else Path.cwd()` или явная оговорка в докстринге.

### NIT-2 — пресет в симлинк-каталоге: save-as рядом с симлинком пишет строку, хранящую структуру машины
- Вход: `proj/A -> /var/folders/.../real_A`, `from_yaml(proj/A/p.yaml)`, затем `to_yaml(proj/B/q.yaml)`.
- Наблюдалось: `catalog_dir: ../../../../var/folders/.../real_A/sprites`.
- Старый код писал абсолютный путь, так что это улучшение, а не регрессия. Выбор между `resolve()` и лексическим `abspath` стоит записать в LS-013. Реалистичный случай — Orin с симлинком на каталог данных на NVMe (на Orin не проверялось).

### NIT-3 — «абсолютные пути не трогаются никогда» верно только в пределах одной ОС
- На Mac: YAML со слоем `sprite_source: "C:\data\cap.png"`, save-as в B -> `'../A/C:/data/cap.png'`.
- Симуляция через `PureWindowsPath`, Python 3.12.13: `is_absolute("/home/orin/cap.png") = False`, поэтому на Windows абсолютный путь Orin превратился бы в `../../home/orin/cap.png`. На настоящем Windows не запускалось.
- Абсолютные пути непереносимы по определению, но README обещает, что они не меняются. Уточнить формулировку.

### NIT-4 — обратные слэши приводятся к прямым только в ветке ребейза
- Вход: `catalog_dir: "sub\sprites"`. Сохранение в тот же каталог -> `'sub\\sprites'`; в другой каталог -> `'../A/sub/sprites'`.
- Если на Windows сохранить пресет со строками через `\` на то же место, на Mac он не откроется. Задача для редактора: выдавать строки с `/` (или нормализовать все относительные строки в `to_yaml`).

### NIT-5 — `..` через симлинк: `relpath` схлопывает `..` лексически, а ядро — нет
- Вход: `A/lnk -> .../elsewhere/deep`, `catalog_dir: lnk/../sprites`. Грузится из `.../elsewhere/sprites`; save-as в B -> `../A/sprites`, то есть уже другой каталог, `/private/tmp/.../A/sprites`.
- Экзотика; достаточно одной строки в LS-013.

### NIT-6 — постусловие в докстринге класса буквально ложно для save-as
«`from_yaml(to_yaml(p, f))` равен `p` с `base_dir` = каталог `f`»: для A -> B проверка `q == p.model_copy(update={"base_dir": B})` даёт `False` (`q.catalog_dir = '../A/sprites'`). Переформулировать: «`resolve_path` каждого пути указывает на тот же файл». Мелочь рядом: строки `# ponytail:` в `_rebase_value` стоят внутри докстринга, а не в комментарии.

## Что я не проверил и в чём не уверен

- Поведение на настоящем Windows и на Orin не запускалось: NIT-3 и NIT-4 — симуляция через `ntpath`/`PureWindowsPath`, NIT-2 для Orin — предположение о симлинке на каталог данных.
- Матрицу инъекций лида B1–B6 не повторял (по брифу); своя инъекция одна — I1.
- Реального производителя пресета с неразрешённым `base_dir` (SHOULD-1) сейчас нет: `grep` находит только `plugin.py:254` с `base_dir=None`. Серьёзность оценена с расчётом на редактор слоёв, а не на текущий код.
- Уходит ли `to_dict()` пресета через IPC или в журнал в каком-либо живом пути, проверял только `grep`'ом по `Services`, `Plugins`, `apps`, `multiprocess_prototype`: вызовов не нашлось. На живом стенде не проверял.
