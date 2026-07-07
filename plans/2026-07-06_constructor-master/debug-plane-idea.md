# Отладочная плоскость (debug plane): ревью UI-tap v0 и целевая архитектура

- **Дата:** 2026-07-07, по запросу владельца («ревью на идею и код; лучшая архитектура,
  универсальный инструмент на будущее»)
- **Статус:** v1 реализована (Task 1.11); v2-расширения — списком в конце
- **Контекст:** UI-tap v0 = Task 1.10 (коммит 89ab5797)

## 1. Ревью идеи v0

**Что подтверждено как правильное:**

- **Транспорт.** Переиспользован проверенный путь log-tail Ф1.5 (RouterPushChannel →
  мост 1.1b → relay 1.7): ноль нового IPC, доставка от дочернего gui-процесса до
  внешнего driver'а доказана live e2e. Любой новый источник отладочных событий
  подключается к этому же пути бесплатно — это главный актив идеи.
- **Безопасность прода.** Тап выключен по умолчанию, события не поглощает, ошибки
  доставки глотает и считает; GUI не может пострадать от отладки.
- **Потоковая модель.** Команды из message_processor-потока только переключают
  атрибуты; Qt-объекты из чужого потока не трогаются.
- **ui.tap.ping** — смоук всей цепочки без физического клика: агент за один вызов
  отличает «тап не включён» / «доставка сломана» / «всё живо».

**Слабости идеи (главное — уровень абстракции):**

1. **Ловится жест, а не намерение.** MouseButtonRelease на кнопке ≠ «что GUI сделал».
   Кнопка, активированная клавиатурой (Space/Enter), невидима; combo/spinbox/slider/
   меню/hotkey невидимы; программные вызовы невидимы. Гоняться за каждым типом виджета
   на уровне Qt — тупик (комбинаторика виджетов × способов активации).
2. **Есть единственная дверь GUI→бэкенд, и она не тапалась.** ВСЁ взаимодействие GUI
   с системой проходит через `CommandSender.send_command`/`send_system_command`
   (field/action/flush-пути сходятся в send_command). Один перехват в этой двери ловит
   намерение полностью — независимо от виджета, клавиатуры или кода.
3. **Три источника — три формы событий** (`ui.event`/`log.record`/`state.changed`),
   агент склеивает руками; упорядочивание только по ts (нет seq).
4. **Агенту нужно 3-5 вызовов** для полной картины (ui_tap + log_tail×N +
   state_subscribe) — должна быть одна кнопка.
5. Прибит к прототипу (wiring в run_gui). Для будущих приложений (app_module «рыба»,
   Ф5) установка должна быть частью generic-bootstrap GUI.

**Ревью кода v0 (конкретика):**

- `ui_event_tap.py`: подъём по родителям ограничен 6 уровнями — глубокие композиции
  могут не дойти до кнопки (граница задокументирована); таб по координате клика —
  верно (currentIndex в момент Release ещё старый); QComboBox не ловится (popup —
  отдельное top-level окно) — закрывается перехватом двери (см. выше).
- `tap_commands.py`: `RouterPushChannel` импортируется из logger_module — семантически
  это generic push-канал, его место в router/channel-слое; перенос — отдельная задача
  (не плодить движение файлов в горячей фазе).
- Один подписчик (last wins) — осознанная граница dev-инструмента.
- `driver.ui_tap(process="gui")` — имя процесса конвенцией из base.yaml; приемлемо.

## 2. Целевая архитектура: три уровня наблюдения, один поток, одна форма

```
УРОВЕНЬ      ИСТОЧНИК                         command       record.kind
жест         UiEventTap (Qt-фильтр)           ui.event      button | tab | ping
намерение    CommandSenderTap (дверь GUI→IPC) ui.event      command | system_command
эффект       log tap (Ф1.5)                   log.record    —
             state deltas (1.1b) + health     state.changed —
```

Принципы:

- **Единый конверт.** Всё, что генерит gui-тап, идёт через `UiEventTap.emit_event`:
  общий монотонный `seq` (упорядочивание жест→намерение без гонок ts), общий ts,
  общие счётчики, общая доставка. Новый источник = один вызов `emit_event`.
- **Намерение — перехват двери, не виджетов.** `CommandSenderTap` оборачивает
  `send_command`/`send_system_command` на инстансе (обратимо, install/remove).
  Значения аргументов обрезаются (`_safe_args`) — в state-дерево и сокет не едут
  мегабайтные значения.
- **Одна кнопка для агента: `debug_session`.** `driver.debug_session(logs_level=,
  state_pattern=, processes=)` включает жест+намерение+логи+state одним вызовом,
  `debug_stop()` выключает. MCP: инструменты `debug_session`/`debug_stop`; чтение —
  существующий `events` (единая очередь driver'а и есть «один поток»).
- **Универсальность.** Уровни «эффект» generic для всех процессов (уже во framework);
  gui-уровни живут в `frontend_module/debug` — любое будущее приложение получает их
  вызовом `register_ui_tap_commands` из своего GUI-bootstrap (для app_module «рыбы» —
  включить в generic-bootstrap, задача Ф5).

Сценарий агента («отладить кнопку»):

```python
drv.debug_session()              # всё включено одним вызовом
# пользователь (или qt-mcp) нажимает кнопку в GUI
for e in drv.events(timeout=10):
    ...  # ui.event(button, seq=41) → ui.event(command, seq=42, command='register_update')
         # → log.record(preprocessor) → state.changed(processes.preprocessor...)
```

Видна вся цепочка «жест → намерение → эффект» с одним driver'ом; разрыв между
уровнями локализует баг (жест есть, команды нет → мёртвая кнопка; команда есть,
эффекта нет → бэкенд, см. introspect/verify-probe).

## 3. Реализовано в v1 (Task 1.11)

- `UiEventTap`: сквозной `seq` во всех событиях.
- `frontend_module/debug/intent_taps.py`: `CommandSenderTap` (install/remove,
  идемпотентно; `_safe_args` — обрезка значений до 200 симв.).
- `ui.tap.subscribe`: параметр `sources` (`["gesture","command"]`, дефолт оба);
  unsubscribe снимает всё, включая перехват двери.
- `driver.debug_session()/debug_stop()`; MCP `debug_session`/`debug_stop` (24 инстр.).
- run_gui: `process._ui_command_sender = command_sender` (доступ тапу к двери).

## 4. v2 (отложено, по потребности)

- **ActionBusTap** (семантические undo-действия): хук `add_post_execute_callback`
  готов в ActionBus, но живой bus создаётся глубоко в окне (bus_factory → main_window)
  — нужна протяжка ссылки; брать при первом реальном сценарии undo-отладки.
- Перенос `RouterPushChannel` logger_module → router/channel-слой (generic push).
- Мульти-подписчики тапа (сейчас last wins).
- `debug_session` пресеты в capability manifest (агент узнаёт о плоскости из
  CAPABILITIES, а не из доков).
- Автоустановка в generic GUI-bootstrap app_module (Ф5, «рыба»).
