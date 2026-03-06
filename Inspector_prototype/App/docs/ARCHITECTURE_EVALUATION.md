# Оценка архитектуры App Inspector

**Дата:** 2025  
**Методология:** Анализ кодовой базы, SOLID, практики enterprise-приложений

---

## 1. Сводная оценка (10-балльная шкала)

| Критерий | Балл | Обоснование |
|----------|------|-------------|
| **SRP (Single Responsibility)** | 8/10 | Чёткое разделение слоёв, MainWindow — чистый compositor. Минус: WindowManager совмещает fullscreen + cursor + access_level + registry. |
| **OCP (Open/Closed)** | 8/10 | Новое окно = 1 строка в registry. Минус: нет плагинов для виджетов, жёсткая привязка в MainWindow._create_tabs(). |
| **LSP (Liskov Substitution)** | 7/10 | QWidget-наследники в целом взаимозаменяемы. Минус: HeaderWidget требует window_manager, но MainWindow создаёт без него — нарушение контракта. |
| **ISP (Interface Segregation)** | 8/10 | SortController не знает про WindowManager. Минус: DataManager — «толстый» фасад, часть методов не нужна всем виджетам. |
| **DIP (Dependency Inversion)** | 7/10 | Инжекция через конструкторы. Минус: Coordinator создаёт все менеджеры внутри — нет DI-контейнера, сложно подменять для тестов. |
| **DRY** | 7/10 | Логика вынесена из монолита. Минус: дублирование App.Registers и Core.Domain.Registers, хардкод путей импорта. |
| **KISS** | 6/10 | 4 слоя — много для простого desktop-приложения. Минус: Domain.Services в импортах, но папки нет — путаница. |
| **Testability** | 6/10 | Слои изолированы. Минус: Qt-сигналы, нет абстракций для IPC/очередей, приложение не запустится из-за сломанных импортов. |
| **Performance** | 8/10 | Zero-copy кадры, async IPC, неблокирующие очереди. Минус: нет backpressure для display_queue. |
| **Observability** | 6/10 | FPS в ImagePanel. Минус: print() вместо structured logging, нет tracing. |
| **Работоспособность** | 3/10 | **Критично:** приложение не запустится — сломанные импорты, невызванный register_standard_threads, Header без window_manager. |

### Итоговая оценка: **6.8/10**

**С учётом блокеров (приложение не запускается):** **5.5/10**

---

## 2. Критические проблемы (блокеры)

### 2.1 Импорты Domain.Services — приложение не запустится

**Где:** coordinator.py, main_window.py, sort_container.py, window_manager.py

```python
from App.Core.Domain.Services.data_manager import DataManager  # ModuleNotFoundError!
```

**Факт:** Папки `App/Core/Domain/Services/` не существует. Менеджеры в `App/Core/Managers/`.

**Исправление:** Создать `App/Core/Domain/Services/__init__.py` с re-export из Managers, либо заменить все импорты на `App.Core.Managers`.

---

### 2.2 DataManager не принимает registers_manager

**Где:** coordinator.py:165–169

```python
self._data_manager = DataManager(
    registers_manager=self._registers,  # ← передаём
    recipe_manager=recipe_manager,
    converter=converter,
)
```

**Факт:** `Core/Managers/data_manager.py` принимает только `recipe_manager` и `converter`. Параметр `registers_manager` вызовет TypeError (unexpected keyword argument).

**Исправление:** Добавить `registers_manager` в сигнатуру DataManager или убрать из вызова.

---

### 2.3 ThreadManager — потоки не регистрируются

**Где:** coordinator.py:214–217

```python
self._thread_manager = ThreadManager(...)
# register_standard_threads() НИКОГДА НЕ ВЫЗЫВАЕТСЯ!
```

**Факт:** `create_all()` вызывается с пустым `_entries` — никакие потоки не создаются. `image_thread` будет `None`, кадры не придут.

**Исправление:** После создания ThreadManager вызвать:
```python
self._thread_manager.register_standard_threads()
```

---

### 2.4 SortContainer — неверный путь импорта

**Где:** sort_container.py:13–16

```python
from App.UI.Widgets.Sort.sort_data import SortData  # Sort не существует!
```

**Факт:** Папка называется `Sort_widget`, не `Sort`. ImportError при импорте SortContainer.

**Исправление:** Заменить на `App.UI.Widgets.Sort_widget.sort_data` и т.д.

---

### 2.5 HeaderWidget без window_manager — crash при нажатии кнопок

**Где:** main_window.py:125, header.py:139, 234, 256

```python
self.header = HeaderWidget()  # window_manager=None
# При нажатии "ЭКРАН": self.window_manager.set_fullscreen() → AttributeError
# При нажатии "ЗАКРЫТЬ": self.window_manager.close_program() → AttributeError
```

**Факт:** HeaderWidget ожидает `window_manager` в конструкторе. WindowManager не имеет метода `close_program` (есть только `close_all`).

**Исправление:**
1. MainWindow должен получать `window_manager` от WindowManager и передавать в HeaderWidget.
2. Либо Header эмитит сигналы `fullscreen_toggle_requested`, `close_requested` — Coordinator/WindowManager обрабатывают.
3. Добавить в WindowManager метод `close_program()` → shutdown Coordinator или close_all + stop_event.

---

### 2.6 Header — неверный путь к admin_window

**Где:** header.py:6

```python
from App.Windows.admin_window import PasswordDialog  # App.Windows удалён (git)
```

**Факт:** admin_window находится в `App/UI/Windows/admin_window.py`.

**Исправление:** `from App.UI.Windows.admin_window import PasswordDialog`

---

### 2.7 DataManager.load_recipe отсутствует

**Где:** coordinator.py:347

```python
self._data_manager.load_recipe(recipe_id)  # AttributeError!
```

**Факт:** У DataManager нет метода `load_recipe`. Метод есть в RecipeManager.

**Исправление:** Добавить в DataManager `load_recipe(recipe_id)` → делегирование в recipe_manager + синхронизация RegistersManager.

---

## 3. Серьёзные проблемы (не блокеры, но ухудшают качество)

### 3.1 Дублирование Registers

**Проблема:** `App.Registers` и `App.Core.Domain.Registers` содержат похожие модели. Риск рассинхронизации.

**Рекомендация:** Оставить только `Core.Domain.Registers`, удалить или пометить `App.Registers` как deprecated.

---

### 3.2 Два WindowManager

**Проблема:** `Core/Application/window_manager.py` (новый) и `Core/Managers/window_manager.py` (legacy). Разные контракты, путаница.

**Рекомендация:** Удалить legacy, переименовать если нужно для ясности.

---

### 3.3 Coordinator — God Object

**Проблема:** Coordinator знает о всех слоях, создаёт всё внутри, обрабатывает все callback'и. При росте приложения станет узким местом.

**Рекомендация:** Вынести обработку регистров в отдельный `RegisterRouter` или `IpcBridge`; Coordinator только связывает компоненты.

---

### 3.4 Нет обработки ошибок IPC

**Проблема:** `_on_register_changed` отправляет в Router без проверки результата. При недоступности бэкенда — тишина.

**Рекомендация:** Retry, circuit breaker, логирование ошибок, сигнал `ipc_error` для UI.

---

### 3.5 Хардкод зависимостей виджетов

**Проблема:** MainWindow._create_tabs() жёстко создаёт 7 виджетов с конкретными классами. Добавление вкладки = правка MainWindow.

**Рекомендация:** Registry виджетов по имени, конфиг вкладок из YAML/JSON.

---

## 4. Рекомендации по улучшению

### 4.1 Приоритет 1 (исправить для запуска)

1. Исправить импорты Domain.Services → Managers или создать Services re-export.
2. Добавить вызов `register_standard_threads()` в Coordinator.
3. Исправить импорты в sort_container (Sort → Sort_widget).
4. Передать window_manager в HeaderWidget или перевести Header на сигналы.
5. Исправить импорт admin_window (App.Windows → App.UI.Windows).
6. Согласовать сигнатуру DataManager с вызовом в Coordinator.
7. Добавить DataManager.load_recipe() или изменить Coordinator._on_apply_recipe.

### 4.2 Приоритет 2 (стабильность)

1. Добавить structured logging (structlog/loguru) вместо print().
2. Обработка ошибок IPC с уведомлением пользователя.
3. Unit-тесты для RegistersManager, DataManager (без Qt).
4. Типизация (type hints) для публичных API.

### 4.3 Приоритет 3 (масштабируемость)

1. DI-контейнер (dependency-injector, punq) для упрощения тестов.
2. Конфиг вкладок MainWindow из файла.
3. Разделение WindowManager: FullscreenController, CursorController, AccessLevelController.
4. Абстракция IPC (интерфейс IpcBridge) для моков в тестах.

---

## 5. Что уже хорошо

- ✅ Чёткое разделение на слои (UI / Application / Domain / Core).
- ✅ MainWindow — чистый compositor, без бизнес-логики.
- ✅ RegistersManager с observer API — единый источник истины.
- ✅ Сигналы вместо прямых вызовов между слоями.
- ✅ Graceful shutdown в Coordinator.
- ✅ WindowRegistry — удобная фабрика окон.
- ✅ ThreadManager — централизованное управление потоками.
- ✅ Pydantic-модели для регистров — валидация и типизация.

---

## 6. Итоговая таблица

| Аспект | Оценка | Комментарий |
|--------|--------|-------------|
| **Идея архитектуры** | 9/10 | Слои, сигналы, observer — правильный подход |
| **Реализация** | 5/10 | Сломанные импорты, незавершённая интеграция |
| **Консистентность** | 5/10 | Domain.Services vs Managers, два Registers |
| **Документация** | 8/10 | NEW_ARCHITECTURE, APP_REFERENCE — хорошо |
| **Готовность к продакшену** | 3/10 | Не запускается без исправлений |

**Вывод:** Архитектурная идея сильная, но интеграция не завершена. После исправления блокеров (раздел 2) оценка поднимется до ~7.5/10. Дальнейшие улучшения (раздел 4) доведут до 8.5/10.
