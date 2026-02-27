# Исправления Иерархии Зависимостей

## Исправленные Ошибки в Плане

### ❌ Было Неправильно:

1. **CommandModule не был связан с DispatchModule**
   - **Реальность:** CommandModule **зависит от** DispatchModule (использует `Dispatcher` и `DispatchStrategy`)

2. **ConsoleModule был связан с ProcessModule**
   - **Реальность:** ConsoleModule **НЕ зависит** от ProcessModule напрямую
   - ConsoleModule может использовать ProcessManager опционально для создания отдельного процесса консоли
   - Но это не обязательная зависимость

3. **ProcessManagerModule не был показан в диаграмме**
   - **Реальность:** ProcessManagerModule должен быть показан как зависящий от ProcessModule, ConfigModule, SharedResourcesModule

4. **Неправильные связи ProcessModule**
   - **Реальность:** ProcessModule использует SharedResourcesModule, RouterModule, WorkerModule, но это не жесткие зависимости
   - Это опциональные зависимости через managers

## ✅ Правильная Иерархия

### Жесткие Зависимости (импорты):

```
BaseManager
├── ConfigModule
├── LoggerModule
├── DispatchModule
│   └── CommandModule (зависит от DispatchModule)
├── ConsoleModule
├── ProcessModule
├── WorkerModule
├── RouterModule (зависит от MessageModule)
├── SharedResourcesModule
└── ProcessManagerModule
    ├── ProcessModule
    ├── ConfigModule
    └── SharedResourcesModule
```

### Опциональные Зависимости (через managers):

- **ConsoleModule** может использовать:
  - CommandManager (опционально)
  - RouterManager (опционально)
  - ProcessManager (опционально)

- **ProcessModule** может использовать:
  - SharedResourcesModule (ProcessStateRegistry, ProcessData)
  - RouterModule (для межпроцессной коммуникации)
  - WorkerModule (WorkerManager для управления потоками)

## Обновленные Описания Модулей

### CommandModule
- **Зависимости:** BaseManager, **DispatchModule** (использует Dispatcher)
- **Исправлено:** Добавлена зависимость от DispatchModule

### ConsoleModule
- **Зависимости:** BaseManager
- **Опциональные зависимости:** CommandManager, RouterManager, ProcessManager (через managers)
- **Исправлено:** Убрана зависимость от ProcessModule

### ProcessManagerModule
- **Зависимости:** BaseManager
- **Использует:** ProcessModule (создает процессы на основе ProcessModule), ConfigModule, SharedResourcesModule
- **Исправлено:** Уточнено, что ProcessManagerModule не наследуется от ProcessModule, а создает процессы на его основе

### ProcessModule
- **Зависимости:** BaseManager
- **Использует:** SharedResourcesModule (ProcessStateRegistry, ProcessData), RouterModule, WorkerModule
- **Исправлено:** Уточнено, что это опциональные зависимости

## Последствия для Тестирования

С учетом правильных зависимостей, порядок тестирования:

1. ✅ BaseManager (100%)
2. ✅ MessageModule (100%)
3. ✅ DataSchemaModule (100%)
4. ✅ DispatchModule (100%) - **ДО** CommandModule
5. ✅ ConfigModule (100%)
6. ✅ CommandModule (100%) - **ПОСЛЕ** DispatchModule
7. ✅ ConsoleModule (100%)
8. ⏳ LoggerModule (0%) - создать тесты
9. ⏳ SharedResourcesModule (94%) - исправить 2 теста
10. ⏳ RouterModule (50%) - исправить импорты
11. ⏳ ProcessModule (77%) - исправить ObservableMixin
12. ⏳ WorkerModule (0%) - исправить WorkerRegistry.is_enabled
13. ⏳ ProcessManagerModule (0%) - создать тесты (после ProcessModule, ConfigModule, SharedResourcesModule)

## Файлы Обновлены

1. ✅ `docs/DEPENDENCY_HIERARCHY.md` - создан с правильной иерархией
2. ✅ `docs/MODULE_TESTING_PROGRESS.md` - обновлен с правильными зависимостями
3. ✅ План тестирования - диаграмма обновлена

