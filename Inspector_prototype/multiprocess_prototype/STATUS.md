# multiprocess_prototype — Статус

**Назначение:** Тестовый прототип для Multiprocess Framework.  
**Статус:** ✅ Рабочий

---

## Текущее состояние

| Компонент | Описание |
|-----------|----------|
| **Процессы** | Camera, Processor, Renderer, Robot, Database, GUI |
| **Камера** | UnifiedCameraProcess — simulator / webcam / hikvision, переключение без перезапуска |
| **SharedMemory** | camera_frame, processor_mask, rendered_frame, mask_frame |
| **GUI** | GuiProcess в `backend/processes/gui_process.py` (frontend_module + FrontendLauncher), PyQt |

---

## Структура (после рефакторинга 2026-03)

```
backend/            — configs/, modules/, processes/, shared/, database/, backends.py
  configs/          — ProcessConfigBase, app_config, Robot/Database/Gui; camera/processor/renderer реэкспорт из modules
  modules/          — camera/, processor/, renderer/ (у каждого: process.py, config.py, домен)
  processes/        — gui, database, robot + реэкспорт UnifiedCamera/Processor/Renderer из modules
  shared/           — message_as_dict и др.
  database/         — DetectionSchema, utils, export_detections
backend/gui_process_mixin.py — GuiProcessMixin (избегает цикла import с frontend)
backend/README.md   — структура backend
frontend/           — configs/, launcher.py, mixins/ (реэкспорт), windows/, widgets/
  configs/          — GuiConfigFrontend, FrontendConfig (реестр окон в frontend_config)
  launcher.py       — FrontendLauncher (окна, регистры)
  windows/          — MainWindow, Loading, InspectorWindow (тесты)
registers/          — create_registers() (фабрика для GUI и backend)
utils/              — FrameGenerator, WebcamCapture, shm_utils
```

Удалены дубли: multiprocess_prototype/database/, Inspector_prototype/processes/

---

## Запуск

```bash
./Inspector_prototype/multiprocess_prototype/run.sh
```

---

## Известные ограничения

- Hikvision требует модуль `hikvision_camera_module` (вне репозитория)
- GUI-тесты требуют DISPLAY (на headless CI пропускаются)
