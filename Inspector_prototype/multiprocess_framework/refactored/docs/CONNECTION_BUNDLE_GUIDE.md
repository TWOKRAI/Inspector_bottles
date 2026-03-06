# Connection Bundle — примеры и оценка подхода

## 1. Что передаётся вместо SharedResourcesManager

### Bootstrap → ProcessManagerProcess

```python
# process_manager_bootstrap.py
bundle = {
    "queues": {},  # ProcessManager не имеет своих очередей
    "config": {"processes_config": self.processes_config},
    "custom": {"process_config": {"processes_config": self.processes_config}}
}

Process(target=run_process_function, args=(class_path, "ProcessManager", stop_event, bundle))
```

### ProcessManagerCore → дочерний процесс (process_test_1, process_b)

```python
# process_manager_core.py
queues = self.queue_registry.get_process_queues(name)
routing_map = dict(self.queue_registry.registered_queues)  # Телефонная книга: все процессы
process_data = self.shared_resources.get_process_data(name)
custom = dict(process_data.custom) if process_data else {}
custom.setdefault("process_config", process_config)

bundle = {
    "queues": queues,
    "config": process_config,
    "custom": custom,
    "routing_map": routing_map   # {process_name: {queue_type: Queue}} — все видят друг друга
}

Process(target=run_process_function, args=(class_path, name, stop_event, bundle))
```

**Двухфазное создание** (`_create_processes_from_config`): сначала создаются очереди для всех процессов, затем запускаются процессы — чтобы routing_map содержал всех.

### run_process_function — построение SharedResourcesManager из bundle

```python
# process_runner.py
if isinstance(shared_resources_or_bundle, dict):
    shared_resources = SharedResourcesManager()
    queues = bundle.get("queues", {})
    config = bundle.get("config", {})
    custom = bundle.get("custom", {})
    
    shared_resources.register_process_state(process_name, ...)
    for qtype, q in queues.items():
        shared_resources.process_state_registry.add_queue(process_name, qtype, q)
    # Телефонная книга: добавляем все процессы из routing_map
    for target_name, target_queues in bundle.get("routing_map", {}).items():
        if target_name != process_name:
            shared_resources.register_process_state(target_name)
            for qtype, q in (target_queues or {}).items():
                shared_resources.process_state_registry.add_queue(target_name, qtype, q)
```

---

## 2. Роутер и доступ к элементам

### Телефонная книга (routing_map)

Все процессы получают `routing_map` — карту очередей всех процессов. Каждый видит всех.

| Процесс | process_state_registry | RouterManager |
|---------|------------------------|---------------|
| **ProcessManagerProcess** | Все дочерние (строит при создании детей) | Может отправлять всем |
| **process_test_1, process_b** | Все процессы из routing_map | Может отправлять любому |

### Что работает

- **process_test_1 → process_b**: `queue_registry.send_to_queue("process_b", "data", msg)` — работает.
- **broadcast_message()**: рассылает всем процессам из registry.
- **ProcessManagerProcess → дети** и **дети ↔ дети**: полная связность.

### Разделённая память

- **multiprocessing.Manager()** — не используется (избегаем RLock).
- **multiprocessing.Queue** — используется; очереди передаются в bundle и pickle-совместимы.
- **multiprocessing.shared_memory** — MemoryManager использует `shared_memory.SharedMemory`; это отдельный механизм, не связанный с bundle.

---

## 3. Профессиональная оценка подхода

| Критерий | Балл | Комментарий |
|----------|------|-------------|
| **Простота** | 9/10 | Минимальный bundle (queues, config, custom), без лишних слоёв |
| **Эффективность** | 8/10 | Только pickle-совместимые объекты, нет лишней сериализации |
| **Кросс-платформенность** | 9/10 | Решает проблему RLock на Windows (spawn) |
| **Расширяемость** | 9/10 | routing_map — телефонная книга для P2P |
| **Обратная совместимость** | 8/10 | Поддержка старого пути (SharedResourcesManager) |
| **Архитектурная чистота** | 9/10 | Дети и отец видят друг друга через routing_map |

**Итог: 8.5/10**

### Плюсы

- Устраняет pickle RLock на Windows.
- Простая модель: dict + Queue + Event + routing_map.
- SharedResourcesManager создаётся в целевом процессе, без передачи тяжёлых объектов.
- Очереди действительно общие (multiprocessing.Queue через pipe).

### Минусы

- ProcessManagerProcess не имеет своих очередей в bundle (`queues: {}`) — обратная связь от детей к нему через очереди не настроена по умолчанию.

