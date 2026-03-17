# multiprocess_prototype\stage_reports\archived\STAGE_02_MESSAGE_ADAPTER.md
# STAGE 02: Внедрение MessageAdapter для создания сообщений

**Дата:** 2026-03-15  
**Статус:** Выполнено

## Действия

### 1. CameraProcess
- Добавлен `self._msg = MessageAdapter(sender=self.name)` в `_init_application_threads()`
- Заменён ручной dict на `self._msg.data()` для frame_ready
- `self.send_message("processor", notification.to_dict())`

### 2. ProcessorProcess
- Добавлен MessageAdapter
- `self._msg.data()` для detection_result
- `self._msg.event()` для frame_processed (обратная связь в Camera)

### 3. RendererProcess
- Добавлен MessageAdapter
- `self._msg.data()` для rendered_frame_ready
- `self._msg.command()` для reject_item (с `data=` для совместимости с handle_command)
- `self._msg.event()` для frame_rendered

### 4. GuiProcess
- Добавлен MessageAdapter
- `self._msg.command()` для start_capture, stop_capture, set_fps, set_threshold
- Для команд передаётся `data=` для совместимости с CommandManager.handle_command (data_field="data")

### 5. RobotSimulatorProcess
- Не изменён — только получает сообщения, не отправляет

## Совместимость с CommandManager

CommandManager.handle_command ожидает `message["data"]` (data_field="data"). MessageAdapter.command() использует `args`. Для совместимости передаётся явно `data=payload` в kwargs.

## Тестирование

- Импорты проверены
- Все сообщения теперь имеют id, timestamp, правильный type через MessageAdapter

## Известные проблемы

- Нет
