# Task W2-c2c: поля `plate_*` в схеме дисплея; вкладка Displays их не теряет

- **Статус:** [PENDING] · **Level:** Middle · **Assignee:** developer
- **Module contract:** public-api-change (`DisplayDefinition`, `DisplaySpec`: четыре необязательных поля)
- **Dependencies:** нет. Ветка `dev/w2-c2`, параллельно с W2-c2b (файлы не пересекаются).
- **Gate:** `machine_gate.sh light <session>` по TESTS; радиус `multiprocess_prototype/domain/tests`, `multiprocess_prototype/frontend/widgets/tabs/displays/tests`, `multiprocess_prototype/adapters/tests/test_recipe_canonical.py`
- **Files:** `multiprocess_prototype/domain/entities/display.py`, `multiprocess_prototype/domain/protocols/display_catalog.py`, `multiprocess_prototype/frontend/widgets/tabs/displays/presenter.py`, `multiprocess_prototype/domain/tests/test_display_plate_fields.py`, `multiprocess_prototype/frontend/widgets/tabs/displays/tests/test_presenter_plate_fields.py`, `multiprocess_prototype/domain/DECISIONS.md`
- **Handoff:** lead -> tester (слепой, свой файл `multiprocess_prototype/domain/tests/test_display_plate_fields_blind.py`) -> developer (REDS, тесты tester-а не правит, break-injection) -> reviewer (sonnet)

Основание: П6, `plate-modes.md`.
- `DisplayDefinition` — `extra="forbid"` (`domain/entities/display.py:120-124`): рецепт с `plate_*` сегодня не проходит `Recipe.from_dict`.
- Вкладка Displays гонит определение через `DisplaySpec` (`domain/protocols/display_catalog.py:25-54`, `definition_to_spec` `:98`, `spec_to_definition_dict` `:138`). Reviewer воспроизвёл: `update(enabled=False)` пишет `hold/2/""/""` поверх `silence/5/"{title}"/"cam_0.camera_device"`; дубликат (`presenter.on_duplicate`, `:301-336`) теряет все четыре поля.

TASK: W2-c2c — четыре поля в схеме; переключение и дубликат во вкладке Displays сохраняют их   PLAN: plans/2026-11-25_multicam-observability/plan.md (П6)
ROLE: developer
CHAIN: lead -> you -> reviewer ; потребитель: W2-c2b (то же правило проверки), W2-c3
DESIGN (decided by the lead — you type it, you do not derive it):
  1. `DisplayDefinition` (после `crop`, с `FieldMeta`):
     - `plate_mode: str = "hold"` — валидатор `{"hold", "silence", "trigger"}`, как `_validate_fit`;
     - `plate_after_s: int = 2` — `field_validator("plate_after_s", mode="before")`: `type(v) is not int` или вне 1..600 -> `ValueError`;
     - `plate_text: str = ""`, `plate_source: str = ""`.
     - `exc.errors()[0]["msg"]` содержит имя поля; для `plate_mode "blink"` в `msg` нет `blink`; для `plate_after_s` значение не проверять.
     - Докстринг класса — абзац «Плашка (П6)»: режимы, порог, шаблон, источник.
  2. `DisplaySpec`: те же четыре поля с теми же умолчаниями; `definition_to_spec` и `spec_to_definition_dict` переносят их.
  3. `presenter.on_duplicate`: новый `DisplaySpec` копирует четыре поля из `source`. Формы правки нет.
  4. `domain/DECISIONS.md` — короткая запись: «поля плашки в `DisplayDefinition` (П6, 2026-11-26); умолчания `minimize` не пишет; правило `plate_after_s` одно для домена и GUI».
FILES (complete list — nothing else; need another file -> stop and ask the lead):
  1. multiprocess_prototype/domain/entities/display.py
  2. multiprocess_prototype/domain/protocols/display_catalog.py
  3. multiprocess_prototype/frontend/widgets/tabs/displays/presenter.py
  4. multiprocess_prototype/domain/tests/test_display_plate_fields.py — новый
  5. multiprocess_prototype/frontend/widgets/tabs/displays/tests/test_presenter_plate_fields.py — новый: presenter поверх настоящего `DisplayCatalogFromRecipe` + `RecipeStoreFromManager` (`RecipeManager` с `InspectorRecipeFormatHook`) над YAML в `tmp_path`; `FakeDisplayCatalog` не использовать; ожидаемые значения читать из файла
  6. multiprocess_prototype/domain/DECISIONS.md
REDS (predicted red tests):
  - test_display_plate_fields.py::test_accepts_plate_fields (`silence`, `5`, `"{title}"`, `"cam_0.camera_device"` -> те же четыре значения; `{"id": "d"}` -> `"hold"`, `2`, `""`, `""`)
  - test_display_plate_fields.py::test_rejects_bad_mode_and_range (`plate_mode "blink"`; `plate_after_s` `0`, `601`, `True`, `"5"`, `5.0` -> `ValidationError`; `exc.errors()[0]["msg"]` содержит имя поля; для `plate_mode "blink"` в `msg` нет `blink`; для `plate_after_s` значение не проверять)
  - test_display_plate_fields.py::test_minimize_drops_defaults (`minimize(("displays", 0), {"id": "d", "plate_mode": "hold", "plate_after_s": 2, "plate_text": "", "plate_source": ""}) == {"id": "d"}`; с `"silence"`, `5` оба ключа остаются)
  - test_presenter_plate_fields.py::test_toggle_enabled_keeps_plate_fields (в файле у исходного экрана `silence`, `5`, `"{title}"`, `"cam_0.camera_device"` после `on_set_enabled("d", False)`)
  - test_presenter_plate_fields.py::test_duplicate_keeps_plate_fields (у `d_copy` в файле те же четыре после `on_duplicate("d")`)
ACCEPTANCE (every number with its command):
  - `<py> -m pytest -q --tb=short multiprocess_prototype/domain/tests/test_display_plate_fields.py multiprocess_prototype/frontend/widgets/tabs/displays/tests/test_presenter_plate_fields.py` -> exit 0, 5 passed
  - `<py> -m pytest -q --tb=short multiprocess_prototype/domain/tests multiprocess_prototype/frontend/widgets/tabs/displays/tests multiprocess_prototype/adapters/tests/test_recipe_canonical.py` -> exit 0, число в отчёте
  - `ruff check -q` по пяти .py -> 0
  - Break-injection: `spec_drops_plate` (`definition_to_spec` без полей) -> `test_toggle…`, `test_duplicate…`; `after_s_coerced` (без `mode="before"`) -> `test_rejects…`; `default_written` -> `test_minimize…`
TESTS: bash "$(git rev-parse --path-format=absolute --git-common-dir)/../scripts/machine_gate.sh" light <session> <py> -m pytest -q --tb=short multiprocess_prototype/domain/tests/test_display_plate_fields.py multiprocess_prototype/frontend/widgets/tabs/displays/tests/test_presenter_plate_fields.py
OUT OF SCOPE: поля в форме вкладки Displays; `DisplayEntrySchema` бэкенда (лишнее игнорирует); GUI плашки (W2-c2b).
TRAPS: `bool` — подкласс `int`: проверка `type(v) is int`, не `isinstance`. `DisplaySpec` — `@dataclass(frozen=True, slots=True)`: поля с умолчаниями в конец.
HANDOFF IN: —
REPORT: STATUS, files, вывод ACCEPTANCE, красные до/после, «Что оставил открытым / ненадёжно».
