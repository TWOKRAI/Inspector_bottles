# `frontend_module` — Архитектурные решения

PySide6-фреймворк виджетов с привязкой к `data_schema_module` (`SchemaBase` + `FieldMeta` + `FieldRouting`). Каждое решение зафиксировано как **ADR** в глобальном `multiprocess_framework/DECISIONS.md`.

> **Этот файл — индекс**, а не дубль. Каждая запись ниже ссылается на полный текст в глобальном `DECISIONS.md`.

---

## Реестр

| ADR | Тема | Глобальный текст |
|-----|------|------------------|
| ADR-033 | `frontend_module` и `shared_registers` — фундамент UI-фреймворка | `../../DECISIONS.md#adr-033` |
| ADR-034 | `FrontendManager` — единая точка входа (`BaseManager`) | `../../DECISIONS.md#adr-034` |
| ADR-035 | `FrontendRegistersBridge` — связь frontend с backend через регистры | `../../DECISIONS.md#adr-035` |
| ADR-036 | Конфигурация frontend — hot-reload без перезапуска | `../../DECISIONS.md#adr-036` |
| ADR-037 | Рефакторинг `frontend_module` и прототипа (2026-03-18) | `../../DECISIONS.md#adr-037` |
| ADR-042 | `ProcessModule` как `IRouterLike` для `FrontendManager` | `../../DECISIONS.md#adr-042` |
| ADR-043 | Унифицированные конфиги frontend на `SchemaBase` + `FieldMeta` | `../../DECISIONS.md#adr-043` |
| ADR-044 | Реорганизация `components/` и паттерн «конфиг рядом с виджетом» | `../../DECISIONS.md#adr-044` |
| ADR-053 | Прототип — один `GuiProcess`, импорты регистров, `FrontendManager` runtime | `../../DECISIONS.md#adr-053` |
| ADR-084 | `FrontendAppContext` — явный контекст вкладок без слияния слоёв | `../../DECISIONS.md#adr-084` |
| ADR-090 | `frontend/coordinators`, границы виджет / Presenter / `managers` | `../../DECISIONS.md#adr-090` |
| ADR-095 | `StructuredTwoLevelTreeWidget` — группа → строки | `../../DECISIONS.md#adr-095` |
| ADR-097 | Touch-клавиатура — проброс из `FrontendConfig`, делегат по колонкам | `../../DECISIONS.md#adr-097` |
| ADR-135 | Механизм вкладок → `TabRegistry`; приложение декларирует `TABS: list[TabSpec]`; permissions/roles деривятся из реестра | `../../DECISIONS.md#adr-135` |
| ADR-139 | `TelemetryPoller` — опрос уровней по видимости вкладки; вторая дорога в тот же read-model, гейт не трогается | `../../DECISIONS.md#adr-139` |

---

## Краткая суть (без дублирования полного текста)

**1. Конфиг рядом с виджетом (ADR-044).** Каждый виджет в `components/<name>/` имеет свой `config.py` с `SchemaBase`-наследником. Конфиг не лежит отдельно в `configs/` — это нарушает принцип «модуль = одна папка».

**2. Виджет ↔ регистр (ADR-035).** Виджет связывается с полем регистра через `FieldRouting.channel` + `FieldMeta`. `FrontendRegistersBridge` подписывается на изменения регистра и обновляет UI; обратно — через `set_field_value()` в `RegistersManager`.

**3. `FrontendManager` — `BaseManager` (ADR-034).** Точка входа в подсистему фронтенда из процесса. Управляет окнами, виджетами, привязкой к регистрам.

**4. Координаторы (ADR-090).** `frontend/coordinators/` — слой между виджетом, Presenter и managers. Виджет не знает про Router/IPC — координатор делегирует действия в backend.

**5. Hot-reload конфигов (ADR-036).** Изменение `FrontendConfig` через `ConfigManager.subscribe()` пересобирает виджеты без перезапуска процесса.

---

## Где искать детали

- Архитектура виджетов — `README.md` модуля.
- Cookbook — `WIDGET_COOKBOOK.md` модуля (примеры компонентов).
- Полный текст ADR — глобальный `multiprocess_framework/DECISIONS.md`.
- Дорожная карта — `multiprocess_framework/docs/FRONTEND_COMMAND_LAUNCHER_ROADMAP.md`.

---

## Локальные решения (FE-серия)

> Записи FE-серии охватывают тему RBAC/Auth-интеграции в frontend_module (PR1 Group C).
> Глобальный индекс — `multiprocess_framework/DECISIONS.md` (обновляется через `python -m scripts.sync`).

### FE-001: Расширение `AccessContext` — именованные permissions + role_name (2026-05-11)

**Контекст.** `AccessContext` хранил только числовой `level` + булевые флаги. Для RBAC нужны именованные права.

**Решение.** Добавлены поля `permissions: frozenset[str]` и `role_name: str` после существующих полей (`level, bypass_readonly, show_hidden`) — позиционные вызовы `AccessContext(5, True, True)` сохраняются без изменений. `frozenset` выбран как immutable + hashable. Сериализация через `to_dict()` / `from_dict()`: permissions → sorted list[str] (детерминизм).

**Backward compat.** `from_dict({})` без ключей permissions/role_name → дефолтные значения. Конструктор без новых полей работает. Существующие тесты не тронуты.

**Альтернативы.** `list[str]` — нет, не hashable. `set[str]` — нет, mutable. Отдельный класс RBAC-контекста — избыточно для PR1.

---

### FE-002: `AccessTrait` двухосевая модель view/edit (2026-05-11)

**Контекст.** Старый `AccessTrait` знал только `can_modify()` через числовой level. RBAC требует отдельно `can_view()` и `can_modify()`.

**Решение.** Добавлены параметры `required_view_permission` и `required_edit_permission`. Логика:
- `can_view()`: если perm задан → `ctx.has_permission(perm)`, иначе `True`.
- `can_modify()`: coherence invariant `edit ⇒ view` (нет view → нет edit); если edit_perm задан → permission check; иначе legacy `ctx.level >= N OR ctx.bypass_readonly`.

**Backward compat.** Первый позиционный аргумент → `legacy_required_level`. Kwarg `required_level=N` → `DeprecationWarning` + работает. `update(int)` → `DeprecationWarning` + создаёт минимальный `AccessContext(level=N)`. `update(AccessContext)` → новый путь без warning. `set_required_level()` — сохранён.

**Coherence invariant.** `can_modify() → can_view()` — enforced в коде: если `can_view() == False`, `can_modify()` возвращает `False` немедленно.

---

### FE-003: Централизация access policy в `BaseConfigurableWidget._apply_access` (2026-05-11)

**Контекст.** До PR1 каждый виджет сам решал что делать при смене уровня доступа. Нет единого места для `setVisible/setEnabled/readOnly+QSS`.

**Решение.** Добавлен метод `_apply_access()` в `BaseConfigurableWidget`. Логика: `can_view==False` → `setVisible(False)`; `can_view==True` → `setVisible(True)`, `setEnabled(can_modify())`, `setProperty("readOnly", not can_modify())` + QSS repolish через `style().unpolish/polish`. Метод защищён guard'ом `if not hasattr(self, "_trait") or self._trait is None`.

`_update_access_level()` сохранён как deprecated alias с `DeprecationWarning`, внутри обновляет trait через legacy путь и вызывает `_apply_access()`.

**Почему repolish.** QSS-селектор `[readOnly="true"]` читается только при repolish — без него смена свойства не отражается в стилях.

---

### FE-004: GUI-контракт request/response для дискретных команд (2026-06-07)

**Контекст.** GUI слал команды бэкенду fire-and-forget и не знал результат (активация рецепта «молча» падала или успевала — UI не отличал). Транспорт request/response уже существовал (ADR-005, correlation_id), но GUI-сторона его не использовала.

**Решение.** Дискретные команды GUI→PM (активация рецепта, start/stop/restart, replace_blueprint) идут **request/response** — GUI узнаёт реальный результат. Высокочастотный **field-write остаётся fire-and-forget** (request на каждую правку слайдера = блокировка). Контракт потоков: `request()` выполняется на **worker-потоке** (`RequestRunner` поверх `QThreadPool`, паттерн `DataReceiverBridge`), результат маршалится в **main-thread сигналом** (AutoConnection) — никакого прямого доступа к виджетам с воркера. Timeout щедрый (30s); слепое ожидание уберёт lifecycle-прогресс поверх того же канала (`request(on_progress=...)`).

**Реализация.** `CommandSender.request_command/request_system_command` + `IRequestingProcess` (framework, `deae8b91`); `RequestRunner` + `ProcessManagerProxy.*_async(on_result)` (prototype, `e9e29f71`); presenter активации рецепта (`c4894133`). Авто-reply транспортом по `request_id` даёт паритет с fire-and-forget (no-op без correlation).

**Альтернативы.** `request()` из main-thread — отвергнуто (фриз UI). Request для field-write — отвергнуто (блокировка hot-path). Модальный диалог результата — отвергнуто (`c4894133` non-modal, не рвёт поток работы).

---

### FE-005: Qt-free ядро read-model телеметрии вынесено в общий модуль (reuse-vs-own, 2026-07-18)

**Контекст.** Плану `backend-ctl-framework-module` (Task 2.3) нужен GUI-эквивалент чтения телеметрии для headless-драйвера диагностики (backend_ctl): локальная модель поверх `state.changed`-дельт + история, 0 IPC на чтение. Единственный кандидат на переиспользование — generic `TelemetryViewModel` (промотирован coherence Task 3.5). Прямой reuse невозможен: VM — `QObject` (`Signal`+`QTimer`-коалесинг), а `frontend_module`/`state_store_module` тянут PySide6 через package `__init__` → импорт из headless-драйвера затащил бы Qt (регресс: driver сознательно тонкий, из фреймворка тянет только `message_module`).

**Решение.** Хранилище снимка (`path → value`) + кольцевые буферы истории + их тонкие инварианты (граница префикса `snapshot`, приведение к числу, окно `maxlen`) вынесены в новый Qt-free `telemetry_readmodel_module.TelemetryReadModel` (envelope-agnostic `ingest(path, value, deleted)`). `TelemetryViewModel` теперь **композирует** ядро, оставляя себе только GUI-специфику: разбор конверта `state_delta`/`gui_local_metric` и коалесинг Qt-сигнала `updated`. Публичный API VM не изменился (тесты — safety-net). backend_ctl композирует то же ядро, наполняя его push'ами `state.changed`.

**Почему не own-дублирование.** Ядро мало (~90 строк), но его ценность — не строки, а тонкие инварианты: две копии `snapshot`-boundary / number-coercion / ring-window разъедутся при первом же баг-фиксе в одной из них. DRY здесь = защита от дрейфа, а не экономия LOC.

**Почему новый модуль, а не существующий.** Qt-free дома во фреймворке не нашлось: `frontend_module` — Qt-слой; `state_store_module.__init__` тянет `GuiStateProxy`→PySide6 (рефактор его `__init__` — шире blast-radius, чем оправдано). Маленький сфокусированный framework-модуль (README/STATUS/interfaces/tests) — согласуется с правилом №2 и импортируется и GUI-слоем, и headless-tooling.

**Альтернативы.** (1) Прямой reuse GUI-VM — отвергнуто (Qt в headless-драйвере). (2) Own-копия ядра в backend_ctl — отвергнуто (дрейф инвариантов; план допускал лишь «последним вариантом»). (3) Ядро в `state_store_module`/`frontend_module` — отвергнуто (Qt в цепочке импортов package `__init__`).

---

### FE-006: Владение Qt-объектами через область — `qt_lifetime` (Task 0.4, 2026-10-05)

**Контекст.** Область владения base_manager (`IScope`, Task 0.2) закрывает ресурсы по фазам, но `QObject` нельзя удалить синхронно с чужого потока или изнутри сигнала, а GUI-процесс после выхода из `app.exec()` не имеет цикла событий, который доставил бы `deleteLater`. Qt может удалить объект первым (удалён Qt-родитель) — область тогда держит мёртвый объект.

**Решение.** Новый `core/qt_lifetime.py` (Stability: lite), реэкспорт в `interfaces.py`:
- `attach_qt(scope, obj)` — запись вида `"qobject"`. Порядок: проверки → `scope.own(_QtRelease)` → реестр адресов → `destroyed.connect`. Освобождение (`_QtRelease`) зовёт `deleteLater` **до** потери последней ссылки: владение уходит C++, объект удаляется на своём потоке. Синхронного `delete` нет.
- Qt удалил объект первым → `_on_destroyed` закрывает область синхронно; при `scope.closed` (идёт чужой `close`) не ждёт его — иначе фриз flush и нарушение ADR-BM-008. Обработчик держит только `weakref` и C++ адрес: объект не бессмертен.
- Проверка Qt-предка (правило C, вердикт CTO): реестр `dict[id(scope), set[адрес]]`, запись снимает `weakref.finalize(scope, _reg.pop, id, None)`; без лока — каждое чтение/запись одним вызовом C-уровня под GIL (ревью р1: под модульным `_lock` только `_posted`, иначе gc-финализатор мог закрыть чужую область под локом); Qt-родитель привязанного объекта обязан быть объектом своей области или её предка. Несовпадение → пара `qt-tree mismatch` в `errors` (утечка не молчит). Проверка только на потоке объекта (best-effort) и только если выше что-то привязано (правило миграции). Адрес удаляет только `_on_destroyed`, после `close`.
- `flush_deferred_deletes()` — `sendPostedEvents(None, DeferredDelete)` в цикле, пока модуль ставил новые `deleteLater` (счётчик `_posted`, предел 16): каскад «удаление `a` закрывает область → `b.deleteLater`».
- `QThreadHandle` — `Stoppable` над `QThread` без `kill` (`terminate()` запрещён): не остановившийся поток — выживший, объект не удаляется.

**Альтернативы.** (1) Якорь области (первый привязанный объект как Qt-корень) — отвергнуто CTO: порядок привязки становится контрактом, второй верхний объект и таймер без родителя дают ложное несовпадение. (2) `singleShot` вместо синхронного `close` в `destroyed` — отвергнуто: цикла событий может не быть. (3) `kill` через `terminate()` — отвергнуто: аварийный выход Qt и порча состояния. (4) Удалять адрес из реестра в `_QtRelease` — отвергнуто: LIFO освобождает родителя раньше ребёнка, ребёнок получил бы ложное несовпадение (S7).

**Границы.** Потребители (`ThreadManager`, `bindings.py`, старые `deleteLater`, `QTimer()` без родителя) не мигрируют — Ф2/Ф5. Старые `deleteLater` не видны счётчику `_posted`. Предел 16 проходов на глубоком каскаде не измерен.

---

### FE-007: `FramePump` — кадры дисплея вытягиваются таймером на ключ из ящика (план gui-frame-path T2, 2026-11-24)

**Контекст.** Тракт кадров gui складывал каждый кадр в очередь событий Qt без предела: +457 МБ/с при 220 кадр/с, отрисовка 0-1 в секунду (воспроизведено cto offscreen). Лечение (вердикт cto, T1-T2): поток-источник кладёт кадр в `LatestMailbox` (`process_module/generic`, ADR-PM-064) — не больше одного кадра на ключ, без Qt; Qt-поток сам вытягивает кадры по таймеру с частотой `fps_limit`. `FramePump` — Qt-часть: `frontend_module/bridge/frame_pump.py`.

**Решение.**
- **Таймер на ключ**, а не один таймер на круг по ключам: быстрый sender не голодит медленный, у каждого свой предел частоты. Обработчик делает один `take(key)` и один `sink(key, item)`; пустой ящик — тик пропущен без вызова `sink`. `sink` получает весь item без изменений (`capture_ns`, `capture_ts`, `replay` насос не читает).
- **`Qt.PreciseTimer` явно.** `CoarseTimer` привязан к сетке 15,625 мс (40 мс превращаются в 46,9 мс). Замеры reviewer-а (Windows 10, Python 3.12.12, PySide6 6.10.3, offscreen, свободная машина):

  | лимит, Гц | Coarse, Гц | Precise, Гц |
  |---|---|---|
  | 20 | 16,0 | 20,0 |
  | 25 | 21,0 | 24,5 |
  | 30 | 21,0 | 29,0 |
  | 60 | 58,5 | 58,5 |

  Числа таблицы — измерения reviewer-а стадии 5 по готовому насосу (период `ceil`). Прежние значения Precise 25,0 и 30,3 в этой таблице, по замечанию reviewer-а, относились к периоду `int()`, а не к `ceil`.

  Под нагрузкой четырёх таймеров по 7,4 мс `Precise` держал 20,0 / 24,9 / 30,2 (при периодах `int()`). Сторож типа таймера — тест полосы `fps_limit` 30 за 2 с (допуск 52..62; `Coarse` даёт 42): тест T3 `test_no_aliasing_22hz_source_limit_20` его не сторожит.
- **Период `ceil(1000 / clamp(fps_limit or 60, 1, 60))` мс.** `ceil`, а не `int`: на 60 Гц `int` даёт 16 мс = 62,5 Гц выше потолка, `ceil` даёт 17 мс = 58,8 Гц. Потолок 60 Гц: `0`/`None` = 60 (дисплею не нужно чаще кадра монитора; решение 1 вердикта). Нечисловой и NaN `fps_limit` трактуются как `None` и не роняют `set_keys`.
- **Ключ вне `set_keys` находит скан**: таймер насоса раз в 100 мс зовёт `mailbox.pending_keys()` и заводит ключу без таймера таймер на 30 Гц. Причина: неизвестный sender в gui идёт в слот «main» (`recipe_displays.py:124-143`, `app.py:1157`), кадр не должен лежать в ящике без читателя. Цена: первый кадр такого ключа задержан до 100 мс скана плюс период таймера. Повторный `set_keys` перехватывает такой ключ, а снимает таймеры всех ключей, которых в новом наборе нет (рецепт может сменить набор дисплеев на живом процессе); ключ с кадром в ящике скан заведёт снова.
- **`stats()` потокобезопасен** (его читает поток heartbeat, а `set_keys` меняет набор ключей в Qt-потоке): копия счётчиков под одним `threading.Lock`, который держат `set_keys` и обновление счётчиков; `sink` вызывается вне замка. `window_max_age_ms` — максимум возраста с последнего `stats(reset_window=True)`; `stats()` без аргумента окно не сбрасывает (второй читатель не искажает окно), `max_age_ms` копится за весь прогон. Часы — `time.perf_counter` (у `monotonic` на Windows шаг 15,6 мс).
- **Счётчики снятого ключа удаляются.** `set_keys` убирает вместе с таймером счётчики ключа, которого нет в новом наборе. Следствие для потребителя метрик (T4): сумма `shown` по ключам при смене набора НЕ монотонна; читать дельтами по ключу с зажимом `max(0, новое - прежнее)`.
- **Исключение `sink`** считается в `errors`, насос не останавливается; строка лога не чаще раза в 5 с на ключ (иначе строка на тик на ключ).
- **`stop()`** идемпотентен и гасит скан и таймеры (закрытие окна не оставляет вызовов `sink` в разрушенный виджет); `set_keys` после него ничего не делает.
- **Слабая ссылка в обработчиках таймеров.** `functools.partial(self._tick, key)` в `timeout.connect` держит насос сильной ссылкой изнутри соединения: после `stop()` образуется цикл, сборщик мусора разрушает насос позже, и процесс падает (`Fatal Python error: Aborted` в следующем `exec()`; воспроизведено на PySide6 6.10.3). Обработчик — замыкание над `weakref.ref(self)`; страж — `test_pump_not_kept_alive_by_timer_connections`.

**Альтернативы.** (1) Один таймер и круг по ключам — отвергнуто: общий предел частоты, быстрый ключ голодит медленный. (2) `Signal` с кадром или будящий `Signal` из `put` — отвергнуто: кадр через сигнал — снова неограниченная очередь событий Qt; `put` Qt не трогает (тест `test_put_posts_no_qt_event` с контролем `postEvent`). (3) Ключ вне набора отбрасывать — отвергнуто: кадр неизвестного sender-а должен дойти в слот «main». (4) Импорт `LatestMailbox` в `bridge/` — отвергнуто: ящик принимается по утиной типизации (`take`, `pending_keys`), `frontend_module` не зависит от `process_module`.

**Границы.** `FramePump` — первый модуль `bridge/` с PySide6 на верхнем уровне; `bridge/README.md` и docstring `bridge/__init__.py` (ранее «pure-Python») исправлены, экспорт насоса из `bridge/__init__.py` не добавлен: `import bridge` его не тянет, импортировать из `bridge.frame_pump`. (Сам `import multiprocess_framework.modules.frontend_module` уже кладёт PySide6 в `sys.modules`: инвариант документный, не рантайм.) Подключение к `DataReceiverBridge` и `app.py` — T3 (`_on_frame_received` принимает один аргумент, `sink` насоса — два: нужен адаптер). Замеры таймера сняты на свободной машине; под живым gui не мерялись.

#### Поправка W2-c (план multicam-observability, 2026-11-25): насос сообщает о тишине ключа

Потерянный источник должен быть виден (решение владельца: тёмная плашка «нет сигнала, N с», возврат к кадру при возобновлении). Факт «на этот ключ N с не показан кадр» — факт самого GUI, а пустой ящик был тихим пропуском тика.

- **Параметры:** `FramePump(mailbox, sink, parent=None, *, on_silence: Callable[[str, float | None], None] | None = None, silence_s: float = 0.0)`. Включено при `on_silence is not None and silence_s > 0`; флаг считается один раз в `__init__`.
- **Смысл тишины:** время с последнего ПОКАЗАННОГО кадра этого ключа; у ключа без кадров — с его заведения (`set_keys` или скан). Возраст на ключ, не общий. `on_silence(key, age_s)` зовётся на тике без показа — ящик пуст ИЛИ кадр не показан (`sink` вернул `False` или бросил) — при `age_s >= silence_s`, не чаще раза на целую секунду возраста. Только пустой тик не годится: при источнике не медленнее насоса пустых тиков нет, и замерший экран остался бы без плашки (воспроизведено: 44 не показанных кадра, 0 вызовов). `on_silence(key, None)` — после `sink` первого показанного кадра, пришедшего после сообщённой тишины; без неё кадр колбэк не зовёт.
- **`sink` возвращает `False`, когда кадр не показан** (`Callable[[str, Any], object]`); `None` и всё остальное — «показан». Не показанный кадр (`False` или исключение) тишину не прерывает. `shown` и `max_age_ms` считают и вызовы, вернувшие `False` (смысл счётчиков фазы A не менялся): постоянно падающая копия растит `shown`, пока стоит плашка. `errors` растёт и на исключение `on_silence`; лог такого исключения — со своим дросселем (раз в 5 с на ключ).
- **Часы** — `time.perf_counter`, как у всего насоса.
- **Потоки и `stop()`:** колбэк зовётся в Qt-потоке вне замка насоса; после `stop()` (в том числе из самого `sink` или `on_silence`) ни `sink`, ни `on_silence` не вызываются.
- **Снятие ключа** (`set_keys`) убирает и состояние тишины; колбэк при этом не зовётся — плашки снимает потребитель при своём `set_keys`. Насос не знает о намеренной остановке источника; порог на дисплей — фильтр потребителя по `age_s`. Набор ключей `stats()` не изменён.
- **Цена выключенного режима:** одна проверка флага на тик; ни одного лишнего чтения часов.
- **Отвергнуто:** (1) мерить тишину в источнике — источник не знает, что показано; (2) подделывать чёрный кадр в источнике — его проинспектируют.
