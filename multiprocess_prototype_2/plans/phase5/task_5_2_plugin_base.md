# Task 5.2 — Расширение ProcessModulePlugin + @for_each

**Status:** IN PROGRESS
**Branch:** `feat/phase5-task5.2-plugin-base`
**Level:** Middle (Sonnet)
**Assignee:** developer

## Цель

Добавить `process()`, `produce()`, `is_source`, `thread_safe` и декоратор `@for_each` в базовый класс ProcessModulePlugin.

## Файлы

| Действие | Путь |
|----------|------|
| ИЗМЕНИТЬ | `multiprocess_framework/modules/process_module/plugins/base.py` |
| ИЗМЕНИТЬ | `multiprocess_framework/modules/process_module/plugins/__init__.py` |
| СОЗДАТЬ  | `multiprocess_framework/modules/process_module/tests/test_plugin_base_pipeline.py` |

## Изменения в base.py

1. `process(self, items: list[dict]) -> list[dict]` — default pass-through
2. `produce(self) -> list[dict]` — default NotImplementedError
3. `is_source` property → `self.category == "source"`
4. `thread_safe: ClassVar[bool] = False` — атрибут класса
5. `for_each` — модульная функция-декоратор рядом с классом

## Тесты (≥ 8)

1. default process → pass-through
2. produce → raises NotImplementedError
3. is_source True для category="source"
4. is_source False для category="processing"
5. thread_safe default False
6. @for_each: dict return → 1:1
7. @for_each: list return → 1:N (extend)
8. @for_each: None return → фильтрация (skip)

## Acceptance Criteria

- [ ] process() default pass-through
- [ ] produce() default NotImplementedError
- [ ] is_source property
- [ ] thread_safe ClassVar[bool] = False
- [ ] for_each экспортирован из plugins/__init__.py
- [ ] Существующие плагины не ломаются
- [ ] ≥ 8 тестов проходят
