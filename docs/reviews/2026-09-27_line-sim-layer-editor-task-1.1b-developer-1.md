# Task 1.1b, часть 1/2 (движок) — отчёт разработчика

**Роль:** developer · **Ветка:** feat/line-sim-layer-editor · **Дата:** 2026-09-27

## Что сделано

Блок A (слой класса `class://`) и блок B (заливка слоя `color_rgb`) — движок
(`Services/line_sim/interfaces.py`, `core/preset.py`, `core/factory.py`,
`core/layered_object.py`, `__init__.py`) + 5 hazard-тестов автора
(`Services/line_sim/tests/test_hazards_1_1b_engine.py`).

**A.** `CLASS_SPRITE_SOURCE = "class://"` в `core/preset.py`, экспорт из
`Services.line_sim`. `ScenePreset` отклоняет: >1 слой `class://`, слой `class://` без
`catalog_dir`, слой `class://` в `mode="defect"` — все три `ValidationError` с именем
слоя. `ObjectFactory` не грузит картинку под `class://` (маркер), `make()` подставляет
разыгранный `base_sprite` НА МЕСТО слоя в списке (без отдельного `base`), пятно дефекта
строится по нижнему слою (`bottom_layers[0]`) после подстановки.

**B.** `LayerSpec.color_rgb: tuple[int,int,int] | None`, валидация 0..255 в
`field_validator(mode="before")` (длина и диапазон канала — с именем слоя; стандартная
pydantic-ошибка `tuple[int,int,int]` на кортеже длины 2 имя слоя не несёт).
`LayeredObject._transform`: заливка → scale → поворот → тон. `layer_params[слой]
["color_rgb"]` — цвет ПОСЛЕ сдвига тона слоя, простые `int` (не `np.uint8`).

## Что я истолковал, а не выполнил буквально

**ObjectFactory.make() теперь работает без `catalog_dir` (только `layers`) — этого нет
в DESIGN.** RED-тесты `test_acceptance_1_1b_layer_color.py::test_color_fill_*` строят
`ScenePreset(layers=[...])` БЕЗ `catalog_dir` и ожидают, что `.make()` отрендерит объект.
До этой задачи `make()` безусловно поднимал `ValueError`, если каталог не загружен —
так было задокументировано в докстринге класса (Task 3.2) и НЕ упомянуто в DESIGN этой
задачи. Я добавил ветку: `catalog_dir is None` → `class_name = ""`, слои — только
`preset.layers` (без авто-`base`), угол по-прежнему из `rng.uniform`. Проверил grep'ом —
ни один существующий тест (кроме новых REDS) не полагается на прежний `ValueError`, так
что относительно безопасно, но это решение не мной санкционировано на уровне DESIGN.
Если это неверный контракт — пожалуйста, скажите, поправлю.

## Находка при написании hazard-теста (H1)

Наивное «заменить `class://` на обычный файловый слой того же размера в той же позиции
списка» — НЕ сравнение слоёв одинаковой длины: без `class://` в пресете `ObjectFactory`
ВСЕГДА добавляет отдельный `"base"` (даже когда в `layers` уже есть слой на этом месте),
а со слоем `class://` — не добавляет. Сосед `top` из-за этого попадает на РАЗНЫЕ индексы,
и сравнение ловит этот сдвиг, а не свойство "class:// не сдвигает соседей". Починил
сравнением против пресета БЕЗ `catalog_dir` (Task 1.1b, блок B) — там `base` тоже не
добавляется, длины списков совпадают. Задокументировано в докстринге теста.

## Тесты

```
PYTHONPATH=$PWD .venv/bin/python -m pytest Services/line_sim/tests Plugins/sim/scene_source -q --tb=short
```
293 passed, 2 failed (font-tool — часть 2, ожидаемо red), 1 skipped (пред-существующий,
не мой). `ruff check Services/line_sim` — чисто.

Акцептанс-файлы по отдельности: `test_acceptance_1_1b_class_layer.py` 9/9,
`test_acceptance_1_1b_layer_color.py` 4/4. Hazard-файл: 5/5.

## Что оставил открытым / ненадёжным

- **Каталог-less `make()` — решение из предыдущего раздела не согласовано с лидом явно.**
  Наибольший риск отчёта.
- H1/H2 сравнивают ДВА прогона с ОДНИМ и тем же seed друг с другом (не с литералом) —
  это осознанный выбор для проверки структурного свойства (независимость rng.spawn()
  от контента/веток), не «тест согласен с любым ответом»: конкретные числовые значения
  не важны, важно их РАВЕНСТВО между веткой реализации A и веткой B.
  Ожидаемый упавший список при break-injection лидом не писал я — предполагаю, что это
  часть шага 3 (лид, никогда не делегируется).
  Соответствие C1/C2 (шрифты) и D (пресет `letters_layered.yaml`) — это часть 2/2,
  не входит в этот коммит.
- `_check_color_rgb` дополнительно отклоняет `bool` как канал (в Python `bool` —
  подкласс `int`) — однострочная защита сверх буквы спеки, не строила отдельного теста
  под неё (проверил только вручную интерактивно не проверял, полагаюсь на код-ревью).

## Файлы

- `/Users/twokrai/Project_code/Inspector_bottles/.claude/worktrees/ls-layer/Services/line_sim/interfaces.py`
- `/Users/twokrai/Project_code/Inspector_bottles/.claude/worktrees/ls-layer/Services/line_sim/core/layered_object.py`
- `/Users/twokrai/Project_code/Inspector_bottles/.claude/worktrees/ls-layer/Services/line_sim/core/preset.py`
- `/Users/twokrai/Project_code/Inspector_bottles/.claude/worktrees/ls-layer/Services/line_sim/core/factory.py`
- `/Users/twokrai/Project_code/Inspector_bottles/.claude/worktrees/ls-layer/Services/line_sim/__init__.py`
- `/Users/twokrai/Project_code/Inspector_bottles/.claude/worktrees/ls-layer/Services/line_sim/tests/test_hazards_1_1b_engine.py`
