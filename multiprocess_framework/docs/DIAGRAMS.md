# Диаграммы (Mermaid)

Сводка визуализаций для `ARCHITECTURE.md`, обзоров и презентаций. Рендер: VS Code / GitHub / Typora.

---

## 1. Architecture layer cake

Одиннадцать слоёв, 21 пакет в `modules/`. Снизу вверх — от примитивов к приложению.

```mermaid
flowchart TB
  subgraph L1 [Foundation]
    BM[base_manager]
    DS[data_schema_module]
    MSG[message_module]
  end
  subgraph L2 [Routing primitives]
    DSP[dispatch_module]
    CRM[channel_routing_module]
  end
  subgraph L3 [Messaging]
    RTR[router_module]
  end
  subgraph L4 [Observability]
    LOG[logger_module]
    ERR[error_module]
    STA[statistics_module]
  end
  subgraph L5 [Resources and config]
    SRM[shared_resources_module]
    CFG[config_module]
    SS[state_store_module]
  end
  subgraph L6 [Command and work]
    CMD[command_module]
    WRK[worker_module]
    CHN[chain_module]
  end
  subgraph L7 [Process]
    PM[process_module]
  end
  subgraph L8 [Orchestration]
    PMM[process_manager_module]
  end
  subgraph L9 [Optional infra]
    CON[console_module]
    SQL[sql_module]
  end
  subgraph L10 [UI optional]
    FE[frontend_module]
  end
  L1 --> L2
  L2 --> L3
  L2 --> L4
  L5 --> L7
  L3 --> L7
  L4 --> L7
  L6 --> L7
  L7 --> L8
  REG[registers_module] --> L7
  REG --> FE
```

---

## 2. Message flow (IPC)

```mermaid
sequenceDiagram
  participant PA as Process A
  participant MA as MessageAdapter
  participant RT as RouterManager
  participant Q as Queue / channel
  participant PB as Process B
  PA->>MA: build message dict
  MA->>RT: enqueue / route
  RT->>Q: write
  Q->>PB: read / dispatch
```

---

## 3. Process lifecycle

```mermaid
stateDiagram-v2
  [*] --> CREATED
  CREATED --> INITIALIZING : spawn / fork
  INITIALIZING --> RUNNING : initialize OK
  RUNNING --> STOPPING : stop signal
  STOPPING --> SHUTDOWN : cleanup
  SHUTDOWN --> [*]
  RUNNING --> STOPPING : crash
```

---

## 4. Config data flow

```mermaid
flowchart LR
  YAML[YAML / Python config] --> SB[SchemaBase model_validate]
  SB --> MD[model_dump dict]
  MD --> PL[process / build]
  PL --> SL[SystemLauncher]
  SL --> PK[pickle bundle]
  PK --> CH[Child ProcessModule]
```

---

## 5. Module dependency graph (21 packages)

```mermaid
graph BT
  base_manager
  data_schema_module
  message_module
  dispatch_module
  channel_routing_module
  logger_module
  error_module
  statistics_module
  router_module
  shared_resources_module
  config_module
  state_store_module
  registers_module
  command_module
  worker_module
  chain_module
  process_module
  process_manager_module
  console_module
  sql_module
  frontend_module
  channel_routing_module --> base_manager
  logger_module --> channel_routing_module
  error_module --> logger_module
  statistics_module --> channel_routing_module
  router_module --> channel_routing_module
  router_module --> message_module
  state_store_module --> base_manager
  chain_module --> base_manager
  process_module --> router_module
  process_module --> command_module
  process_module --> worker_module
  process_module --> shared_resources_module
  process_manager_module --> process_module
  process_manager_module --> shared_resources_module
```

---

## 6. Constructor analogy

```mermaid
flowchart LR
  subgraph PC [ПК = приложение]
    MB[Материнская плата = base_manager + data_schema]
    CPU[CPU = process_module]
    BUS[Шина = message_module + router]
    NIC[NIC = IPC queues / Router channels]
    RAM[RAM = shared_resources / config slices]
    HDD[HDD = persistence / recipes]
  end
```

**Смысл:** фреймворк поставляет «комплектующие»; приложение подключает драйверы (воркеры, схемы, процессы) по контракту Dict at Boundary.
