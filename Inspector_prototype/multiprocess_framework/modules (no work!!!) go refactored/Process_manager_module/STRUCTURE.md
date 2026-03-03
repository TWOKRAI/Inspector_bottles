# Структура Process Manager Module

## 📁 Организация по папкам

Модуль организован по принципу разделения ответственности (Separation of Concerns).

### core/ - Утилитарные классы

Содержит классы с бизнес-логикой управления процессами (не процессы).

- `process_manager_core.py` - Основная логика управления процессами
- `process_lifecycle.py` - Управление жизненным циклом процессов
- `process_priority.py` - Управление приоритетами процессов
- `process_status.py` - Мониторинг статусов процессов

**Использование:**
```python
from src.Modules.Process_manager_module.core import ProcessManagerCore
```

### process/ - ProcessManager как процесс

Содержит ProcessManagerProcess - ProcessManager как процесс системы.

- `process_manager_process.py` - ProcessManagerProcess (наследуется от ProcessModule)

**Использование:**
```python
from src.Modules.Process_manager_module.process import ProcessManagerProcess
```

### bootstrap/ - Bootstrap для запуска

Содержит Bootstrap для запуска ProcessManagerProcess.

- `process_manager_bootstrap.py` - ProcessManagerBootstrap

**Использование:**
```python
from src.Modules.Process_manager_module.bootstrap import ProcessManagerBootstrap
```

### legacy/ - Обратная совместимость

Содержит старый ProcessManager для обратной совместимости.

- `Processes_Manager.py` - ProcessManager (legacy)

**Использование:**
```python
from src.Modules.Process_manager_module.legacy import ProcessManager
# или
from src.Modules.Process_manager_module import ProcessManager  # через __init__.py
```

### config/ - Конфигурация

Содержит классы для работы с конфигурацией процессов.

- `process_config.py` - ProcessConfig, ProcessConfiguration

**Использование:**
```python
from src.Modules.Process_manager_module.config import ProcessConfig, ProcessConfiguration
```

### runner/ - Запуск процессов

Содержит функции для запуска процессов (top-level для сериализации).

- `process_runner.py` - _run_process_function

**Использование:**
```python
from src.Modules.Process_manager_module.runner import _run_process_function
```

### monitor/ - Мониторинг

Содержит классы для мониторинга процессов.

- `process_monitor.py` - ProcessMonitor

**Использование:**
```python
from src.Modules.Process_manager_module.monitor import ProcessMonitor
```

### platforms/ - Платформо-зависимые адаптеры

Содержит адаптеры для разных платформ.

- `base.py` - Базовый класс PlatformAdapter
- `windows.py` - WindowsPlatform
- `linux.py` - LinuxPlatform

**Использование:**
```python
from src.Modules.Process_manager_module.platforms import get_platform_adapter
```

## 🔄 Зависимости между компонентами

```
Bootstrap
    ↓ использует
ProcessManagerProcess (ProcessModule)
    ↓ использует
ProcessManagerCore
    ↓ использует
ProcessLifecycle, ProcessPriority, ProcessStatus
    ↓ используют
ProcessRunner, ProcessMonitor
```

## 📝 Правила импорта

1. **Внутри модуля**: Используйте относительные импорты (`..`, `...`)
2. **Извне модуля**: Используйте абсолютные импорты через `__init__.py`
3. **Между папками**: Используйте относительные импорты с указанием папки

**Примеры:**

```python
# Внутри core/process_manager_core.py
from .process_lifecycle import ProcessLifecycle
from ...runner.process_runner import _run_process_function

# Извне модуля
from src.Modules.Process_manager_module import ProcessManagerCore
from src.Modules.Process_manager_module.core import ProcessLifecycle
```

## ✅ Преимущества такой структуры

1. **Четкая ответственность** - каждая папка отвечает за свою область
2. **Легкая навигация** - понятно где что находится
3. **Простое тестирование** - легко тестировать отдельные компоненты
4. **Масштабируемость** - легко добавлять новые компоненты
5. **Обратная совместимость** - старый код сохранен в legacy/

