# multiprocess_prototype — Статус

**Назначение:** Тестовый прототип для Multiprocess Framework.  
**Статус:** ✅ Рабочий

**Архитектура:** [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) · **Документация:** [docs/README.md](docs/README.md)

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

## Последние изменения (2026-03-23)

- `camera_tab`: презентер (Phase 2): `IRegistersManagerGui`, `RegisterBindingContext`, `CameraTabPresenter`/`CameraTabView`/`CameraTabCallbacks`; валидатор `label_attribute`
- Миграция на control_v2: `ui_config.py` → `schemas.py` (camera_tab, processing_tab, settings_tab)
- Все контролы через `frontend_module.components.control_v2`
- `CameraRegisters`: добавлены `hikvision_frame_rate`, `hikvision_exposure_time`, `hikvision_gain`
- Processing tab: legacy fallback удалён, при отсутствии RegistersManager — заглушка

## Известные ограничения

- Hikvision требует модуль `hikvision_camera_module` (вне репозитория)
- GUI-тесты требуют DISPLAY (на headless CI пропускаются)
