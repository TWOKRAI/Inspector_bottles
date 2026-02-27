# Как сообщить об ошибках

## 📋 Что нужно предоставить

Для быстрой диагностики и исправления ошибок, пожалуйста, предоставьте:

### 1. Точный текст ошибки

Скопируйте полный вывод ошибки из терминала, включая:
- Тип ошибки (AttributeError, TypeError, NameError и т.д.)
- Сообщение об ошибке
- Стек трейс (traceback)

### 2. Команда запуска

Укажите точную команду, которую вы использовали:
```bash
# Пример
python src/multiprocess_framework/refactored/run_all_tests.py --module worker_module
```

### 3. Какой тест падает

Укажите:
- Имя теста
- Имя модуля
- Номер строки (если есть)

### 4. Контекст

- Какие исправления были применены
- Что работало до этого
- Что изменилось

## 🔍 Пример правильного отчета

```
Ошибка: AttributeError: 'WorkerRegistry' object has no attribute 'is_enabled'

Команда: pytest src/multiprocess_framework/refactored/modules/worker_module/tests -v

Тест: test_create_manager

Стек трейс:
  File ".../worker_manager.py", line 83, in initialize
    self._log_info(f"WorkerManager '{self.manager_name}' initialized")
  File ".../observable_mixin.py", line 264, in _call_manager
    if not hasattr(self._registry, 'is_enabled'):
AttributeError: 'WorkerRegistry' object has no attribute 'is_enabled'
```

## 🛠️ Быстрая диагностика

Если не можете скопировать ошибку, попробуйте:

1. **Запустить конкретный тест:**
   ```bash
   pytest src/multiprocess_framework/refactored/modules/worker_module/tests/test_worker_manager.py::TestWorkerManager::test_create_manager -v --tb=long
   ```

2. **Проверить импорты:**
   ```bash
   python -c "from multiprocess_framework.refactored.modules.worker_module import WorkerManager; print('OK')"
   ```

3. **Проверить структуру:**
   ```bash
   python src/multiprocess_framework/refactored/check_module.py worker_module --all
   ```

---

**Пожалуйста, пришлите полный текст ошибки для точной диагностики!**

