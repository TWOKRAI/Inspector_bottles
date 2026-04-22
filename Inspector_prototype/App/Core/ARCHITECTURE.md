# Core — Архитектура

## Ответственность
Ядро приложения. Содержит бизнес-логику, базовые классы виджетов и фоновые потоки.
Не содержит предметно-ориентированного UI (это задача `Widget/`).

---

## Файлы в корне Core/

| Файл | Класс | Ответственность |
|------|-------|-----------------|
| `app_config.py` | `AppConfig` (Pydantic), `AppConfigManager` (QObject) | Хранение и загрузка конфигурации приложения (`app_config.json`): размеры экрана, fullscreen-ограничения |
| `base_configurable_widget.py` | `ConfigurableWidget(QWidget)` | Базовый класс для всех UI-виджетов с авто-привязкой к полю `RegistersManager`. Реализует паттерн «Наблюдатель»: виджет автоматически обновляется при изменении регистра |

---

## Core/Managers/

Все классы-менеджеры — бизнес-логика без UI.

| Файл | Класс | Ответственность |
|------|-------|-----------------|
| `window_manager.py` | `WindowManager` | Жизненный цикл окон Qt, IPC через `RouterManager`, управление уровнями доступа, fullscreen, курсор |
| `data_manager.py` | `DataManager(QObject)` | Фасад над `CameraManager`, `RegionManager`, `RecipeManager`. Единый API для работы с данными камер и регионов |
| `camera_manager.py` | `CameraManager(QObject)` | CRUD для `CameraData`-моделей. Сигналы: `camera_changed`, `camera_added`, `camera_removed` |
| `region_manager.py` | `RegionManager(QObject)` | CRUD для регионов (`RegionData`) и шагов цепочек (`ChainStepData`) внутри камер |
| `recipe_manager.py` | `RecipeManager` | Загрузка/сохранение рецептов (YAML). Интеграция с `RegistersManager` для структурированного сохранения |
| `params_manager.py` | `ParamsManager` | Сбор параметров из виджетов (`get_params`), применение рецептов к виджетам (`apply_params`), YAML-хранилище через `SortData` |
| `logging_manager.py` | `LoggingManager(QObject)` | Централизованное логирование с ротацией файлов, Qt-сигналы, генерация debug-отчётов |
| `error_manager.py` | `ErrorManager(QObject)` | Обработка ошибок: регистрация, уведомление пользователя, статистика, декоратор `handle_errors` |
| `converter_manager.py` | `ConverterManager` | Утилиты конвертации: Pydantic ↔ dict ↔ JSON ↔ YAML ↔ flat-dict. Все методы статические |
| `translation_manager.py` | `TranslationManager(QObject)` | i18n: перевод ключей из metadata Pydantic-полей, загрузка JSON/YAML-файлов переводов |

---

## Core/Threads/

Фоновые Qt-потоки. Не взаимодействуют с UI напрямую — только через сигналы.

| Файл | Класс | Ответственность |
|------|-------|-----------------|
| `thread_image_update.py` | `UpdateImage(QThread)` | Читает кадры из общей памяти, выбирает режим отображения, эмитирует `update_frame` → `MainWindow.update_data` |
| `thread_loading.py` | `Loading(QThread)` | Мониторит очередь готовности процессов, обновляет прогресс-бар загрузки |
| `thread_bot_message.py` | `BotThread(QThread)` | Слушает очередь `queue_manager.bot_message`, эмитирует сообщения → `WindowManager.show_message` |

---

## Правила

- Менеджеры **не знают** о конкретных виджетах; взаимодействие только через сигналы Qt или явные вызовы интерфейсов.
- `ParamsManager` — менеджер, а не компонент: он управляет состоянием рецептов и виджетами через интерфейс `get_params`/`apply_params`.
- `ConverterManager` — утилитарный класс без состояния (все методы `@staticmethod`).
- `WindowManager` — единственный класс, который знает обо всех окнах; остальные менеджеры окон не касаются.
