# Multiprocess Framework — Professional Multiprocessing System for Python

**Version:** 2.0 (Refactored, Phase 8/8 Complete)  
**Status:** ✅ Production Ready  
**Python:** 3.8+  
**License:** MIT

---

## What is This?

**Multiprocess Framework** is a **comprehensive architectural system** for building reliable, scalable, multithreaded and multiprocessing applications in Python.

Instead of:
```python
# ❌ Raw multiprocessing (painful)
q_in = Queue()
q_out = Queue()
q_log = Queue()
q_err = Queue()
p = Process(target=worker, args=(q_in, q_out, q_log, q_err, ...))
# ... what protocol? how to structure? how to log? when to stop?
```

You get:
```python
# ✅ Multiprocess Framework (structured)
launcher = SystemLauncher(processes=[
    ("processor", {"class_path": "MyApp.ProcessorProcess"}),
    ("logger", {"class_path": "MyApp.LoggerProcess"}),
])
launcher.run()  # blocks until Ctrl+C, graceful shutdown
```

---

## Core Features

✅ **15 modular, independent components**  
✅ **Unified messaging protocol** (Message with 9 types)  
✅ **Type-safe data structures** (Pydantic v2 + SchemaBase)  
✅ **Centralized logging & error handling** (through ObservableMixin)  
✅ **Graceful shutdown** (signal handling, timeout cascades)  
✅ **Thread-safe worker management** (WorkerManager)  
✅ **Dict at Boundary** (process-safe serialization)  
✅ **Request-Response pattern** (correlation_id)  
✅ **Observable/Proxy pattern** (transparent logging)  
✅ **Channel routing** (Router, Logger, Error managers)

---

## Architecture at a Glance

```
Application (Your Code)
    ↓
ProcessModule (base class for each process)
    ├─ RouterManager (send/receive messages)
    ├─ CommandManager (dispatch commands)
    ├─ WorkerManager (manage threads)
    ├─ LoggerManager (centralized logging)
    └─ ConfigManager (manage configuration)
    ↓
ProcessManagerProcess (orchestrator)
    ├─ ProcessRegistry (all processes)
    ├─ ProcessMonitor (state tracking)
    └─ SharedResourcesManager (inter-process resources)
    ↓
SystemLauncher (entry point)
    └─ Fork/spawn processes, handle signals
```

**15 Modules Organized in 5 Layers:**

| Layer | Modules | Purpose |
|-------|---------|---------|
| **Foundation** | base_manager, data_schema_module, message_module | Core abstractions, type safety |
| **Infrastructure** | logger_module, error_module, config_module, console_module, shared_resources_module | Services & utilities |
| **Communication** | router_module, dispatch_module, command_module | Inter-process messaging |
| **Process** | worker_module, process_module | Process & thread management |
| **Orchestration** | process_manager_module | System startup & lifecycle |

---

## Quick Start

### 1. Create a Process

```python
from multiprocess_framework.refactored.modules.process_module import ProcessModule
from multiprocess_framework.refactored.modules.worker_module import (
    ThreadConfig, ExecutionMode
)
import time

class CameraProcess(ProcessModule):
    def initialize(self) -> bool:
        self.log_info("Camera starting")
        
        # Create a worker thread
        def capture_frames(stop_event, pause_event):
            frame_count = 0
            while not stop_event.is_set():
                if pause_event.is_set():
                    time.sleep(0.05)
                    continue
                
                frame_count += 1
                self.log_info(f"Captured frame {frame_count}")
                
                # Send to detector
                msg = self.msg.command(
                    targets=["detector"],
                    command="detect",
                    args={"frame_id": frame_count},
                )
                self.router.send(msg)
                
                time.sleep(0.033)  # ~30 FPS
        
        self.create_worker(
            "capture",
            capture_frames,
            ThreadConfig(execution_mode=ExecutionMode.LOOP),
            auto_start=True,
        )
        return True
    
    def shutdown(self) -> bool:
        self.log_info("Camera shutting down")
        return True
```

### 2. Create Another Process

```python
class DetectorProcess(ProcessModule):
    def initialize(self) -> bool:
        self.log_info("Detector starting")
        
        # Register command handler
        self.command_manager.register_command(
            "detect",
            self._detect_handler
        )
        return True
    
    def _detect_handler(self, msg_data):
        frame_id = msg_data.get("frame_id")
        self.log_info(f"Detecting in frame {frame_id}")
        
        # Send results somewhere
        msg = self.msg.command(
            targets=["display"],
            command="show",
            args={"objects": 5},
        )
        self.router.send(msg)
        return {"status": "done"}
    
    def shutdown(self) -> bool:
        self.log_info("Detector shutting down")
        return True
```

### 3. Launch

```python
from multiprocess_framework.refactored.modules.process_manager_module import SystemLauncher

if __name__ == "__main__":
    launcher = SystemLauncher(
        processes=[
            ("camera", {
                "class_path": "myapp.CameraProcess",
                "config": {"fps": 30},
            }),
            ("detector", {
                "class_path": "myapp.DetectorProcess",
                "config": {"model": "yolo.pt"},
            }),
            ("display", {
                "class_path": "myapp.DisplayProcess",
                "config": {},
            }),
        ],
        console_enabled=True,
    )
    
    launcher.run()  # blocks until Ctrl+C
```

**That's it!** Your system:
- Creates 3 processes (camera, detector, display)
- Communicates through typed messages
- Logs everything to console/files
- Handles errors gracefully
- Shuts down cleanly on Ctrl+C

---

## Key Concepts

### 1. Message Protocol (Dict at Boundary)

Processes communicate through typed messages:

```python
# 9 message types
msg = adapter.command(targets=["detector"], command="detect", args={...})
msg = adapter.log("error", "Failed to initialize")
msg = adapter.request(targets=["service"], request_type="status", timeout=5)
msg = adapter.response(targets=["requester"], request_id=req_id, result={...})
msg = adapter.event("frame_ready", event_data={...})
msg = adapter.broadcast(content=data, exclude=["self"])
msg = adapter.system(targets=[...], action="pause")
msg = adapter.data(targets=[...], data_type="frame", data=blob)

# Convert to dict at process boundary
raw = msg.to_dict()  # ← send through queue
# Restore in other process
msg = Message.from_dict(raw)
```

### 2. Observable Logging (Transparent Integration)

All managers automatically log through a unified interface:

```python
class MyManager(BaseManager, ObservableMixin):
    def __init__(self, name, logger=None):
        BaseManager.__init__(self, name)
        ObservableMixin.__init__(
            self,
            managers={'logger': logger} if logger else {},
        )
    
    def do_work(self):
        self._log_debug("debug info")     # → LoggerManager.debug()
        self._log_info("processing")      # → LoggerManager.info()
        self._record_metric("ops", 1)     # → StatsManager.record()
        try:
            risky_operation()
        except Exception as e:
            self._track_error(e)          # → ErrorManager.log_exception()
```

### 3. Graceful Shutdown

Processes are cleaned up properly:

```
Ctrl+C / SIGTERM
    ↓
ProcessRegistry.stop_all(timeout=5s)
    ├─ Set stop_event for each process
    ├─ Wait for graceful exit (up to 5s)
    ├─ If hanging: SIGTERM
    ├─ If still hanging: SIGKILL
    └─ Guarantee: all dead in 5s
    ↓
Flush logs, close connections
    ↓
Exit code 0
```

### 4. Type-Safe Data Structures

Define your process's data schema:

```python
from data_schema_module import SchemaBase, FieldMeta, FieldRouting
from typing import Annotated

class DetectorConfig(SchemaBase):
    confidence: Annotated[float, FieldMeta(
        "Detection confidence",
        min=0.0, max=1.0,
        unit="%",
    )] = 0.5
    
    max_objects: Annotated[int, FieldMeta(
        "Max objects per frame",
        min=1, max=1000,
    )] = 100

# Automatic validation
config = DetectorConfig()
config.update_field("confidence", 0.8)  # ✓ OK
config.update_field("confidence", 1.5)  # ✗ Error
```

---

## Documentation

| Document | Purpose | Read Time |
|----------|---------|-----------|
| **[DOCUMENTATION_INDEX.md](./DOCUMENTATION_INDEX.md)** | Navigation & quick links | 5 min |
| **[FRAMEWORK_OVERVIEW.md](./FRAMEWORK_OVERVIEW.md)** | Complete overview (8000+ lines) | 45 min |
| **[ARCHITECTURE_REFERENCE.md](./ARCHITECTURE_REFERENCE.md)** | Diagrams & tables | 30 min |
| **[ARCHITECTURE_ESSAY.md](./ARCHITECTURE_ESSAY.md)** | Design philosophy | 30 min |
| **[DECISIONS.md](./DECISIONS.md)** | 21 architectural decisions (ADRs) | 20 min |

**Each module also has:**
- `README.md` — module documentation
- `STATUS.md` — refactoring status & scores
- `interfaces.py` — public contract
- `tests/` — usage examples

---

## Design Patterns Used

✅ Factory Pattern (MessageFactory)  
✅ Strategy Pattern (4 dispatch strategies)  
✅ Adapter Pattern (everywhere)  
✅ Observer Pattern (ObservableMixin)  
✅ Template Method Pattern (ProcessModule)  
✅ Proxy Pattern (logging proxies)  
✅ Dependency Injection (explicit dependencies)  

---

## Performance

| Operation | Complexity | Notes |
|-----------|-----------|-------|
| Send message | O(1) | AsyncSender buffering |
| Dispatch command | O(1) | Dict lookup (EXACT_MATCH) |
| Create process | O(n) | Depends on memory |
| Graceful shutdown | O(timeout) | 5-10 seconds typical |
| Logging batch | O(batch_size) | Amortized O(1) |

---

## When to Use

### ✅ Ideal For

- **Video processing** (camera → detector → tracker → UI)
- **IoT applications** (sensors → processing → storage)
- **Microservices** (lightweight service architecture on one machine)
- **Monitoring systems** (multi-source data collection)

### ❌ Not For

- Simple scripts (use raw `multiprocessing`)
- Distributed systems (use Docker + Kubernetes)
- Async-only code (use `asyncio` instead)

---

## Testing

Run all tests:

```bash
cd Inspector_prototype/multiprocess_framework/refactored
pytest modules/ -v
```

Test specific module:

```bash
pytest modules/router_module/tests/ -v
```

With coverage:

```bash
pytest modules/ --cov=modules --cov-report=html
```

---

## Principles

1. **Explicit is Better Than Implicit** — No hidden globals, all dependencies passed explicitly
2. **Separation of Concerns** — Each module handles one responsibility
3. **Graceful Everything** — Graceful initialization, shutdown, degradation, error handling
4. **Type Safety** — Pydantic + Protocol for type hints
5. **Modularity** — 15 independent modules, can be extended/replaced
6. **Dict at Boundary** — Process-safe serialization

---

## Project Structure

```
Inspector_prototype/multiprocess_framework/refactored/
├── FRAMEWORK_OVERVIEW.md          # Main documentation (start here)
├── ARCHITECTURE_REFERENCE.md      # Diagrams & tables
├── ARCHITECTURE_ESSAY.md          # Design philosophy
├── DECISIONS.md                   # 21 architectural decisions
├── DOCUMENTATION_INDEX.md         # Navigation guide
│
├── modules/                       # 15 modules
│   ├── base_manager/
│   ├── data_schema_module/
│   ├── message_module/
│   ├── logger_module/
│   ├── error_module/
│   ├── config_module/
│   ├── router_module/
│   ├── dispatch_module/
│   ├── command_module/
│   ├── worker_module/
│   ├── process_module/
│   ├── process_manager_module/
│   ├── console_module/
│   ├── shared_resources_module/
│   └── registers_module/
│
└── multiprocess_prototype/        # Example application
    └── main.py                    # Full working example
```

---

## Contributing

When adding new features:

1. Define interface in `interfaces.py` (Protocol or ABC)
2. Implement in module
3. Write tests in `tests/`
4. Update module `README.md`
5. Run `pytest` — all tests must pass
6. Update `DECISIONS.md` if architectural
7. Update `DOCUMENTATION_INDEX.md`

---

## License

MIT

---

## Changelog

### v2.0 (Phase 8/8 Complete) — March 2026
- ✅ All 15 modules complete and production-ready
- ✅ Comprehensive documentation (5000+ lines)
- ✅ 21 architectural decisions documented
- ✅ Full test coverage (100+ unit tests)
- ✅ Graceful shutdown with signal handling
- ✅ Error recovery with error_module
- ✅ CommandManager with 6 built-in commands

---

## Support

For questions or issues:

1. Check `DOCUMENTATION_INDEX.md` for navigation
2. Read `FRAMEWORK_OVERVIEW.md` for the concept
3. Look at `ARCHITECTURE_REFERENCE.md` for specifics
4. Check module `README.md` files
5. Review `tests/` for usage examples

---

**Built with ❤️ for reliable multiprocessing in Python**

Last Updated: March 13, 2026
