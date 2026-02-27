# Документация RouterModule

## Структура документации

- **USAGE_GUIDE.md** - Подробное руководство по использованию с примерами
- **ARCHITECTURE.md** - Архитектура модуля
- **DISPATCH_INTEGRATION.md** - Интеграция с Dispatch модулем

## Быстрая навигация

- Хочу начать использовать → `USAGE_GUIDE.md`
- Хочу понять архитектуру → `ARCHITECTURE.md`
- Хочу понять интеграцию с Dispatch → `DISPATCH_INTEGRATION.md`

## Основные концепции

### BaseManager + ObservableMixin

RouterManager наследуется от BaseManager и использует ObservableMixin для:
- Единообразия со всеми менеджерами системы
- Автоматического логирования
- Стандартного жизненного цикла

### Интеграция с Dispatch

RouterManager использует Dispatch модуль для интеллектуальной маршрутизации сообщений.

См. `DISPATCH_INTEGRATION.md` для деталей.

