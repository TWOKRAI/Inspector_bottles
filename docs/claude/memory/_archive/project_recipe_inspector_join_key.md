---
name: project-recipe-inspector-join-key
description: Рецепт — inspector(join) обязан быть ПРЯМЫМ ключом процесса, не под metadata (иначе join молча выключен)
metadata:
  type: project
---

В рецептах v3 блок `inspector:` (режим корреляции DataReceiver) ОБЯЗАН быть **прямым ключом процесса** (сиблинг `plugins`/`chain_targets`), а НЕ под `metadata:`. Бэкенд: `unwrap_recipe` → `normalize_blueprint` → `ProcessConfig.inspector`; `generic_process.py::_build_inspector` читает `config.inspector.mode`. Под `metadata:` поле уходит в `ProcessConfig.metadata` → `inspector` пустой → mode по умолчанию **`fanin`** (InspectorManager), а НЕ `join` (JoinInspectorManager).

**Симптом (стоил долгой отладки 2026-06-16):** многовходовой узел (overlay_draw: frame+overlay; center_crop: frame+overlay/filtered) НЕ сливает входы → primary (кадр) проходит left-join один, second-вход (overlay) теряется. Видимо: кадр и круги рисуются, а **линия line_filter НЕ рисуется И триггер center_crop не срабатывает** (recog пуст). Ошибок в логе НЕТ — «молча».

**ПОЧИНЕНО (fix-forward, 2026-06-16):** `backend/launch.py::unwrap_recipe` теперь поднимает `inspector` из `metadata` в прямой ключ (`_hoist_inspector_from_metadata`) при загрузке ЛЮБОГО рецепта/топологии. GUI-save больше НЕ ломает join — обе формы honor-ятся. Заодно автоматически чинятся legacy `letter_angle_inspect`, `dataset_circle_capture`. Регресс-тест в `recipes/tests/`.

**Предыстория грабли:** GUI при пересохранении рецепта переносит `inspector` под `metadata` (домен-entity `Process` не имеет поля `inspector` → `_fold_extra_into_metadata` сворачивает туда). Раньше это молча выключало join. Рабочий эталон прямого ключа: `line_filter_inspect.yaml`.

**Проверка headless:** `unwrap_recipe(raw)` → у процесса `p.get('inspector')` должен дать `{mode: join, ...}`, а `p['metadata'].get('inspector')` — None.

Связано: [[project_line_filter_feature]], [[project_pult_control_panel]].
