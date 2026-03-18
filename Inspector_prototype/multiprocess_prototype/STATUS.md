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
| **GUI** | GuiProcessFrontend (frontend_module), PyQt, чекбоксы Original / Mask / Contours |

---

## Структура (после рефакторинга)

```
backend/            — configs/, processes/, modules/
  configs/          — CameraConfig, ProcessorConfig, RendererConfig, RobotConfig, DatabaseConfig, GuiConfig
  processes/        — camera, processor, renderer, robot, database, gui (legacy)
frontend/           — config, process, registers, windows/
  config.py         — GuiConfigFrontend
  process.py        — GuiProcessFrontend (FrontendManager)
  registers.py      — create_frontend_registers()
  windows/          — InspectorWindow
configs/            — реэкспорт из backend.configs + frontend (совместимость)
gui/, utils/        — GUI виджеты, утилиты
```

---

## Запуск

```bash
./Inspector_prototype/multiprocess_prototype/run.sh
```

---

## Известные ограничения

- Hikvision требует модуль `hikvision_camera_module` (вне репозитория)
- GUI-тесты требуют DISPLAY (на headless CI пропускаются)
