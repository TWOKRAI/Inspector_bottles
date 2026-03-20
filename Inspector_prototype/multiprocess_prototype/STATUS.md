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

## Известные ограничения

- Hikvision требует модуль `hikvision_camera_module` (вне репозитория)
- GUI-тесты требуют DISPLAY (на headless CI пропускаются)
