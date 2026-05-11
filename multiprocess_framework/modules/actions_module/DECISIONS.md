# actions_module — Архитектурные решения

## ACT-001: `set_pre_execute_hook` — минимальное расширение ActionBus для pre-execute блокировки

**Дата:** 2026-05-11
**Статус:** Принято
**PR:** PR2 auth-rbac (Group A)

### Контекст

Для блокировки мутаций до авторизации (PreAuthGuard) нужна точка перехвата
в ActionBus перед вызовом handler.apply(). Два варианта:
1. Один метод `set_pre_execute_hook(hook, on_blocked)` в ActionBus.
2. HandlerProxy-обёртки в bus_factory.

### Решение

Вариант 1 — один метод `set_pre_execute_hook`. Hook вызывается в `execute()`
перед `handler.apply()`. Если hook вернул False — apply не вызывается,
undo_stack не трогается, опционально вызывается on_blocked.

`undo()` и `redo()` хук НЕ проходят — откат уже совершённого действия не блокируется.

Один хук (last-write wins). Если уже установлен — заменяется.

### Альтернативы

- HandlerProxy: proxy обёртки дублируются для каждого handler-а, при добавлении
  нового handler блокировка теряется. Hook — единственная точка входа.
- Middleware-stack: избыточно для одного хука. Если в будущем понадобится
  цепочка — вводится middleware-stack в PR4.

### Последствия

- ActionBus остаётся простым и тестируемым.
- Приложение (prototype) регистрирует хук через bus_factory.
- Фреймворк не знает про конкретную auth-логику.
