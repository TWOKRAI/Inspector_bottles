# Agent Cheatsheet — 5 частых задач

> Быстрый старт для агента или нового разработчика.  
> Полная документация: `README.md`, `docs/MODULES_OVERVIEW.md`, `docs/CONSTRUCTOR_BLUEPRINT.md`.

---

## 1. Добавить новый плагин

1. Создать класс наследник `ProcessModulePlugin` в `multiprocess_prototype/plugins/`
2. Реализовать `configure(ctx)`, опционально `start(ctx)`, `shutdown(ctx)`, `process(items)`
3. Зарегистрировать через `@register_plugin` или добавить в blueprint
4. **Файлы:** `modules/process_module/plugins/base.py` (контракт), `modules/process_module/plugins/interfaces.py` (IProcessServices Protocol)

---

## 2. Создать новый процесс

ProcessModule — универсальный. Поведение через config, не наследование:

```python
ProcessModule(config={"plugins": [{"plugin_class": "...", "plugin_name": "..."}]})
```

**Файлы:** `modules/process_module/core/process_module.py`, `modules/process_module/generic/plugin_orchestrator.py`

---

## 3. Добавить IPC-сообщение между процессами

1. Отправка: `self.send_message("target_process", {"type": "data", ...})`
2. Обработка: `self.router_manager.register_message_handler("msg_type", handler)`
3. Dict at Boundary: только `dict` между процессами (ADR-008)

**Файлы:** `modules/router_module/`, `modules/message_module/`, `docs/ROUTING_GLOSSARY.md`

---

## 4. Добавить новый менеджер / расширить модуль

1. Наследовать от `BaseManager + ObservableMixin`
2. Реализовать `initialize()` / `shutdown()`
3. Добавить `interfaces.py`, `README.md`, `STATUS.md`, `tests/`
4. ADR в `DECISIONS.md` модуля

**Файлы:** `modules/base_manager/`, `docs/EXTENSION_GUIDE.md`, `docs/CONSTRUCTOR_BLUEPRINT.md`

---

## 5. Найти что где лежит

| Задача | Куда смотреть |
|--------|--------------|
| Все 22 модуля | `docs/MODULES_OVERVIEW.md` |
| Как модули связаны | `docs/DIAGRAMS.md` |
| Архитектурные решения | `DECISIONS.md` (корень + модульные) |
| Контракты модулей | `docs/MODULE_CONTRACTS.md` |
| Паттерны фреймворка | `docs/CONSTRUCTOR_BLUEPRINT.md` §4 |
| Глоссарий роутинга | `docs/ROUTING_GLOSSARY.md` |
| Правила фреймворка | `docs/claude/FRAMEWORK_RULES_EXTRACT.md` |
