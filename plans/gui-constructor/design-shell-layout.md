# Дизайн: оболочка, раскладка, виджет, пакеты, Пульт

Часть плана [`plan.md`](plan.md). Редакция §6–§7 T4.1 ([`gui-bootstrap-design.md`](../frontend-constructor/gui-bootstrap-design.md))
под решение владельца [`constructor-layers.md`](../frontend-constructor/constructor-layers.md) → «Форма конструктора»,
«Пульт». Соседи: [`design-boot.md`](design-boot.md), [`design-connection-context.md`](design-connection-context.md).

---

## 1. Оболочка (`GuiHostWindow`) — вне Gen-1 `windows/`

**Путь — `multiprocess_framework/modules/frontend_module/host/`** (находка CTO 4). T4.1 §6 клал шелл в
`frontend_module/windows/host_window.py`, но `windows/` — Gen-1, «LEGACY, frozen» (`frontend_module/STATUS.md`), а
ступень 3.0 окна codemod rework его **удаляет** (`framework-architecture-rework/plan.md:361`). Файлы `host/*` вносятся
в список разреза rework 2б.2 этим планом (синхронизация соседей).

Оболочка владеет: окнами (одно главное + любые дополнительные `QMainWindow`), доками (`QDockWidget` на экземпляр
виджета), вкладками из доков (`tabifyDockWidget`), выносом дока в плавающее окно, пунктом «Переместить в окно…»,
сохранением/восстановлением раскладки, **замком**, статусом подключений, F11/Esc, хуком закрытия
`close_guards: list[Callable[[str], bool]]`, строкой статуса с `add_status_widget`.

Разбор `multiprocess_prototype/frontend/windows/main_window.py` (766 строк, `wc -l` перепроверен) — таблица T4.1 §6,
номера строк «(T4.1)»:

| Генерик → оболочка | Прикладное → остаётся в прототипе |
|---|---|
| F11/Esc полноэкранный режим (`262-263`, `380-405`) | `AppHeaderWidget`, `ErrorBannerWidget` (`20-21`) → центральная часть `inspector.classic` |
| Сохранение и восстановление геометрии (`271-285`) → раскладка оболочки | Кнопка «Скрыть» и drag-высота вкладок, `HideToggleButton` (`45-113`, `442-582`) → внутри `classic` до его дробления |
| Undo/Redo-шорткаты на `UndoRedoController` (`409-440`) → действие оболочки, контроллер даёт пакет | RS-4: индикаторы топологии, `confirm_discard_topology_changes` (`207-226`, `300-346`, `639-664`) → `close_guards` |
| Строка статуса (`228-233`) | FPS/Latency/Frames и 5 биндингов `system.*` (`595-626`) → `add_status_widget` из пакета |
| — | Аккумуляторы кадров и трассы (`673-766`) → `wire_frames`/`timers` пакета |
| — | Dirty-метка Settings (`634-637`) |

В оболочке нет ни одного импорта прототипа, `Services`, `Plugins` и ни одного пути `system.*`; предметных слов нет
(гейт домен-паттерна frontend-constructor Ф6: `bottle|defect|inspection|Inspector_bottles` = 0).

## 2. Раскладка — данные

### 2.1 Два слоя: декларация и правки пользователя (находка CTO c)

| Слой | Что | Где | Кто пишет |
|---|---|---|---|
| **Декларация** (YAML) | подключения → окна → доки → `widget` + `params` + `connection`; пресеты по ролям; какие доки заперты | `default_layout` пакета; рабочее место — `INSPECTOR_CONFIG_DIR/layouts/<role>.yaml` | разработчик пакета; наладчик — через «Сохранить раскладку как…» |
| **Правки пользователя** (блоб) | геометрия, положение доков, плавающие окна — `QMainWindow.saveState()` + `saveGeometry()` | prefs клиента рядом с YAML: `<role>.<window>.state` | оболочка, при закрытии |

Оба ключуются по **`objectName`**: у окна — `window.<id>`, у дока — `dock.<widget_id>`, где `widget_id` — ключ экземпляра
в YAML (стабилен между запусками). Источник правды о **составе** — YAML; блоб только двигает то, что YAML создал.

Порядок применения: создать окна и доки по YAML → `restoreGeometry`/`restoreState` блоба → **заново применить замок**
→ `show`. Проба CTO: `restoreState` чужого состояния вернул `True` — возвратом валидировать нельзя. Поэтому блоб
хранится вместе с хешем набора `objectName`; при несовпадении (пакет добавил/убрал виджет) блоб **не применяется**,
раскладка встаёт по YAML, в лог — одна строка с причиной.

Формат YAML (черновик, уточняет Task 2.1):

```yaml
layout_version: 1
connections: [inspector]              # имена из конфига клиента; встроенный GUI — [local]
windows:
  main:
    title: "Инспектор"
    docks:
      camera:   {widget: inspector.classic, connection: inspector, area: center, locked: true}
      procs:    {widget: fw.processes, connection: inspector, area: right, tab_with: null}
  aux:
    docks:
      pult_1:   {widget: fw.pult, params: {knobs: [...]}, area: left}
```

### 2.2 Замок

Запертый док: без кнопки закрытия, без выноса в окно, без перемещения (`setFeatures(NoDockWidgetFeatures)` +
`setAllowedAreas` = текущая). Замок — атрибут дока в YAML (`locked: true`) плюс общий режим «Заблокировать раскладку»
(оператор) / «Разблокировать» (наладчик, будущая проверка роли через auth бэкенда). **Замок переживает `restoreState`**:
он применяется после восстановления и проверяется тестом (запертый док после `restoreState` блоба, где тот же док
был плавающим и закрытым, — видим, пристыкован, без кнопки закрытия).

### 2.3 Перемещение между окнами

Проба CTO (offscreen, PySide6 6.10.3): `setFloating(True)` оставляет родителя, `isWindow: True`;
`a.removeDockWidget(d); b.addDockWidget(Right, d)` → родитель `B`, область `RightDockWidgetArea`, в `A` —
`NoDockWidgetArea`. Программный перенос между главными окнами штатный; нет только перетаскивания мышью **между**
окнами. Пункт меню дока «Переместить в окно… ▸ <список окон> / Новое окно» закрывает «быстро раскидывать» без новой
зависимости. **Qt Advanced Docking System** (`PySide6QtAds`, Context7 `/mborgerson/pyside6_qtads`) — только если
понадобится именно мышь между окнами; лицензия и колёса под PySide6 6.10 / aarch64 (Orin NX) не проверены, в
`.venv` не установлена. Не в этом плане (Ф5, по нужде).

### 2.4 Пресеты и QSettings

Пресет по роли = отдельный YAML. Геометрия сегодня пишется в `QSettings("INNOTECH", "Inspector")`
(`main_window.py:266`, перепроверено), а `AppIdentity` — `org="Inspector", app_name="Inspector Bottles"` (`app.py:91`,
перепроверено). Оболочка берёт ключ из `AppIdentity`; старое значение `INNOTECH/Inspector` читается **один раз** при
первом запуске как миграция геометрии главного окна, дальше не трогается. Решение моё, последствия для операторских
машин не оценены (открыто).

## 3. `WidgetSpec` — единица размещения

Qt-free (`frontend_module/bootstrap/interfaces.py`):

| Поле | Тип | Смысл |
|---|---|---|
| `id` | `str` | глобальный ключ с префиксом пакета: `fw.processes`, `inspector.classic`, `sim.layers` |
| `title` | `str` | заголовок дока по умолчанию |
| `backend_role` | `str \| None` | `app_id` бэкенда, к которому виджет применим; `None` — любой (общие виджеты фреймворка) |
| `params` | `Mapping[str, ParamSpec]` | схема параметров экземпляра (движок форм строит редактор) |
| `multi_instance` | `bool` | можно ли держать несколько экземпляров (Пульт — да, `classic` — нет) |
| `factory` | `str` | `"<модуль>:<функция>"`, импорт — лениво при создании дока |
| `legacy` | `bool` | только `inspector.classic`; даёт `ctx.legacy_deps` (`design-connection-context.md` §3.6) |

Нынешние вкладки `TabFactory` регистрируются виджетами **1:1** (Task 1.5): `inspector.pipeline`, `inspector.recipes`, …
— без правки самих вкладок; фабрика-обёртка собирает вкладку из `ctx`/`ctx.legacy_deps`. Переход на чистый контекст —
по вкладке, по нужде (Ф5).

## 4. Пакеты — где живут

| Пакет | Префикс | Место | Qt |
|---|---|---|---|
| Общие виджеты фреймворка (процессы, телеметрия, наблюдаемость, Пульт) | `fw.*` | `frontend_module/widgets/…` (кит), каталог — `frontend_module/host/fw_pack.py` | да |
| Инспекция | `inspector.*` | `multiprocess_prototype/frontend/app_spec.py` + `boot/` | да |
| Срез сервиса | `<svc>.*` | **`Services/<svc>/gui/`** — подпакет, корень сервиса его **не импортирует** | да, только в `gui/` |
| Эталон | `minimal.*` | `examples/minimal_gui/` | да |

**Одно место для пакета симулятора** (находка CTO 5, расхождение с gui-service `architecture.md:37-38`): пакет —
`Services/line_sim/gui/`, не `apps/line_sim/`. Причина: срез сервиса = бэкенд-часть + клиентский порт + пакет виджетов
рядом (решение владельца 2026-09-26); `apps/line_sim` — composition root бэкенда, GUI к нему не относится.
`architecture.md` правится синхронизацией соседей. Корень `Services/line_sim` остаётся без Qt:
`Services/line_sim/__init__.py:3` обещает «без torch и PySide6»; сегодня греп импортов Qt по `Services/line_sim` = 0
(единственное вхождение слова `PySide6` — сам этот докстринг и тест `test_acceptance_3_1.py`).

**Правила слоёв для пакетов (Task 1.0).** Синтаксис sentrux: `[[boundaries]]` с `from`/`to`, deny-список; пути —
**буквальные префиксы каталогов**, `*` заменяет только имя файла и не раскрывает сегменты
(`.claude/plugins/mcp-sentrux/README.md:55-60`); ключа-исключения в файле нет (греп `except|exclude|allow` по
`rules.toml` — 0). Значит, «`Services/* ↛ PySide6` кроме `*/gui/*`» **одним правилом не выражается**. Решение:
1. `examples/* ↛ Services/*` и `examples/* ↛ Plugins/*` — два обычных правила (сегодня импортов `Services|Plugins` в
   `examples` — 0, `grep -rnE` по `examples`);
2. `Services/* ↛ PySide6/*` — **контракт-тестом грепом** (pytest, `Services/tests/` или `scripts/`): импорт
   `PySide6|PyQt|qtpy` в `Services/**/*.py` разрешён только в `Services/*/gui/**` и в трёх автономных инструментах,
   перечисленных поимённо (`Services/robot_comm/server/sim_robot.py`, `…/sim_monitor.py`,
   `Services/hikvision_camera/sdk_app/main_window.py` — сегодняшний греп CTO, перепроверен);
3. плюс sentrux-правила на Qt-free подкаталоги, где префикс не задевает `gui/`
   (`Services/line_sim/core/*` → `PySide6/*` и т. п.) — только если RED-проба Task 1.0 покажет, что sentrux вообще
   ловит `to = "PySide6/*"` для внешнего пакета (существующие правила `rules.toml:224-227, 242-245` этого не
   доказывают — их никто не ломал).

Вердикт по правилам — `sentrux check .` CLI; MCP `check_rules` проверяет 9 из 39 правил (корневой `CLAUDE.md`).

## 5. `inspector.classic` — переходный виджет (находка CTO g)

Виджетом становится **центральная часть** нынешнего `MainWindow` — header / банер / центральная панель / tab-host
(T4.1: `126-174`, `201-205`), **не `QMainWindow`**: статус-бар, F11, геометрия и QSettings — у оболочки, иначе в доке
другого `QMainWindow` окажется второе главное окно со своим статус-баром. Один экземпляр (`multi_instance=False`),
`legacy=True`, запертый док `area: center` в раскладке инспектора по умолчанию. Встроенный GUI после Task 2.2 = оболочка
+ `classic`; снаружи выглядит как сегодня (приёмка — те же вкладки, та же геометрия главного окна).

Закат: дробление на камеру / результаты / управление — Ф5, по нужде роли (оператор не должен закрыть камеру —
замок уже есть; дробить, когда наладчику понадобится другая раскладка). Счётчик долга — sunset-тест `legacy_deps` = 1.

## 6. Пульт — виджет ручек

Решение владельца 2026-09-26 (`constructor-layers.md` → «Пульт»): Пульт — масштабируемый виджет, собирающий ручки из
разных областей; тот же набор доступен без GUI через `backend_ctl`.

### 6.1 Ручка = адрес + описание

Ручка **не ссылается** на чужой виджет. Она привязана к тому же регистру/команде/пути состояния, что исходный виджет,
и оба показывают одно значение через состояние бэкенда. Ручку можно перенести, продублировать, удалить — ничего не
ломается.

**Один адрес для GUI, `backend_ctl` и агентов** (`KnobAddress`, Qt-free, `frontend_module/knobs/address.py`):

| Вид | Строка | Совпадает с |
|---|---|---|
| регистр | `reg:<process>/<register>/<field>` | `backend_ctl` `set_register(process, register, field, value)` (`backend_ctl/registers.py:103`, перепроверено) |
| команда | `cmd:<process>/<command>` | `send_command(process, command, data)` |
| показ | `state:<path>` | путь дерева состояния (`state_get`) |

`parse(str) -> KnobAddress`, `str(addr)` — взаимно обратны; `backend_ctl` принимает ту же строку (Task 4.1). Адрес
не содержит подключения: подключение — у экземпляра Пульта или у ручки (`connection:` в параметрах), по той же
паре (виджет, подключение).

`KnobSpec`: `address`, `label`, `hint` (вид контрола — по умолчанию из описания регистра каталога 1b.2a:
`FieldInfo` → слайдер/поле/тумблер), `confirm` (спрашивать ли подтверждение). Проверка значения — описание регистра
из каталога (1b.2a, 1b.2b-pre); отказ бэкенда откатывает ручку с текстом (1b.2c).

### 6.2 Где хранятся

Ручки для людей — **в раскладке рабочего места** (`params.knobs` экземпляра `fw.pult`): у оператора и наладчика
разные Пульты на одном рецепте. В рецепте остаются только пайплайновые контролы `local` ноды `control_panel`.
Пультов может быть несколько; каждый — обычный виджет (`multi_instance=True`) в любом окне.

**«Вынести на Пульт»** — пункт контекстного меню у любого поля регистра в любом виджете, построенном движком форм:
публикует событие шины интерфейса `fw.pult.add_knob{address, label}`; если Пультов несколько — подменю с их
заголовками; если ни одного — предложение создать.

### 6.3 Зародыш — `Services/control_panel`

`ControlSpec` (`Services/control_panel/controls.py`) уже различает вид (`button|toggle|slider|number|text|select`) и
назначение `source: local|param|monitor|action`; адресует через `target_process` + **`target_plugin_index: int`**
(`controls.py:61`, перепроверено) + `target_field` / `target_command`. Индекс плагина — не адрес `backend_ctl`
(там имя регистра). Сведение (Task 4.4): `param`/`monitor`/`action` получают `address: KnobAddress`; старые поля
читаются один раз при загрузке рецепта и переводятся в адрес (индекс → имя регистра по каталогу плагинов процесса);
запись — только в новой форме. `local` не меняется. GUI сегодня — вкладка сервиса
`multiprocess_prototype/frontend/widgets/tabs/services/control_panel/`, не размещаемый виджет.

**Слои:** модель ручки, адрес и отрисовка через движок форм — фреймворк (предметных слов нет); пайплайновая часть
`control_panel` (плагин, `local`-эмиты) — сервис.

**Четыре «Пульта» (находка CTO 8, условие 4):** (1) виджет ручек и его сервис — **единственное** значение слова
«Пульт» с 2026-09-26; (2) `apps/pult` gui-service → **`apps/gui_client`**; (3) `pult_web` / процесс `pult`
(`apps/line_sim/pipeline.yaml:141`) — веб-пульт ленты, позже его ручки становятся Пультом с адресами бэкенда
`line_sim`; (4) `Services/control_panel` — зародыш (1). В документах gui-service слово «Пульт» исторически значит
клиента (2) — там стоит плашка терминологии.

## 7. Раскладка кода: Qt-free ядро и Qt-пакет (Р-4 rework)

| Тип | Файл | Сторона Р-4 | Задача |
|---|---|---|---|
| `GuiAppSpec`, `GuiHooks`, `WidgetSpec`, `ThemeSpec`, `TimerSpec`, `UiEventSpec` | `frontend_module/bootstrap/interfaces.py` | ядро | 1.4 |
| `GuiHostRuntime`, `EnvelopeBus`, `ConnectionState`, `RuntimeCaps` (Protocol) | `bootstrap/runtime.py` | ядро | 1.3 |
| `ConnectionRegistry` | `bootstrap/connections.py` | ядро | 1.3 |
| `InProcessRuntime` | `bootstrap/runtime_inprocess.py` | ядро | 1.3 |
| `WidgetContext`, каналы, `FrameHub` | `bootstrap/context.py`, `bootstrap/frame_hub.py` | ядро | 1.5 |
| `pack_loader` | `bootstrap/pack_loader.py` | ядро | 1.4 |
| `RemoteGuiRuntime` + реконнект | `bootstrap/remote_runtime.py` | ядро | gui-service 1.4 |
| `BootContext`, `GuiBootstrap`, стадии, `qt_invoker` | `bootstrap/bootstrap.py` | Qt-пакет | 1.4 |
| `EnvelopeBus`-реализация (`DataReceiverBridge`) | `bootstrap/envelope_bus.py` | Qt-пакет | 1.3 (Р-B) |
| `GuiHostWindow`, раскладка, замок, «Переместить в окно» | `frontend_module/host/{window,layout,lock}.py` | Qt-пакет (разбор YAML — ядро: `host/layout_model.py`) | 2.1 |
| Шина интерфейса | `frontend_module/host/ui_bus.py` (Qt-free) | ядро | 3.2 |
| `KnobAddress`, `KnobSpec` | `frontend_module/knobs/{address,spec}.py` | ядро | 4.1 |
| `fw.pult` | `frontend_module/knobs/pult_widget.py` | Qt-пакет | 4.2 |
| `APP_SPEC` инспектора, хуки | `multiprocess_prototype/frontend/app_spec.py`, `frontend/boot/` | прототип | 1.2, 1.4 |

Все — **новые файлы** или правки на месте; окна codemod не требуют. Qt-free проверяется грепом `PySide6` по файлу
(импорт через пакет поднимает PySide6 до расщепления Р-4 — `design-boot.md` §6).

## 8. Открыто и ненадёжно

- Формат YAML раскладки — черновик; хеш набора `objectName` как защита блоба — моё решение, не проверено пробой.
- Миграция `INNOTECH/Inspector` → `AppIdentity` — одноразовое чтение; поведение на машинах операторов не оценено.
- Выражаемость «`Services` без Qt кроме `gui/`» в sentrux — вывод из README плагина и отсутствия ключей в
  `rules.toml`, не из пробы; ловит ли sentrux внешний `PySide6/*` вообще — не проверено (RED-проба Task 1.0).
- Сведение `target_plugin_index` → имя регистра предполагает, что каталог плагинов процесса однозначно даёт имя
  регистра по индексу; при мульти-плагинном процессе с одинаковыми регистрами — не проверено.
- ADS: лицензия, колёса aarch64, жест drag между окнами — не проверены (CTO проверял отрицательно только по документации).
