# application — точка входа frontend-приложения

Содержит менеджеры верхнего уровня: инициализация Qt-приложения, управление окнами, потоками, горячая перезагрузка конфигурации.

## Ключевые символы

- `FrontendManager` — единая точка входа frontend. Координирует регистры, конфигурацию, окна и потоки. Интегрируется с config_module для hot-reload.
- `WindowManager` — управление окнами (создание, показ, закрытие, сохранение состояния).
- `ThreadManager` — управление рабочими потоками GUI (отправка задач, очистка).
- `RoutedCommandSender` — сборка и отправка COMMAND-сообщений по IPC-маршруту (ядро GUI→backend).
- `run_process_attached_frontend()` — запуск frontend в отдельном процессе с жизненным циклом.
- `FrontendLaunchHooks` — callback-ы для инициализации и завершения frontend.

## Stability

contract

→ Корневой README: `../../README.md`
