# Phase 1: Camera

**Статус:** 🟡 IN PROGRESS

## Цель

Добавить capture-плагин, доказать что кадры попадают в SHM и IPC-сообщения проходят между процессами.

## Задачи

### Task 1.1 — Capture Plugin
**Level:** Middle (Sonnet)
**Goal:** Скопировать и адаптировать CapturePlugin из прототипа v1
**Files:**
- `plugins/capture/plugin.py`
- `plugins/capture/config.py`
**Steps:**
1. Скопировать `multiprocess_prototype/plugins/cameras/camera_service/` 
2. Адаптировать импорты под prototype_2
3. Убедиться что SHM ring buffer создаётся через PluginConfig.memory
**Acceptance criteria:**
- [ ] CapturePlugin регистрируется через @register_plugin
- [ ] SHM создаётся автоматически из config.memory
- [ ] Кадры пишутся в ring buffer

### Task 1.2 — Frame Counter Plugin
**Level:** Junior (Sonnet)
**Goal:** Простой плагин-получатель для проверки IPC
**Files:**
- `plugins/frame_counter/plugin.py`
- `plugins/frame_counter/config.py`
**Steps:**
1. Создать плагин с input port `frame` (dtype: image/bgr)
2. При получении frame_ready — инкрементировать счётчик и логировать
**Acceptance criteria:**
- [ ] Считает полученные кадры
- [ ] Логирует FPS каждые N секунд

### Task 1.3 — Topology с Wire
**Level:** Junior (Sonnet)
**Goal:** JSON topology с двумя процессами и wire между ними
**Files:**
- `topology/phase1_camera.json`
**Steps:**
1. Процесс `camera_0` с CapturePlugin
2. Процесс `counter` с FrameCounterPlugin
3. Wire: `camera_0.capture.frame → counter.frame_counter.frame`
**Acceptance criteria:**
- [ ] Blueprint.check() проходит без ошибок
- [ ] Wire-совместимость портов валидируется
- [ ] Frame counter логирует полученные кадры

## Оценка прототипа v1

**Что было:** CameraProcess — полноценный хардкод-класс (~300 строк) с:
- Ручным созданием SHM ring buffer
- Ручной регистрацией middleware
- Ручной подпиской StateProxy
- Service layer (CameraService) с абстрактным backend

**Что улучшаем:**
- SHM через PluginConfig.memory (декларативно)
- Middleware через plugin configure() (явно)
- Backend switching через config field (без if/else фабрики)

## Зависимости от фреймворка

- GenericProcess должен корректно создавать SHM из PluginConfig.memory
- Wire routing должен работать (доставка frame_ready между процессами)
