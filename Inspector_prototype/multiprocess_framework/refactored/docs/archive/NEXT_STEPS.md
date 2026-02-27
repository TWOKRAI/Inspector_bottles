# Следующие шаги рефакторинга

## Текущий статус

✅ **Message Module** - завершен (транспорт)
- Структура модуля готова
- Система схем (Pydantic v2) реализована
- Тесты и документация готовы

## План дальнейших действий (от глобального к меньшему)

### 1. Base Manager Module (основа для всех менеджеров) ⭐ СЛЕДУЮЩЕЕ

**Зачем:** Все менеджеры (Worker, Logger, Router, Command, Config, Dispatch) должны наследоваться от базового менеджера.

**Что нужно сделать:**
- [ ] Создать структуру модуля по стандарту (core/, types/, mixins/, adapters/)
- [ ] `BaseManager` - абстрактный класс с жизненным циклом (initialize/shutdown)
- [ ] `BaseAdapter` - базовый класс для адаптеров
- [ ] `ObservableMixin` - миксин для логирования/мониторинга
- [ ] `ManagerExtensionMixin` - миксин для расширений
- [ ] Интерфейсы для менеджеров
- [ ] Тесты и документация

**Структура:**
```
base_manager/
├── __init__.py
├── interfaces.py
├── core/
│   ├── __init__.py
│   └── base_manager.py        # BaseManager (абстрактный)
├── adapters/
│   ├── __init__.py
│   └── base_adapter.py        # BaseAdapter
├── mixins/
│   ├── __init__.py
│   ├── observable_mixin.py     # ObservableMixin
│   └── extension_mixin.py      # ManagerExtensionMixin
├── types/
│   ├── __init__.py
│   └── manager_types.py        # Типы, константы
├── README.md
└── tests/
    └── test_base_manager.py
```

### 2. Process Module (организм) - базовый процесс

**Зачем:** Базовый процесс, который заполняется менеджерами. Это "организм" в аналогии.

**Что нужно сделать:**
- [ ] Создать структуру модуля
- [ ] `ProcessCore` - жизненный цикл процесса
- [ ] `ManagersComponents` - фабрика менеджеров
- [ ] `ProcessCommunication` - коммуникация через Router
- [ ] `ProcessConfigHandler` - обработка конфигов
- [ ] Интеграция с Base Manager Module
- [ ] Тесты и документация

**Зависимости:** Base Manager Module

### 3. Process Manager (мозг) - создает и управляет процессами

**Зачем:** Создает процессы, управляет их жизненным циклом, мониторит здоровье.

**Что нужно сделать:**
- [ ] Создать структуру модуля
- [ ] `SystemLauncher` - запуск системы
- [ ] `ProcessManagerCore` - ядро менеджера процессов
- [ ] `ProcessManager` - основной класс
- [ ] Builders (декораторы, конфиги)
- [ ] Мониторинг и health checks
- [ ] Тесты и документация

**Зависимости:** Process Module, Base Manager Module

### 4. Router Module (нервная система) ⭐

**Зачем:** Связывает все компоненты через Message Module.

**Зависимости:** Message Module, Base Manager Module

### 5. Shared Resources (архив)

**Зависимости:** Data Schema, Base Manager Module

### 6. Data Schema (ДНК)

**Зависимости:** Base Manager Module (опционально)

### 7. Менеджеры процесса (органы)

- Worker Manager
- Logger Manager
- Config Manager
- Command Manager
- Dispatch

**Зависимости:** Base Manager Module, Router Module

## Приоритеты

1. **Base Manager Module** - основа для всего ⭐
2. **Process Module** - базовый процесс
3. **Process Manager** - управление процессами
4. Router Module - нервная система
5. Остальные модули

## Принципы

- ✅ Похожая структура модулей везде (как в Message Module)
- ✅ От глобального к меньшему
- ✅ Базовые модули перед специализированными
- ✅ Четкие зависимости между модулями

