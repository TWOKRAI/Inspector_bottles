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

**2026-03-24**

- `docs/`: только актуальные гайды (`ARCHITECTURE`, `FRONTEND_MAP`, `RECIPES_SYSTEM`); планы и архивный разбор удалены из каталога (история — в `DECISIONS.md` и git).
- Рецепты: два пространства в одном YAML (`register_recipes` / `app_recipes`); вкладка «Рецепты» — только регистры; «Настройки» — app-рецепт через `AppRecipePanel` (база `RecipeSlotTablePanel`). См. `docs/RECIPES_SYSTEM.md`, ADR-081–082 в `multiprocess_framework/DECISIONS.md`.
- Документация: обновлена `docs/ARCHITECTURE.md` (карта запуска, каталог `managers/`, оценки прототипа и фреймворка); `managers/README.md`; наведение порядка (`.DS_Store`, `.gitignore`).
- Камера: поля `hikvision_frame_rate` / `exposure_time` / `gain` в `CameraConfig` и `apply_camera_register_update` → `set_parameters` при активном Hikvision (контракт с `CameraRegisters`).
- UI: опциональная телеметрия `frontend/diagnostics.py` + `GuiConfig.ui_diagnostics` / `INSPECTOR_UI_DIAGNOSTICS`; тесты `tests/test_ui_diagnostics.py`, `tests/support/gui_env.py` (ADR-083).
- Фронт: `FrontendAppContext` + `docs/FRONTEND_MAP.md` (карта слоёв, тесты без полного GUI); ADR-084.

**2026-03-23**

- `sim_webcam_widget` влит в `frontend/widgets/camera_common/` (`SimWebcamWidget`, presenter, binder, callbacks).
- Вкладки и `TabItemConfig`/`TabsConfig` в `frontend/widgets/tabs_setting/` (`camera_tab`, `processing_tab`, `recipes_tab`, `settings_tab`).
- `camera_tab`: `IRegistersManagerGui`, `RegisterBindingContext`, презентер/вью/колбэки; контролы — `frontend_module.components`, схемы — `schemas.py`.
- `CameraRegisters`: `hikvision_*` поля; processing tab без legacy fallback при отсутствии регистров — заглушка.

## Известные ограничения

- Hikvision требует модуль `hikvision_camera_module` (вне репозитория)
- GUI-тесты требуют DISPLAY (на headless CI пропускаются)
