# multiprocess_prototype — Статус

**Назначение:** Тестовый прототип для Multiprocess Framework.  
**Статус:** ✅ Рабочий

**Архитектура:** [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) · **Фронт (карта):** [docs/FRONTEND_MAP.md](docs/FRONTEND_MAP.md) · **Документация:** [docs/README.md](docs/README.md)

---

## Текущее состояние

| Компонент | Описание |
|-----------|----------|
| **Процессы** | Camera, Processor, Renderer, Robot, Database, GUI |
| **Камера** | UnifiedCameraProcess — simulator / webcam / hikvision, переключение без перезапуска |
| **SharedMemory** | camera_frame, processor_mask, rendered_frame, mask_frame |
| **GUI** | `GuiProcess` + `GuiConfig` (`backend/processes/gui/`), `GuiProcessMixin`, `FrontendLauncher`, PyQt |
| **Данные** | `persistence/`: `INSPECTOR_DATA_DIR` или `~/.inspector_prototype`, `user_prefs.json` (camera_type) |

---

## Запуск

```bash
./Inspector_prototype/multiprocess_prototype/run.sh
```

---

## Последние изменения

**2026-03-25**

- **Touch-клавиатура:** **`FrontendConfig.touch_keyboard`** → **`build_dict`** / **`FrontendAppContext.get_touch_keyboard`**; вкладки рецептов / настроек / ROI / постобработки передают dict в деревья и **`bind_touch_keyboard_line_edit`** для **`QLineEdit`** (слот, имя региона). ADR-097 в `multiprocess_framework/DECISIONS.md`.

- **Логические камеры (UI):** **`ProcessorRegisters.logical_camera_ids`**; **`ensure_logical_camera_and_seed_roi`** ([`frontend/coordinators/logical_cameras.py`](frontend/coordinators/logical_cameras.py)) после смены типа на вкладке камеры; ROI/постобработка — **`camera_ids_union`** + **`subscribe_all`** на регистр **`processor`**. Пустой **`process_targets`** в **`FieldMeta`** → **`RegistersManager`** не шлёт **`register_update`** (ADR-094). Нормализация **`post_processing_payload`** сохраняет пустые списки по камерам.
- **Данные / рецепты:** канон вложенных полей **`crop_regions`** / **`post_processing_regions`** вынесен в **`registers/schemas/processing_tab/`** (`crop_regions_payload`, `post_processing_payload`, `PostProcessingRegionEntry`); **`ProcessorRegisters`** нормализует payload при validate; **`snapshot_migrate.migrate_register_recipe_snapshot`** вызывается из **`RecipeManager.load_recipe_to_registers`**. Документ **`docs/DATA_MODEL_NESTED.md`**; ADR-093 в `multiprocess_framework/DECISIONS.md`.
- **Постобработка:** вкладка `post_processing` — `PostProcessingTabWidget` + `PostProcessingPanelWidget` (BaseWidget); поле **`ProcessorRegisters.post_processing_regions`** (`camera` → список регионов с x1,y1,x2,y2 и флагами); без App DataManager; ADR-092 в `multiprocess_framework/DECISIONS.md`. Во **`frontend_module.core.qt_imports`** добавлен **`QSpinBox`**.

**2026-03-25** (ранее)

- ROI (`cropped_regions_widget`): разметка камера → таблица → кнопки → группа «Параметры области (ROI)»; структура **камера → регион → [x, y, width, height]** в `ProcessorRegisters.crop_regions`; ADR-091 в `multiprocess_framework/DECISIONS.md`.
- Фронт: разделение **tab shell** (`BaseTab`) и **фиче-виджетов** (`BaseWidget` + MVP): панели рецептов (`RegisterRecipePanelWidget`, `AppRecipePanelWidget`), ROI (`CroppedRegionsPanelWidget`), обработка (`ProcessingPanelWidget`); доки фреймворка `TAB_STRUCTURE.md` / `MVP_TEMPLATE.md` / `widgets/README.md` прототипа.
- Фронт: зафиксированы слои **виджет / Presenter / `managers`** в `docs/FRONTEND_MAP.md` и `frontend/widgets/README.md`; пакет `frontend/coordinators/` (общие чистые хелперы); `FrontendAppContext.get_*_tab_ui` / `get_recipe_access`; ADR-090 в `multiprocess_framework/DECISIONS.md`.

**2026-03-24**

- `docs/`: только актуальные гайды (`ARCHITECTURE`, `FRONTEND_MAP`, `RECIPES_SYSTEM`); планы и архивный разбор удалены из каталога (история — в `DECISIONS.md` и git).
- Рецепты: два пространства в одном YAML (`register_recipes` / `app_recipes`); вкладка «Рецепты» — только регистры; «Настройки» — app-рецепт через `AppRecipePanel`. См. `docs/RECIPES_SYSTEM.md`, ADR-081–082 в `multiprocess_framework/DECISIONS.md`.
- Документация: обновлена `docs/ARCHITECTURE.md` (карта запуска, каталог `managers/`, оценки прототипа и фреймворка); `managers/README.md`; наведение порядка (`.DS_Store`, `.gitignore`).
- Камера: поля `hikvision_frame_rate` / `exposure_time` / `gain` в `CameraConfig` и `apply_camera_register_update` → `set_parameters` при активном Hikvision (контракт с `CameraRegisters`).
- UI: опциональная телеметрия `frontend/diagnostics.py` + `GuiConfig.ui_diagnostics` / `INSPECTOR_UI_DIAGNOSTICS`; тесты `tests/test_ui_diagnostics.py`, `tests/support/gui_env.py` (ADR-083).
- Фронт: `FrontendAppContext` + `docs/FRONTEND_MAP.md` (карта слоёв, тесты без полного GUI); ADR-084.

**2026-03-23**

- `sim_webcam_widget` влит в `frontend/widgets/camera_common/` (`SimWebcamWidget`, presenter, binder, callbacks).
- Вкладки — пакеты `frontend/widgets/*_tab/`; `TabItemConfig`/`TabsConfig` в `frontend/widgets/tabs_setting/` (реэкспорт вкладок).
- `camera_tab`: `IRegistersManagerGui`, `RegisterBindingContext`, презентер/вью/колбэки; контролы — `frontend_module.components`, схемы — `schemas.py`.
- `CameraRegisters`: `hikvision_*` поля; processing tab без legacy fallback при отсутствии регистров — заглушка.

## Известные ограничения

- Hikvision требует модуль `hikvision_camera_module` (вне репозитория)
- GUI-тесты требуют DISPLAY (на headless CI пропускаются)
