# Task 1.0 — tester (RED), редактор слоёв line_sim: переносимые пути ScenePreset

Роль: `tester`, независимый, blind. Ветка `test/ls-layer-1.0`, worktree
`.claude/worktrees/ls-1.0-tester` (pre-implementation commit `4e000222`).
План: `plans/line-sim-layer-editor.md`, Task 1.0.

## Файл

`Services/line_sim/tests/test_acceptance_1_0_paths.py` — 7 тестов по DESIGN из
брифа (fixture-builder на `tmp_path`, рендер-оракул `ObjectFactory(preset).make(...).render()`,
`np.array_equal`).

## Источники контракта

- `Services/line_sim/interfaces.py` (Protocol/dataclass/Pydantic контракт — прочитан)
- `Services/line_sim/README.md` (описание `ScenePreset`, `ObjectFactory`, резолюция
  путей в `from_yaml`, reserved-имена `base`/`damaged` — прочитан)
- `Services/dataset_gen/core/catalog.py` (формат каталога: листовая папка = класс,
  RGBA обязателен — прочитан)
- `Services/line_sim/__init__.py` (публичный API — прочитан)

`core/preset.py`, `core/factory.py`, `core/catalog_bridge.py`, `core/layered_object.py`
и остальной `Services/line_sim/tests/` — НЕ читал, НЕ грепал, НЕ импортировал.

## Команда

```
PYTHONPATH=$PWD /Users/twokrai/Project_code/Inspector_bottles/.venv/bin/python -m pytest \
  Services/line_sim/tests/test_acceptance_1_0_paths.py -q --tb=short
```

## Результат — 3 failed, 4 passed in ~0.5s

| Тест | Критерий | Предсказано | Факт | Падающий assert |
|---|---|---|---|---|
| `test_to_dict_keeps_relative_strings` | 1 | RED | **RED** | `assert d["catalog_dir"] == "sprites"` → фактически абсолютный путь `/private/var/.../A/sprites` |
| `test_to_yaml_same_dir_has_no_absolute_path` | 2 | RED | **RED** | `assert str(a) not in text` → и `catalog_dir`, и `sprite_source` в q.yaml записаны абсолютными путями |
| `test_moved_folder_renders_same` | 3 | GREEN | **GREEN** | — |
| `test_save_as_other_dir_keeps_images_and_relative_paths` | 4 | RED | **RED** | `assert not Path(data["catalog_dir"]).is_absolute()` → `True` (абсолютный) |
| `test_load_independent_of_cwd` | 5 | GREEN | **GREEN** | — |
| `test_absolute_and_scheme_ids_untouched` | 6 | GREEN | **GREEN** | — |
| `test_from_dict_roundtrip_after_from_yaml` | 7 | GREEN | **GREEN** | — |

Все 7 совпали с предсказанием REDS из брифа — расхождений нет. Все три RED падают
с `AssertionError`, показывающим реальный (абсолютизированный) вывод против ожидаемого
литерала/свойства — не `ImportError`/`SyntaxError` (значит окружение теста исправно) и
не `AttributeError` (значит `from_yaml`/`to_dict`/`to_yaml` уже существуют и работают,
просто резолвят пути безвозвратно в абсолютные — ровно та проблема, которую Task 1.0
должен закрыть).

Ruff: `All checks passed!` на файле теста.

## Что я истолковал, а не выполнил буквально

- Критерий 1 в брифе не уточнял, через `from_dict` или `from_yaml` грузить YAML перед
  проверкой `to_dict()`. Выбрал `from_yaml` — иначе тест тривиально зелёный и не проверяет
  ничего нового относительно критерия 7 (там явно `from_dict(p.to_dict())`, round-trip без
  файла). Фактический RED подтвердил, что это осмысленный выбор: именно `from_yaml`
  сейчас "портит" относительность на входе.
- Критерий 6 — компаунд из двух независимых проверок (абсолютный путь / `fixture://` id).
  Собрал в один тест с двумя блоками assert вместо двух отдельных функций — обе части
  прошли (GREEN), само сочетание в одном тесте не влияет на диагностику при падении
  (assert на первой половине остановил бы тест раньше второй).
- Слой `cap` в абсолютном yaml (критерий 6, первая часть) назвал `cap`, а не `base` —
  проверил по README: коллизия имени `base`/`damaged` действует только при заданном
  `catalog_dir`; в layers-only пресете это не проверялось явно тестом, выбрал безопасное
  имя, чтобы не привязывать критерий 6 к другому, непроверяемому здесь правилу.

## Что оставил открытым / ненадёжным

- Не проверял **почему** конкретно ломается относительность (нет доступа к `core/preset.py`)
  — тесты фиксируют наблюдаемое поведение через публичный API, не механизм. Разработчику
  предстоит решить, хранить ли исходную относительную строку отдельно от резолвленной, или
  вычислять относительный путь на лету в `to_dict`/`to_yaml` через `os.path.relpath` от
  некоторого base_dir.
- Критерий 4 проверяет только "не абсолютный" (`Path.is_absolute()`), не конкретное
  значение вида `../A/sprites` — сознательно (брифом не зафиксирован точный вид
  относительного пути при сохранении в другую директорию), но это значит тест примет
  любую относительную форму, включая потенциально хрупкую.
- Рендер-оракул сравнивает два независимых прогона через `np.array_equal`, а не литерал —
  по DESIGN брифа это осознанный выбор (пиксели зависят от `cv2`/платформы), но статус
  «не завязано на код под тестом» тут слабее, чем для литеральных проверок 1/2/4/6.
- Не запускал break-injection (не в скоупе tester per project-rules — это стадия 3,
  выполняется лидом отдельно, не делегируется).
- Один потенциальный leak-риск: при чтении `interfaces.py` увидел docstring
  `SceneCompositorProtocol`, упоминающий `core/scene_compositor.py` (Task 3.4) — файл не
  открывал и не использовал, это чужой (уже реализованный) модуль, не относящийся к Task 1.0
  (`preset.py`/`factory.py`). Называю явно, т.к. правило требует называть любой контакт с
  запрещённой зоны, даже касательный.

## Утечки

Нет. Все обращения — к файлам из списка Allowed (`interfaces.py`, `README.md`,
`__init__.py`, `Services/dataset_gen/core/catalog.py`). Не читал, не грепал и не
импортировал `core/preset.py`, `core/factory.py`, `core/catalog_bridge.py`,
`core/layered_object.py`, другие файлы `Services/line_sim/tests/`.

## Коммит

`1a23ff0b` (branch `test/ls-layer-1.0`) — `test(line_sim): [RED] редактор слоёв 1.0 —
переносимые пути пресета`.
