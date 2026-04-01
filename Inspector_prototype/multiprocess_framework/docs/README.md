# docs/ — Документация фреймворка

**Корень:** [../README.md](../README.md)  
**Индекс:** [../DOCUMENTATION_INDEX.md](../DOCUMENTATION_INDEX.md)  
**Решения:** [../DECISIONS.md](../DECISIONS.md)

---

## Актуальные документы

| Файл | Назначение |
|------|------------|
| **[FRAMEWORK_OVERVIEW.md](./FRAMEWORK_OVERVIEW.md)** | Полный обзор: слои, принципы, жизненный цикл, quick start |
| **[CONFIG_SCHEMA_DATA_FLOW.md](./CONFIG_SCHEMA_DATA_FLOW.md)** | Цепочка: `SchemaBase` → dict → `Config` / `proc_dict` / процессы |
| **[CONFIG_PATHS.md](./CONFIG_PATHS.md)** | Канонический слой schema→dict, ветки доставки, фасад `get_config`, антипаттерны |
| **[ARCHITECTURE_REFERENCE.md](./ARCHITECTURE_REFERENCE.md)** | Диаграммы и таблицы (быстрая справка) |
| **[ROUTING_GLOSSARY.md](./ROUTING_GLOSSARY.md)** | Процесс vs канал Router, регистры, `connection_map` |
| **[ARCHITECTURE_MODULE_CATALOG.md](./ARCHITECTURE_MODULE_CATALOG.md)** | Каталог модулей и связей с прототипом |
| **[FRONTEND_COMMAND_LAUNCHER_ROADMAP.md](./FRONTEND_COMMAND_LAUNCHER_ROADMAP.md)** | План: sender, лаунчер, фазы UI-команд |
| **[MODULE_README_TEMPLATE.md](./MODULE_README_TEMPLATE.md)** | Шаблон `README.md` для нового модуля |

---

## Порядок чтения

1. **Первый контакт:** [FRAMEWORK_OVERVIEW.md](./FRAMEWORK_OVERVIEW.md) (разделы 1–7).
2. **Конфиги и схемы (dict at boundary):** [CONFIG_SCHEMA_DATA_FLOW.md](./CONFIG_SCHEMA_DATA_FLOW.md).
2b. **Одна модель преобразования и ветки:** [CONFIG_PATHS.md](./CONFIG_PATHS.md).
3. **Справка и схемы:** [ARCHITECTURE_REFERENCE.md](./ARCHITECTURE_REFERENCE.md).
4. **Почему так устроено:** [../DECISIONS.md](../DECISIONS.md) (ADR).
5. **Конкретный модуль:** `modules/<name>/README.md` и `STATUS.md`.
