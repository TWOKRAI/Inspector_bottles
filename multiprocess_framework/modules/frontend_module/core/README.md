# core — базовые классы и утилиты frontend_module

Слой, не зависящий от Qt: маршрутизация команд, регистры-бридж, импорты Qt, интерфейсы. Размещается отдельно чтобы не подтягивать Qt в зависимости.

## Ключевые символы

- `RoutedCommandSender` — сборка COMMAND-сообщений и отправка первому получателю из маршрута.
- `FrontendRegistersBridge` — адаптер между GuiState и RegistersManager.
- `qt_imports` — централизованные импорты Qt (вежливая обработка missing PySide6).

## Stability

contract

→ Корневой README: `../../README.md`
