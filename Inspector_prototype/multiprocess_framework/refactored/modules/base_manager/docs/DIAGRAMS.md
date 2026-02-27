# Диаграммы взаимодействия компонентов ObservableMixin

## Архитектурная диаграмма

```mermaid
graph TB
    subgraph "ObservableMixin"
        OM[ObservableMixin<br/>Главный класс]
        
        subgraph "Core Components"
            MR[ManagerRegistry<br/>Реестр менеджеров]
            MC[MethodCache<br/>Кэш методов]
        end
        
        subgraph "Method Creators"
            LM[LoggingMethods<br/>Методы логирования]
            SM[StatsMethods<br/>Методы статистики]
            EM[ErrorMethods<br/>Методы ошибок]
        end
        
        subgraph "Proxy System"
            PC[ProxyCreator<br/>Создатель прокси]
            BP[BuiltinPlugins<br/>Встроенные плагины]
        end
        
        subgraph "Plugin System"
            PR[PluginRegistry<br/>Реестр плагинов]
            CP[CustomPlugins<br/>Кастомные плагины]
        end
        
        subgraph "Decorators"
            OD[ObservableDecorators<br/>Декораторы]
        end
    end
    
    OM --> MR
    OM --> MC
    OM --> LM
    OM --> SM
    OM --> EM
    OM --> PC
    OM --> PR
    OM --> OD
    
    PC --> BP
    PC --> PR
    PR --> CP
    
    MR --> MC
    LM --> MC
    SM --> MC
    EM --> MC
    PC --> MC
```

## Поток вызова метода

```mermaid
sequenceDiagram
    participant User
    participant ObservableMixin
    participant ManagerRegistry
    participant MethodCache
    participant Manager
    
    User->>ObservableMixin: manager.log_info("message")
    ObservableMixin->>ManagerRegistry: is_enabled('logger')
    ManagerRegistry-->>ObservableMixin: True
    ObservableMixin->>MethodCache: get('logger', 'info')
    MethodCache-->>ObservableMixin: method (из кэша)
    ObservableMixin->>Manager: method("message")
    Manager-->>ObservableMixin: result
    ObservableMixin-->>User: result
```

## Поток создания прокси-методов

```mermaid
sequenceDiagram
    participant User
    participant ObservableMixin
    participant ProxyCreator
    participant BuiltinPlugins
    participant PluginRegistry
    participant CustomPlugins
    
    User->>ObservableMixin: __init__(..., auto_proxy=True)
    ObservableMixin->>ProxyCreator: create_proxy_methods()
    ProxyCreator->>BuiltinPlugins: LoggerPlugin.create_proxy_methods()
    BuiltinPlugins-->>ProxyCreator: созданы log_info(), log_error() и т.д.
    ProxyCreator->>PluginRegistry: get_plugins_for_manager()
    PluginRegistry-->>ProxyCreator: список плагинов
    ProxyCreator->>CustomPlugins: plugin.create_proxy_methods()
    CustomPlugins-->>ProxyCreator: созданы кастомные методы
    ProxyCreator-->>ObservableMixin: прокси-методы созданы
```

## Поток регистрации плагина

```mermaid
sequenceDiagram
    participant User
    participant ObservableMixin
    participant PluginRegistry
    participant Plugin
    
    User->>ObservableMixin: register_plugin(plugin)
    ObservableMixin->>PluginRegistry: register(plugin)
    PluginRegistry->>PluginRegistry: индексировать по менеджерам
    PluginRegistry-->>ObservableMixin: плагин зарегистрирован
    ObservableMixin->>Plugin: create_private_methods()
    Plugin-->>ObservableMixin: приватные методы созданы
    ObservableMixin->>Plugin: create_proxy_methods() (если auto_proxy)
    Plugin-->>ObservableMixin: прокси-методы созданы
    ObservableMixin->>Plugin: create_decorators()
    Plugin-->>ObservableMixin: декораторы созданы
```

## Взаимодействие с менеджерами системы

```mermaid
graph LR
    subgraph "Process Manager"
        PM[ProcessManager]
        PM --> OM1[ObservableMixin]
        OM1 --> LM1[LoggerManager]
        OM1 --> SM1[StatsManager]
        OM1 --> RM1[RouterManager]
    end
    
    subgraph "Worker Manager"
        WM[WorkerManager]
        WM --> OM2[ObservableMixin]
        OM2 --> LM2[LoggerManager]
        OM2 --> SM2[StatsManager]
    end
    
    subgraph "Router Manager"
        RM[RouterManager]
        RM --> OM3[ObservableMixin]
        OM3 --> LM3[LoggerManager]
        OM3 --> SM3[StatsManager]
        OM3 --> MM[MessageModule]
    end
    
    PM -.->|сообщения| RM
    WM -.->|сообщения| RM
    RM -.->|маршрутизация| PM
    RM -.->|маршрутизация| WM
```

## Пример использования в Process Manager

```mermaid
sequenceDiagram
    participant ProcessManager
    participant ObservableMixin
    participant LoggerManager
    participant StatsManager
    participant RouterManager
    
    ProcessManager->>ObservableMixin: __init__(managers={...})
    ObservableMixin->>ObservableMixin: создание прокси-методов
    ProcessManager->>ProcessManager: start_process()
    ProcessManager->>ObservableMixin: log_info("Starting process")
    ObservableMixin->>LoggerManager: info("Starting process")
    ProcessManager->>ObservableMixin: record_metric("process.started")
    ObservableMixin->>StatsManager: record_metric("process.started")
    ProcessManager->>ObservableMixin: route_message(msg, "worker")
    ObservableMixin->>RouterManager: route(msg, "worker")
```

