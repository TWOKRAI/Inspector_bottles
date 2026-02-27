# Документация ProcessModule

## Структура документации

- **ARCHITECTURE.md** - Архитектура модуля
- **COMMUNICATION.md** - Коммуникация через RouterManager и Dispatch
- **STATUS.md** - Текущий статус разработки
- **COMPLETION_PLAN.md** - План завершения модуля

## Быстрая навигация

- Хочу понять архитектуру → `ARCHITECTURE.md`
- Хочу понять коммуникацию → `COMMUNICATION.md`
- Хочу узнать статус → `STATUS.md`

## Основные концепции

### Коммуникация

**Вся коммуникация идет через RouterManager**, который использует **Dispatch модуль** для маршрутизации:

```
ProcessCommunication → RouterManager → Dispatcher → MessageChannel
```

См. `COMMUNICATION.md` для деталей.

### Архитектура

ProcessModule наследуется от BaseManager и использует ObservableMixin для единообразия со всеми менеджерами системы.

См. `ARCHITECTURE.md` для деталей.

