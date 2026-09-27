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

## Итерация 2 — проверка cceba3f7

**Вердикт:** APPROVE_WITH_NITS. SHOULD-1..3 и NIT-6 закрыты. Остаток SHOULD-3 в двух докстрингах `preset.py` (NIT-7) нужно поправить до слияния ветки, Task 1.0 он не блокирует.
**Объём:** `git show cceba3f7` (`preset.py`, `test_hazards_1_0_paths.py`, `README.md`, `DECISIONS.md`).

### Прогон

```
PYTHONPATH=$PWD .venv/bin/python -m pytest Services/line_sim/tests Plugins/sim/scene_source -q --tb=short
======================== 275 passed, 1 skipped in 9.80s ========================
ruff check -q preset.py test_hazards_1_0_paths.py -> exit 0
```

Скрипт итерации 1 `repro_1_0.py` перезапущен на cceba3f7 (HEAD ветки), без изменений в самом скрипте.

### Находки итерации 1

- **SHOULD-1 — закрыт.** Сценарий [B]: `from_dict({"catalog_dir": "sprites", "base_dir": "/tmp/rv10_7cdsohvk/A"})`, затем `to_yaml(B/q.yaml)`.
  Было: `../../../../tmp/rv10_kts00oju/A/sprites`, после переноса A+B — `FileNotFoundError`.
  Стало: `B/q.yaml catalog_dir: ../A/sprites`; после копирования A+B в `/var/folders/.../rv10m_iq_gq7oh` — `OK num_classes=2`.
  Тест `test_save_as_from_symlinked_base_dir_writes_short_relative_path` строит свой симлинк под `tmp_path` и сравнивает с литералом `"../A/sprites"`. Поэтому он не зависит от того, симлинк ли `/tmp` на данной ОС.
- **SHOULD-2 — закрыт.** Тест `test_from_yaml_by_relative_path_survives_chdir`: `from_yaml("A/p.yaml")`, затем `chdir` в соседний каталог, проверка литерала `num_classes == 2`. Инъекции лида (убрать `.resolve()` в `from_yaml` / `to_yaml`) по брифу не повторял.
- **SHOULD-3 — закрыт в README и LS-013.** Тексты сверены: «между машинами переносим YAML, `to_dict()` несёт `base_dir` этой машины». Поведение [E] не изменилось, и так и должно быть, правка чисто документационная: `from_dict` с `base_dir` другой машины -> `FileNotFoundError: /home/orin/presets/A/sprites`.
- **NIT-6 — закрыт.** Новый Post совпадает с наблюдаемым: [C2] тот же каталог -> `sprites`; [B] другой каталог -> `../A/sprites`, картинки грузятся. Мелочь рядом (`# ponytail:` внутри докстринга `_rebase_value`) не тронута, не блокирует.

### Новое

- **NIT-7 [документация] — то же утверждение, что в SHOULD-3, осталось в двух докстрингах `Services/line_sim/core/preset.py`.** Итерация 1 назвала только README и LS-013, так что это пропуск ревьюера, а не лида.
  - `:37-39`, докстринг класса: «на dict-границе и в YAML он остаётся ровно той строкой, что была задана (переносимость между машинами)». Сценарий [E] показывает, что dict с `base_dir` между машинами не переносим. «В YAML ровно та строка» противоречит Post этого же докстринга и докстрингу `to_yaml`: при save-as строка `sprites` превращается в `../A/sprites`, сценарий [B].
  - `:97`, `from_dict`: «dict остаётся переносимым между машинами». Опровергает тот же [E].
  - Исправление: те же формулировки, что уже есть в README («строки хранятся как записаны; между машинами переносим YAML; при save-as в другой каталог `to_yaml` пересчитывает относительные строки»).
- **NIT-8 [качество] — двойной `resolve()` в `to_yaml`.** После правки `base_dir = Path(self.base_dir).resolve()`, и строкой ниже снова `if base_dir.resolve() != target_dir`. Второй вызов лишний, на поведение не влияет.

### NIT-1..5: блокировать не предлагаю

Повторный прогон дал те же результаты, что в итерации 1:
- [A] `FileNotFoundError .../Y/sprites`;
- [C] `../../../../var/folders/.../real_A/sprites`;
- [F] `'../A/C:/data/cap.png'`;
- [G] при сохранении в тот же каталог `'sub\\sprites'`;
- [H] `../A/sprites` указывает на другой реальный каталог.

Ни один из них не регрессия, и в живом коде до них сейчас не дойти. `grep -rn --include='*.py' '\.to_yaml('` по `Services Plugins apps multiprocess_prototype`, исключая `tests/`, находит только `Services/ml_train/trainer.py:348`, а это другой класс. Вызовов `ScenePreset.to_yaml` вне тестов нет. Эти сценарии станут достижимы, когда появится редактор, так что Task 1.2a/1.2h — подходящее место для них.

**Условие:** в плане их пока нет. `grep -n -i "NIT\|ревью 1.0\|base_dir=None\|симлинк" plans/line-sim-layer-editor.md` не находит упоминаний Task 1.0, а последняя правка плана — 4e000222. Их нужно записать во входные данные Task 1.2a/1.2h до того, как Task 1.0 будет отмечен закрытым, иначе они потеряются.

### Что я не проверил и в чём не уверен

- Инъекции лида не повторял (по брифу), своих в итерации 2 не делал. Что тесты краснеют при откате, знаю только со слов лида.
- Тест с симлинком не зависит от платформы по построению, но на Linux/Orin и Windows не запускался.
- NIT-7 найден чтением и подтверждён сценариями [B]/[E], не тестом: утверждения в докстринге тестом не закрепить.
