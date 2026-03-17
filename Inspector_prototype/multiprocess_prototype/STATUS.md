# multiprocess_prototype — Статус

**Назначение:** Тестовый прототип для Multiprocess Framework.  
**Статус:** ✅ Рабочий

---

## Текущее состояние

| Компонент | Описание |
|-----------|----------|
| **Процессы** | Camera, Processor, Renderer, Robot, GUI |
| **Камера** | UnifiedCameraProcess — simulator / webcam / hikvision, переключение без перезапуска |
| **SharedMemory** | camera_frame, processor_mask, rendered_frame, mask_frame |
| **GUI** | PyQt, чекбоксы Original / Mask / Contours |

---

## Структура (после рефакторинга)

```
processes/          — все процессы (в т.ч. unified_camera_process)
backend/            — бэкенды камеры (Simulator, Webcam, Hikvision)
configs/            — Pydantic-конфиги
gui/, utils/        — GUI и утилиты
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
