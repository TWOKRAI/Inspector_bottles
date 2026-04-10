# План: GUI-команды, лаунчер, масштабирование UI — дорожная карта (детальная)

> **Статус документа (2026-04-10):** актуальный проектный roadmap; не является спецификацией реализованного кода.

**Статус:** проектный документ для реализации в отдельной сессии / репозитории.  
**Аудитория:** разработчик, архитектор, нейросетевой агент.  
**Связанные документы:**

- [ARCHITECTURE_MODULE_CATALOG.md](./ARCHITECTURE_MODULE_CATALOG.md) — **каталог всех модулей и пакетов** (отсюда строить диаграммы связей).
- [ROUTING_GLOSSARY.md](./ROUTING_GLOSSARY.md), [FRAMEWORK_OVERVIEW.md](./FRAMEWORK_OVERVIEW.md), `frontend_module/README.md`, `DECISIONS.md`.

---

## 0. Философия: «бриллиант без перегруза»

### 0.1 Цели

| Цель | Как измерять |
|------|----------------|
| Мощный фреймворк | Новое приложение переиспользует **message / router / process / frontend** без копипасты отправки команд. |
| Гибкость | Инъекция `resolve_targets` и каталога args — **без** импорта приложения из `frontend_module`. |
| Масштабирование UI | Много окон и виджетов — **один** реестр окон, **матрёшка** feature-папок (см. каталог §B.2). |
| Меньше слоёв в голове | Один канонический путь «кнопка → процесс»; второй путь только с ADR. |

### 0.2 Ограничители сложности (обязательные)

1. **Один релиз логики «отправить команду из GUI»** — после фазы M1 в коде не должно остаться двух независимых реализаций (handler vs mixin).
2. **Не добавлять новый модуль** ради 50 строк — сначала `frontend_module/application/` или `core/`.
3. **Фаза M2 (лаунчер)** не начинается, пока M1 не закрыта тестами и ADR.
4. **Домен не в фреймворке:** `command_routing`, `GUI_COMMAND_CATALOG`, схемы регистров Inspector — только в приложении (ADR-050).
5. **command_module / dispatch_module** не использовать как «замену» пути GUI→очередь; они про **внутри процесса** после доставки.

### 0.3 Разрешённый стек слоёв (чтобы не запутаться)

Концептуально для **одной** кнопки «отправить команду в другой процесс»:

```text
[Виджет прототипа] → [GuiCommandHandler или тонкий фасад]
    → [RoutedCommandSender]  ← единственная реализация «сборка + send»
        → MessageAdapter.command  (message_module)
        → IRouterLike.send_message  (process_module / контракт frontend_module)
```

**Не добавлять** между виджетом и sender: Coordinator, второй Handler, EventBus — без отдельного ADR.

Для **полей регистров** (не command):

```text
Виджет → RegistersManager.set_field_value → FrontendRegistersBridge → router → register_update
```

Два параллельных механизма (register vs command) — **норма**; путаница лечится документацией и чеклистом в [registers/CHECKLIST.md](../../../multiprocess_prototype/registers/CHECKLIST.md).

---

## 1. Контекст: что есть сейчас

### 1.1 Прототип

| Компонент | Роль |
|-----------|------|
| `frontend/commands/gui_command_handler.py` | `execute(command_id)` → routing + catalog → `MessageAdapter.command` → `send_message` |
| `backend/gui_process_mixin.py` | `_send_command` — **дубликат** логики sender |
| `registers/command_routing.py` | `command_id` → список имён процессов |
| `registers/gui_command_catalog.py` | `command_id` → `args_builder(**kwargs)` |
| `frontend/launcher.py` | Конфиг, регистры, handler, `FrontendManager`, окна, loading→main |

### 1.2 Модули фреймворка (роль в этой задаче)

| Модуль | Роль |
|--------|------|
| **message_module** | Канон сборки COMMAND и `to_dict()` |
| **process_module** (через `IRouterLike`) | Фактическая отправка в очередь |
| **router_module** | Внутри процесса — полноценный роутер; GUI держит только контракт отправки |
| **command_module** | Обработка **после** доставки в целевой процесс |
| **dispatch_module** | Уточнение маршрута **внутри** обработчика |
| **frontend_module** | `FrontendManager`, `WindowManager`, мост регистров, компоненты UI |

### 1.3 Два пути (нельзя смешивать)

- **Путь A — outbound GUI:** `MessageAdapter` + `send_message` → другой процесс (**сюда RoutedCommandSender**).
- **Путь B — inbound worker:** dict в процессе → `CommandManager` / `dispatch` (**не** подменять путь A).

Подробнее: §1.3 прежней версии плана (сохранено по смыслу).

---

## 2. Цель A: `RoutedCommandSender` (универсальный отправитель)

### 2.1 Имя и расположение

- **Имя класса:** `RoutedCommandSender` (фиксировать в ADR).
- **Пакет:** `frontend_module/application/routed_command.py` (или `core/`, если `application` перегружен — выбрать один раз и не плодить оба).
- **Экспорт:** добавить в `frontend_module/__init__.py` только если это не создаёт циклов; иначе импорт «прямой» из подмодуля (как сейчас с частью API).

### 2.2 Конструктор (инъекция)

```python
# Сигнатура (псевдокод для реализации)
class RoutedCommandSender:
    def __init__(
        self,
        router: IRouterLike,
        message_factory: SupportsCommandMessage,  # протокол: .command(...) -> has to_dict()
        resolve_targets: Callable[[str], List[str]],
        get_args_builder: Optional[Callable[[str], Optional[Callable[..., dict]]]] = None,
    ): ...
```

- `get_args_builder(command_id)` возвращает `None` или callable; если `None` — метод `send(command_id, args=dict, data=optional)`.

### 2.3 Методы

| Метод | Поведение |
|-------|-----------|
| `send(command_id, *, args=None, data=None, **kwargs)` | Если есть builder из каталога и переданы `kwargs` — собрать args; иначе использовать `args`. Далее как в текущем `_send`. |
| `send_or_raise` (опционально, фаза L) | Для строгого UI; не обязателен в M1. |

### 2.4 Протоколы в `frontend_module/interfaces.py`

Добавить минимум:

- `SupportsCommandMessage` с методом `command(targets, command, args, data, need_ack=False)` возвращающим объект с `to_dict()`.

Не тянуть `MessageAdapter` типом из `message_module` в публичный импорт `frontend_module.interfaces`, если это ломает изоляцию — достаточно Protocol.

### 2.5 Интеграция в прототип (после M1)

| Файл | Изменение |
|------|-----------|
| `gui_command_handler.py` | Хранит `_sender: RoutedCommandSender`; `execute` делегирует; convenience-методы остаются **здесь** (домен). |
| `gui_process_mixin.py` | `_send_command` вызывает **тот же** экземпляр sender (передать ссылку при старте GUI или создать лениво из `self._msg` + `self.send_message` + closures на app resolve/catalog). |

**Важно:** не создавать **два** sender с разными замыканиями — один объект на процесс GUI.

### 2.6 Тесты фреймворка (M1)

- Файл: `frontend_module/tests/test_routed_command_sender.py` (или рядом с существующими тестами модуля).
- Мок `router.send_message` записывает `(target, dict)`.
- Мок `message_factory.command` возвращает простой объект с `to_dict()`.
- Проверить: вызов `resolve_targets`, первый target, формат dict (минимум ключей как у реального command message — сверить с `MessageAdapter`).

---

## 3. Цель B: каркас лаунчера (только после M1)

### 3.1 Зачем откладывать

Лаунчер трогает больше файлов и сценариев (окна, таймеры). **Сначала** выровнять отправку команд — меньше связей при отладке.

### 3.2 MVP лаунчера (M2)

Не обязательно ABC с 8 методами. Достаточно:

**Вариант 1 (предпочтительный для простоты):** одна функция

`run_process_attached_frontend(process_ref, *, hooks: FrontendLaunchHooks) -> int`

где `FrontendLaunchHooks` — `Protocol` или `dataclass` с полями-колбэками:

- `build_ui_config(process_ref) -> dict`
- `build_registers() -> tuple[Any, dict]`
- `create_command_sender(process_ref) -> RoutedCommandSender` (или совместимый интерфейс)
- `register_windows(wm, fm, config, sender, app, process_ref) -> None`
- `on_registers_boot(rm, config) -> None` (optional)

**Вариант 2:** класс `FrontendAppLauncher` с теми же хуками — если команда предпочитает ООП.

Прототип: `FrontendLauncher` становится **тонкой обёрткой**, заполняющей `hooks` из текущего кода.

### 3.3 Масштабирование: много окон

| Требование | Реализация |
|------------|------------|
| Новое окно | Папка `windows/<name>/`, фабрика регистрируется **только** в `register_windows` / хуке; ключ в `window_registry` конфига. |
| Не плодить лаунчеры | Один `FrontendLauncher` / один вызов `run_process_attached_frontend`. |
| Общие зависимости окна | Передавать `registers_manager`, `command_sender`, callbacks через замыкание фабрики (как сейчас `create_main_window`). |

### 3.4 Связь с `ApplicationCoordinator`

- **M2:** не встраивать Coordinator, если нет явного запроса — уменьшение слоёв.
- **Фаза L:** либо делегирование из Coordinator в ту же функцию `run_process_attached_frontend`, либо ADR «единая точка входа».

---

## 4. `MessageManagerAdapter` и второй канал отправки

| Действие | Когда |
|----------|--------|
| Удалить из прототипа неиспользуемый экспорт | Вместе с M1 или отдельным микрокоммитом |
| Интеграция с `CommandAdapter.execute_via_message` | Только фаза L + ADR + `message_manager` на `ProcessModule` |

До этого **не** открывать второй путь отправки из GUI.

---

## 5. Дорожная карта по фазам (чёткий чеклист)

### M0 — подготовка (½ дня)

- [ ] Прочитать [ARCHITECTURE_MODULE_CATALOG.md](./ARCHITECTURE_MODULE_CATALOG.md).
- [ ] ADR в `DECISIONS.md`: «Outbound GUI command = IRouterLike + MessageAdapter + RoutedCommandSender; домен снаружи».
- [ ] Зафиксировать имя файла и пакета sender (раздел 2.1).

**Готово, если:** ADR смержен, команда согласна с путём A/B.

---

### M1 — RoutedCommandSender + убрать дубль (ядро)

- [ ] `frontend_module/.../routed_command.py` + Protocol в `interfaces.py`.
- [ ] Тесты моками (без Qt).
- [ ] `GuiCommandHandler` на sender.
- [ ] `GuiProcessMixin._send_command` на тот же sender.
- [ ] `pytest multiprocess_prototype/tests` зелёный.
- [ ] `python scripts/validate.py` (с PYTHONPATH).
- [ ] `frontend_module/STATUS.md` обновлён.

**Не делать в M1:** лаунчер-ABC, Coordinator, fan-out на несколько процессов, async send.

**Definition of Done M1:** grep по репозиторию не находит второй копии логики `resolve_command_targets` + `command(` + `send_message` в handler и mixin (только вызовы sender).

---

### M2 — каркас лаунчера (после M1)

- [ ] Вынести общую последовательность из `FrontendLauncher.run` в функцию/базовый хук (раздел 3.2).
- [ ] Прототип: делегирование; поведение идентично (регрессия тестов + ручной smoke GUI).
- [ ] Документ: обновить `multiprocess_prototype/docs/ARCHITECTURE.md` одним абзацем.

**Не делать в M2:** новые типы окон, рефакторинг всех виджетов.

---

### M3 — чистка и документация

- [ ] Удалить или подключить `MessageManagerAdapter` (решение из §4).
- [ ] В `ARCHITECTURE_MODULE_CATALOG.md` добавить строку про `RoutedCommandSender` в части C.
- [ ] Опционально: Mermaid в `frontend_module/docs/ARCHITECTURE.md` (как в старом §5 плана).

---

### Фаза L (позже, отдельные ADR)

- Fan-out команд на `targets[1:]`.
- `send_async` из UI при нагрузке.
- Слияние с `ApplicationCoordinator`.
- `ProcessModule.message_manager` для `CommandAdapter`.

---

## 6. Анти-паттерны

| Анти-паттерн | Почему плохо |
|--------------|--------------|
| Импорт `multiprocess_prototype` из `frontend_module` | Ломает переиспользование фреймворка. |
| Новый слой «CommandBus» между виджетом и sender | Лишняя сущность без запроса на pub/sub. |
| Вызов `router_module.send` напрямую из виджета | Обход ProcessModule и единого контракта процесса. |
| Хранение routing в JSON без типов | Сложнее ревью и агентам; лучше Python-каталог + тесты. |
| Два лаунчера с разной последовательностью `initialize` | Разъезд поведения окон. |

---

## 7. Таблица «куда кладём что» (сводная)

| Сущность | Фреймворк | Прототип |
|----------|-----------|----------|
| Формат COMMAND | message_module | — |
| Отправка в очередь | IRouterLike | — |
| RoutedCommandSender | frontend_module | фабрика hooks передаёт resolve/catalog |
| resolve + catalog | — | registers/* |
| Схемы регистров | — | registers/schemas |
| Окна/вкладки Inspector | — | frontend/* |
| Каркас run | frontend_module (после M2) | hooks |
| Обработка в worker | command_module (+ dispatch) | handlers процесса |

---

## 8. Инструкция для другого чата / агента

1. Открыть **сначала** [ARCHITECTURE_MODULE_CATALOG.md](./ARCHITECTURE_MODULE_CATALOG.md) — нарисовать или запросить диаграмму по §A.2 и §B.1.
2. Выполнить **только M0 + M1**; остановиться и перепроверить DoD M1.
3. Затем M2, затем M3.
4. Не смешивать фазы L без явного запроса пользователя.
5. После каждой фазы: ADR/STATUS + validate + pytest.

**Критерий успеха всего этапа M1–M3:** прототип короче по дублям, фреймворк даёт один переиспользуемый sender, каталог модулей актуален, количество ментальных слоёв для «кнопка→процесс» = 3 (виджет → handler/sender → message+router).
