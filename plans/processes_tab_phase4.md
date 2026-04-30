# Plan: Процессы — Фаза 4 (Pause + Workers + Дерево)

**Дата:** 2026-04-28
**Статус:** DRAFT

## Обзор

Три связанных фичи для вкладки "Процессы": (1) пауза/возобновление процессов через IPC, (2) передача данных о workers в heartbeat и broadcast, (3) раскрываемое дерево с workers как дочерними узлами. Задачи идут последовательно: фреймворк -> данные -> GUI.

## Порядок выполнения

### Фаза 1: Фреймворк — pause/resume + pause_all/resume_all

- Task 1.1: pause_all_workers / resume_all_workers в WorkerManager [PENDING]
- Task 1.2: Встроенные команды worker.pause_all / worker.resume_all в ProcessModule [PENDING]
- Task 1.3: Команды process.pause / process.resume в ProcessManagerProcess [PENDING]
- Task 1.4: Статус "paused" в ProcessMonitor [PENDING]

### Фаза 2: Данные — workers в heartbeat и broadcast

- Task 2.1: Workers status в heartbeat от ProcessModule [PENDING]
- Task 2.2: Workers data в ProcessMonitor broadcast [PENDING]
- Task 2.3: Workers data в ProcessMonitorModel (GUI) [PENDING]

### Фаза 3: GUI — кнопка паузы и раскрываемое дерево

- Task 3.1: Кнопка Pause/Resume в ProcessControlPanel [PENDING]
- Task 3.2: Регистрация process.pause / process.resume в routing/catalog [PENDING]
- Task 3.3: Раскрываемое дерево с workers [PENDING]

---

## Детальные спецификации задач

### Task 1.1 -- pause_all_workers / resume_all_workers в WorkerManager

**Уровень:** Middle (Sonnet, normal)
**Исполнитель:** developer
**Цель:** Добавить групповые методы паузы/возобновления всех воркеров в WorkerManager.

**Контекст:** WorkerManager уже имеет `pause_worker(name)` и `resume_worker(name)` для отдельных воркеров (строки 107-121 в `worker_manager.py`). Также есть `start_all_workers()` и `stop_all_workers()` как образцы групповых операций (строки 127-135). Нужно по аналогии добавить `pause_all_workers()` и `resume_all_workers()`.

**Файлы:**
- `multiprocess_framework/modules/worker_module/core/worker_manager.py` -- добавить методы
- `multiprocess_framework/modules/worker_module/interfaces.py` -- добавить в интерфейс IWorkerManager
- `multiprocess_framework/modules/worker_module/adapters/worker_adapter.py` -- проксировать через адаптер
- `multiprocess_framework/modules/worker_module/tests/test_worker_manager.py` -- тесты

**Шаги:**
1. В `worker_manager.py` после `stop_all_workers()` (строка 135) добавить:
   ```python
   def pause_all_workers(self) -> None:
       for name in self._worker_registry.get_all_names():
           self.pause_worker(name)
       self._log_info("All workers paused")

   def resume_all_workers(self) -> None:
       for name in self._worker_registry.get_all_names():
           self.resume_worker(name)
       self._log_info("All workers resumed")
   ```
2. В `interfaces.py` в интерфейс `IWorkerManager` добавить сигнатуры `pause_all_workers(self) -> None` и `resume_all_workers(self) -> None`.
3. В `worker_adapter.py` добавить проксирующие методы по аналогии с `pause_worker`/`resume_worker`.
4. В `test_worker_manager.py` добавить тест `test_pause_all_resume_all_workers`.

**Критерии приемки:**
- [ ] `WorkerManager.pause_all_workers()` ставит на паузу все зарегистрированные воркеры
- [ ] `WorkerManager.resume_all_workers()` возобновляет все воркеры
- [ ] Методы доступны через адаптер (WorkerAdapter)
- [ ] Тест проходит: `python -m pytest multiprocess_framework/modules/worker_module/tests/test_worker_manager.py -k "pause_all" -v`

**Вне скоупа:** Фильтрация воркеров (например, пауза только application-воркеров). Это можно добавить позже.

**Зависимости:** нет

---

### Task 1.2 -- Встроенные команды worker.pause_all / worker.resume_all в ProcessModule

**Уровень:** Middle+ (Sonnet, extended thinking)
**Исполнитель:** developer
**Цель:** Каждый дочерний ProcessModule должен уметь обрабатывать IPC-команды для паузы/возобновления своих воркеров.

**Контекст:** ProcessModule получает IPC-команды через `router_manager -> command_manager.handle_command()` (см. `process_lifecycle.py` строки 140-163). Команды регистрируются в `command_manager` и автоматически пробрасываются в router. Для pause нужно зарегистрировать команды `worker.pause_all` и `worker.resume_all` во ВСЕХ ProcessModule при инициализации.

**Файлы:**
- `multiprocess_framework/modules/process_module/core/process_module.py` -- регистрация команд
- `multiprocess_framework/modules/process_module/lifecycle/process_lifecycle.py` -- при необходимости

**Шаги:**
1. В `process_module.py` в методе `run()` (строка 488) или в `_init_custom_managers()` / после инициализации `command_manager` — зарегистрировать встроенные команды:
   - `worker.pause_all` -> вызывает `self.worker_manager.pause_all_workers()`
   - `worker.resume_all` -> вызывает `self.worker_manager.resume_all_workers()`
2. Место регистрации: в `process_lifecycle.py` метод `_register_commands_with_router` (строка 140) — здесь уже происходит связка command_manager с router. Но регистрировать сами команды нужно ДО этого вызова, в `initialize()`.
3. Добавить метод `_register_builtin_process_commands()` в ProcessModule, вызываемый в `initialize()` после создания command_manager и worker_manager:
   ```python
   def _register_builtin_process_commands(self) -> None:
       if not self.command_manager or not self.worker_manager:
           return
       self.command_manager.register_command(
           "worker.pause_all",
           lambda data=None, **kw: self.worker_manager.pause_all_workers() or {"success": True},
           metadata={"description": "Поставить все воркеры на паузу"},
       )
       self.command_manager.register_command(
           "worker.resume_all",
           lambda data=None, **kw: self.worker_manager.resume_all_workers() or {"success": True},
           metadata={"description": "Возобновить все воркеры"},
       )
   ```
4. Вызвать `_register_builtin_process_commands()` в `process_lifecycle.py` в методе `initialize()`, после строки с `_init_system_threads` и до `_register_commands_with_router`.

**Критерии приемки:**
- [ ] Любой дочерний ProcessModule принимает IPC-команду `worker.pause_all` и ставит все свои воркеры на паузу
- [ ] Любой дочерний ProcessModule принимает IPC-команду `worker.resume_all` и снимает паузу
- [ ] Heartbeat-воркер НЕ ставится на паузу (он должен продолжать слать heartbeat) — проверить, что pause_event у heartbeat_sender не затрагивается, либо добавить фильтр по worker_type

**Edge cases:**
- Heartbeat-воркер: если он тоже будет поставлен на паузу, ProcessMonitor решит что процесс unresponsive. Нужно либо (а) не ставить на паузу system-воркеров (heartbeat_sender), либо (б) в `pause_all_workers()` фильтровать по `worker_type != SYSTEM`. Рекомендация: вариант (б) — добавить параметр `exclude_system=True` в `pause_all_workers()`.

**Вне скоупа:** Добавление команд в ProcessManagerProcess (это Task 1.3).

**Зависимости:** Task 1.1

---

### Task 1.3 -- Команды process.pause / process.resume в ProcessManagerProcess

**Уровень:** Middle+ (Sonnet, extended thinking)
**Исполнитель:** developer
**Цель:** PM обрабатывает `process.pause` / `process.resume`, отправляя IPC-команду дочернему процессу.

**Контекст:** ProcessManagerProcess._register_builtin_commands() (строка 184) регистрирует команды `process.start`, `process.stop` и т.д. По аналогии нужно добавить `process.pause` и `process.resume`. Логика: PM получает команду от GUI -> отправляет `worker.pause_all` или `worker.resume_all` дочернему процессу через `send_message()`.

**Файлы:**
- `multiprocess_framework/modules/process_manager_module/process/process_manager_process.py` -- добавить команды и обработчики

**Шаги:**
1. В `_register_builtin_commands()` добавить в словарь `commands`:
   ```python
   "process.pause": (self._cmd_process_pause, "Поставить процесс на паузу"),
   "process.resume": (self._cmd_process_resume, "Возобновить процесс"),
   ```
2. Добавить обработчики `_cmd_process_pause` и `_cmd_process_resume` по аналогии с `_cmd_process_stop`:
   ```python
   def _cmd_process_pause(self, data=None, **kwargs) -> dict:
       if isinstance(data, dict):
           kwargs.update(data)
       process_name = kwargs.get("process_name", "")
       if not process_name:
           return {"error": "process_name required"}
       return self.pause_process(process_name)

   def _cmd_process_resume(self, data=None, **kwargs) -> dict:
       if isinstance(data, dict):
           kwargs.update(data)
       process_name = kwargs.get("process_name", "")
       if not process_name:
           return {"error": "process_name required"}
       return self.resume_process(process_name)
   ```
3. Добавить методы `pause_process(name)` и `resume_process(name)`:
   ```python
   def pause_process(self, process_name: str) -> dict:
       process = self._process_registry.get_process_by_name(process_name)
       if not process or not process.is_alive():
           return {"success": False, "error": "process not alive"}
       msg = {"command": "worker.pause_all", "sender": self.name, "type": "system"}
       self.send_message(process_name, msg)
       return {"success": True, "process_name": process_name}

   def resume_process(self, process_name: str) -> dict:
       process = self._process_registry.get_process_by_name(process_name)
       if not process or not process.is_alive():
           return {"success": False, "error": "process not alive"}
       msg = {"command": "worker.resume_all", "sender": self.name, "type": "system"}
       self.send_message(process_name, msg)
       return {"success": True, "process_name": process_name}
   ```

**Критерии приемки:**
- [ ] Команда `process.pause` с `process_name` отправляет IPC-сообщение `worker.pause_all` дочернему процессу
- [ ] Команда `process.resume` с `process_name` отправляет IPC-сообщение `worker.resume_all` дочернему процессу
- [ ] Ошибки (процесс не найден, не жив) возвращают `{"success": False, "error": "..."}`

**Вне скоупа:** Отслеживание реального перехода в paused (это Task 1.4).

**Зависимости:** Task 1.2

---

### Task 1.4 -- Статус "paused" в ProcessMonitor

**Уровень:** Middle (Sonnet, normal)
**Исполнитель:** developer
**Цель:** ProcessMonitor должен отслеживать статус "paused" через heartbeat-данные и broadcast его.

**Контекст:** ProcessMonitor._on_heartbeat_received() получает heartbeat от дочерних процессов (строка 131). Сейчас heartbeat содержит только sender + timestamp. После Task 2.1 heartbeat будет включать `workers_status`. По этим данным можно определить, что все application-воркеры на паузе = процесс в "paused". Но это зависит от Task 2.1. Альтернативный вариант: дочерний процесс сам сообщает свой статус "paused"/"running" в heartbeat.

**Файлы:**
- `multiprocess_framework/modules/process_manager_module/monitor/process_monitor.py` -- обработка paused
- `multiprocess_prototype/frontend/widgets/tabs_setting/processes_tab/constants.py` -- добавить цвет для "paused"

**Шаги:**
1. В heartbeat-сообщение от ProcessModule (Task 2.1) добавить поле `"status"` -- текущий статус процесса. Дочерний ProcessModule после получения `worker.pause_all` должен обновить свой статус на "paused" (через `update_process_state(status="paused")`), а после `worker.resume_all` — обратно на "running".
2. В `ProcessMonitor._on_heartbeat_received()` проверять поле `status` из heartbeat:
   ```python
   status = msg.get("status")
   if status == "paused":
       # обновить previous_states для этого процесса
       prev = self.previous_states.get(sender)
       if (prev or {}).get("status") != "paused":
           snap = {"status": "paused", "metadata": {}, "custom": {}}
           self._handle_state_change(sender, prev, snap)
           self.previous_states[sender] = snap.copy()
   ```
3. В `_check_heartbeats()`: процесс со статусом "paused" считается живым и не нуждается в рестарте. Добавить "paused" в список не-terminal статусов.
4. В `constants.py` добавить цвет:
   ```python
   "paused": "#f1c40f",  # жёлтый
   ```

**Критерии приемки:**
- [ ] Когда все воркеры на паузе, статус процесса отображается как "paused"
- [ ] "paused" процесс НЕ считается crashed/unresponsive
- [ ] Broadcast process_status_changed содержит new_status="paused"
- [ ] Цвет "paused" отображается в GUI

**Зависимости:** Task 1.2, Task 1.3 (логика изменения статуса в ProcessModule)

---

### Task 2.1 -- Workers status в heartbeat от ProcessModule

**Уровень:** Middle (Sonnet, normal)
**Исполнитель:** developer
**Цель:** Расширить heartbeat-сообщение данными о воркерах процесса.

**Контекст:** `ProcessModule._heartbeat_loop()` (строка 539 в `process_module.py`) отправляет heartbeat каждые 5 секунд. Сейчас сообщение содержит: type, subtype, command, sender, timestamp. Нужно добавить `workers_status` из `worker_manager.get_all_workers_status()`.

**Файлы:**
- `multiprocess_framework/modules/process_module/core/process_module.py` -- расширить heartbeat_msg

**Шаги:**
1. В `_heartbeat_loop()` после формирования `heartbeat_msg` (строки 547-553) добавить:
   ```python
   # Данные о воркерах для ProcessMonitor
   if self.worker_manager:
       try:
           workers = self.worker_manager.get_all_workers_status()
           # Исключить metrics для экономии трафика
           for w in workers.values():
               w.pop("metrics", None)
           heartbeat_msg["workers_status"] = workers
       except Exception:
           pass
   ```
2. Убедиться что данные pickle-safe (Dict at Boundary): `get_all_workers_status()` уже возвращает dict[str, dict] с примитивными типами (строки 145-158 в `worker_manager.py`) — проверить что `WorkerStatus.value` и `WorkerType.value` дают строки, а не enum.

**Критерии приемки:**
- [ ] Heartbeat-сообщение содержит ключ `workers_status` с dict воркеров
- [ ] Данные сериализуемы через pickle (Dict at Boundary)
- [ ] metrics исключены для экономии трафика IPC

**Вне скоупа:** Обработка workers_status на стороне ProcessMonitor (это Task 2.2).

**Зависимости:** нет

---

### Task 2.2 -- Workers data в ProcessMonitor broadcast

**Уровень:** Middle (Sonnet, normal)
**Исполнитель:** developer
**Цель:** ProcessMonitor сохраняет workers_status из heartbeat и включает в broadcast.

**Контекст:** ProcessMonitor._on_heartbeat_received() (строка 131) сейчас сохраняет только timestamp. `_broadcast_full_status()` (строка 413) шлёт process_full_status. Нужно сохранять workers_status и включать в оба broadcast (status_changed и full_status).

**Файлы:**
- `multiprocess_framework/modules/process_manager_module/monitor/process_monitor.py`

**Шаги:**
1. Добавить новое хранилище `self._workers_status: dict[str, dict] = {}` в `__init__`.
2. В `_on_heartbeat_received()` сохранять workers:
   ```python
   workers = msg.get("workers_status")
   if workers and isinstance(workers, dict):
       self._workers_status[sender] = workers
   ```
3. В `_broadcast_full_status()` добавить workers в данные каждого процесса:
   ```python
   for name, data in all_status.items():
       workers = self._workers_status.get(name)
       if workers:
           data["workers"] = workers
   ```
4. В `_broadcast_status_change()` добавить workers в state:
   ```python
   workers = self._workers_status.get(process_name)
   if workers:
       current_state["workers"] = workers
   ```

**Критерии приемки:**
- [ ] broadcast `process_full_status` содержит `workers` dict для каждого процесса
- [ ] broadcast `process_status_changed` содержит `workers` в `state`
- [ ] Workers очищаются при удалении процесса из previous_states

**Зависимости:** Task 2.1

---

### Task 2.3 -- Workers data в ProcessMonitorModel (GUI)

**Уровень:** Middle (Sonnet, normal)
**Исполнитель:** developer
**Цель:** ProcessMonitorModel сохраняет и отдаёт workers data для отображения в дереве.

**Контекст:** ProcessMonitorModel.update_process() (строка 41) делает merge: `{**existing, **data}`. Workers придут как ключ `"workers"` в data dict. Никаких изменений в модели не нужно -- merge уже работает корректно. Но ProcessDataBridge.on_status_update() (строка 64) берёт только `new_status` и `state` -- нужно проверить что workers проходят.

**Файлы:**
- `multiprocess_prototype/frontend/widgets/tabs_setting/processes_tab/process_data_bridge.py` -- убедиться что workers пробрасываются

**Шаги:**
1. В `ProcessDataBridge.on_status_update()` (строка 82): проверить, что `state` из broadcast содержит `workers` и они попадают в `update_data`. Текущий код `update_data = {"status": new_status, **state}` уже включит workers из state.
2. В `ProcessDataBridge.on_full_snapshot()` (строка 98): проверить, что при полном снимке workers из `snapshot[name]` попадают в модель. Текущий merge `{**existing, **data}` уже включит.
3. Если нужна дополнительная обработка — добавить. Скорее всего ничего менять не нужно, только проверить и добавить комментарий.

**Критерии приемки:**
- [ ] `ProcessMonitorModel.processes["camera_0"]["workers"]` содержит dict воркеров после broadcast
- [ ] Данные обновляются при каждом heartbeat broadcast

**Вне скоупа:** GUI-отображение (это Task 3.3).

**Зависимости:** Task 2.2

---

### Task 3.1 -- Кнопка Pause/Resume в ProcessControlPanel

**Уровень:** Middle (Sonnet, normal)
**Исполнитель:** developer
**Цель:** Добавить кнопку паузы/возобновления в панель управления процессами.

**Контекст:** ProcessControlPanel (process_control_panel.py) имеет три кнопки: Start, Stop, Restart. Нужно добавить четвёртую кнопку Pause/Resume. Текст и поведение кнопки зависят от текущего статуса процесса.

**Файлы:**
- `multiprocess_prototype/frontend/widgets/tabs_setting/processes_tab/process_control_panel.py`

**Шаги:**
1. В `__init__()` после создания `_btn_restart` (строка 56) добавить:
   ```python
   self._btn_pause = QPushButton("⏸ Пауза")
   self._btn_pause.setEnabled(False)
   layout.addWidget(self._btn_pause)  # добавить ПЕРЕД addStretch()
   ```
   Переместить `layout.addStretch()` после добавления `_btn_pause`.
2. Подключить сигнал: `self._btn_pause.clicked.connect(self._on_pause_toggle)`
3. Добавить `_btn_pause` в `_disable_all()`.
4. В `_update_buttons()`:
   ```python
   can_pause = has_process and status == "running"
   can_resume = has_process and status == "paused"
   self._btn_pause.setEnabled(can_pause or can_resume)
   if status == "paused":
       self._btn_pause.setText("▶ Возобновить")
   else:
       self._btn_pause.setText("⏸ Пауза")
   ```
5. Добавить `_on_pause_toggle()`:
   ```python
   def _on_pause_toggle(self) -> None:
       if not self._current_process:
           return
       if self._current_status == "paused":
           action = "process.resume"
       else:
           action = "process.pause"
       self._send_pm_command(action, process_name=self._current_process)
       self.action_requested.emit(action, self._current_process)
       self._disable_all()
       QTimer.singleShot(2000, self._update_buttons)
   ```
   Примечание: confirmation dialog для pause НЕ нужен — операция обратима.

**Критерии приемки:**
- [ ] Кнопка "Пауза" видна в панели управления
- [ ] Кнопка активна только когда статус "running" (пауза) или "paused" (возобновление)
- [ ] Текст переключается: "Пауза" / "Возобновить"
- [ ] При нажатии отправляется process.pause или process.resume через _send_pm_command
- [ ] Debounce 2 секунды после нажатия

**Вне скоупа:** Подтверждение (confirmation dialog) для паузы.

**Зависимости:** Task 1.3, Task 1.4

---

### Task 3.2 -- Регистрация process.pause / process.resume в routing/catalog

**Уровень:** Junior (Haiku, normal)
**Исполнитель:** developer
**Цель:** Зарегистрировать новые команды в GUI routing и catalog.

**Контекст:** GUI отправляет команды через `process.command` wrapper (AD-8), но маршрутизация всё равно проходит через `EXPLICIT_COMMAND_TARGETS` и `GUI_COMMAND_CATALOG`. Для корректности нужно зарегистрировать process.pause и process.resume.

**Файлы:**
- `multiprocess_prototype/registers/commands/routing.py` -- добавить в EXPLICIT_COMMAND_TARGETS
- `multiprocess_prototype/registers/commands/catalog.py` -- добавить в GUI_COMMAND_CATALOG

**Шаги:**
1. В `routing.py` в `EXPLICIT_COMMAND_TARGETS` (строка 29) добавить:
   ```python
   "process.pause": ["ProcessManager"],
   "process.resume": ["ProcessManager"],
   ```
2. В `catalog.py` в `GUI_COMMAND_CATALOG` (строка 98) добавить:
   ```python
   "process.pause": _args_process_name,
   "process.resume": _args_process_name,
   ```

**Критерии приемки:**
- [ ] `process.pause` и `process.resume` присутствуют в `EXPLICIT_COMMAND_TARGETS`
- [ ] `process.pause` и `process.resume` присутствуют в `GUI_COMMAND_CATALOG`
- [ ] `resolve_command_targets("process.pause")` возвращает `["ProcessManager"]`

**Зависимости:** нет (можно делать параллельно с Task 1.x)

---

### Task 3.3 -- Раскрываемое дерево с workers

**Уровень:** Senior (Opus, normal)
**Исполнитель:** teamlead
**Цель:** Переделать ProcessTreeView на двухуровневое дерево: процессы -- корневые узлы, workers -- дочерние (раскрываемые) узлы.

**Контекст:** Сейчас ProcessTreeView (process_tree_view.py) -- плоский список процессов. Нужно сделать двухуровневое дерево. BaseEditorTreeView поддерживает дочерние узлы через `QStandardItem.appendRow()`. Колонки для workers отличаются от процессов: Имя | Статус | Тип | Restarts | Last Error.

ВАЖНО: при работе с QStandardItem и деревьями есть паттерн из памяти проекта `feedback_widget_qt_patterns.md` -- setFlags рекурсия, blockSignals, EditTriggers. Нужно соблюдать.

**Файлы:**
- `multiprocess_prototype/frontend/widgets/tabs_setting/processes_tab/process_tree_view.py` -- основные изменения
- `multiprocess_prototype/frontend/widgets/tabs_setting/processes_tab/constants.py` -- добавить константы для workers

**Шаги:**
1. В `constants.py` добавить:
   ```python
   # Колонки дерева (общие для process + worker)
   # Процесс: Имя | Статус | PID | Приоритет | Класс
   # Worker:  Имя | Статус | Тип | Restarts | Last Error
   COLUMN_HEADERS: list[str] = ["Имя", "Статус", "PID / Тип", "Приоритет / Restarts", "Класс / Last Error"]
   ```
   Либо оставить текущие 5 колонок и переиспользовать их для workers с другой семантикой.
   Рекомендация: переименовать заголовки нейтрально, чтобы подходили обоим уровням:
   ```python
   COLUMN_HEADERS: list[str] = ["Имя", "Статус", "Доп. инфо", "Параметр", "Детали"]
   ```
   Или сохранить текущие заголовки (они в основном для процессов) и просто заполнять worker-строки соответствующими данными — пользователь поймёт из контекста.
   
   Решение: сохранить текущие заголовки, для worker-строк использовать те же колонки с другой семантикой.

2. В `constants.py` добавить роль для типа узла worker:
   ```python
   ROLE_WORKER = Qt.ItemDataRole.UserRole + 3  # имя воркера
   ```

3. В `process_tree_view.py` в `_build_process_row()`: сделать корневой элемент `col_name` обязательно expandable (даже если workers пока нет).

4. Добавить метод `_build_worker_rows(workers: dict) -> list[list[QStandardItem]]`:
   ```python
   def _build_worker_rows(self, workers: dict) -> list[list[QStandardItem]]:
       rows = []
       for wname, wdata in sorted(workers.items()):
           col_name = QStandardItem(f"  {wname}")
           col_name.setData("worker", ROLE_TYPE)
           col_name.setData(wname, ROLE_WORKER)
           col_name.setFlags(col_name.flags() & ~Qt.ItemFlag.ItemIsEditable)

           status = wdata.get("status", "unknown")
           col_status = QStandardItem(status)
           color_hex = WORKER_STATUS_COLORS.get(status, "#95a5a6")
           col_status.setForeground(QBrush(QColor(color_hex)))
           col_status.setFlags(col_status.flags() & ~Qt.ItemFlag.ItemIsEditable)

           worker_type = wdata.get("worker_type", "—")
           col_type = QStandardItem(worker_type)
           col_type.setFlags(col_type.flags() & ~Qt.ItemFlag.ItemIsEditable)

           restarts = wdata.get("restart_count", 0)
           col_restarts = QStandardItem(str(restarts))
           col_restarts.setFlags(col_restarts.flags() & ~Qt.ItemFlag.ItemIsEditable)

           last_error = wdata.get("last_error") or "—"
           col_error = QStandardItem(str(last_error)[:50])
           col_error.setToolTip(str(last_error))
           col_error.setFlags(col_error.flags() & ~Qt.ItemFlag.ItemIsEditable)

           rows.append([col_name, col_status, col_type, col_restarts, col_error])
       return rows
   ```

5. В `_populate()`: после `root.appendRow(row)` добавить workers как дочерние узлы:
   ```python
   workers = data.get("workers", {})
   if workers:
       parent_item = row[0]  # col_name — корневой элемент строки
       for worker_row in self._build_worker_rows(workers):
           parent_item.appendRow(worker_row)
   ```

6. В `constants.py` добавить `WORKER_STATUS_COLORS`:
   ```python
   WORKER_STATUS_COLORS: dict[str, str] = {
       "running":  "#27ae60",
       "stopped":  "#95a5a6",
       "paused":   "#f1c40f",
       "error":    "#e74c3c",
       "created":  "#9b59b6",
   }
   ```

7. Обработка выбора worker-узла: в widget.py `_on_process_selected` проверить ROLE_TYPE. Если "worker" — показать детали воркера в detail panel. Если "process" — как сейчас. Для control panel: при выборе worker-узла — получить имя родительского процесса через ROLE_PROC.

8. Save/restore selection: BaseEditorTreeView использует `Qt.UserRole` для ключа — нужно убедиться что worker-узлы имеют уникальный ключ (например `"{process_name}/{worker_name}"`).

**Критерии приемки:**
- [ ] Процессы отображаются как корневые узлы с expand-стрелкой
- [ ] При раскрытии показываются workers с колонками: Имя | Статус | Тип | Restarts | Last Error
- [ ] Цветовая индикация статуса workers (running/stopped/paused/error)
- [ ] При выборе worker-строки detail panel показывает информацию о воркере
- [ ] Save/restore selection работает при refresh (не сбрасывается выделение)
- [ ] Прокрутка и раскрытие сохраняются при обновлении данных

**Edge cases:**
- Процесс без воркеров: показывать без expand-стрелки (или с пустой)
- Worker с длинным last_error: обрезать до 50 символов + tooltip
- Очень много воркеров (>20): работоспособность дерева

**Вне скоупа:** Управление отдельными воркерами из GUI (start/stop/restart worker). Фильтрация воркеров. Сортировка.

**Зависимости:** Task 2.3 (данные о workers должны быть в модели)

---

## Риски и ограничения

1. **Heartbeat-воркер и пауза:** Если `pause_all_workers()` ставит на паузу heartbeat_sender, процесс будет считаться unresponsive. Решение: Task 1.2 описывает фильтрацию system-воркеров.

2. **Pickle-safety:** Workers status в heartbeat должен быть полностью dict-based (Dict at Boundary). `get_all_workers_status()` уже возвращает dict с `.value` для enum — проверить что `is_alive` (bool) и `thread` (Thread) не попадут. `is_alive` — ок (bool), `metrics` — ок (dict of primitives). Но `thread` НЕ попадает в `get_worker_status()` — только извлечённые примитивы.

3. **Размер heartbeat:** Добавление workers_status увеличивает размер heartbeat. Для процесса с 10 воркерами — примерно +2KB. При 10 процессах x каждые 5 секунд = +4KB/с — приемлемо. Исключаем `metrics` для экономии.

4. **GUI refresh при частых обновлениях:** Heartbeat каждые 5 секунд + workers data -> частый refresh дерева. BaseEditorTreeView.refresh() делает full rebuild — может быть медленно с expand-состояниями. Нужно сохранять expand state при refresh.

5. **ProcessModule.update_process_state:** Для Task 1.4 нужно вызывать `update_process_state(status="paused")` — проверить что этот метод не конфликтует с ProcessMonitor liveness checks.
