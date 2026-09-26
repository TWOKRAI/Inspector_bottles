# Ревью CTO: конструктор интерфейса — слои, эталоны, виджет как единица (2026-09-26)

**Предмет:** `plans/frontend-constructor/constructor-layers.md`, коммит `0c7a460e` (только документы), плюс плашка в
`gui-bootstrap-design.md`, ссылка в `plan.md`, запись памяти и страница-пояснение для владельца.
**Роль:** `cto` (Fable), синхронно, только чтение. Отчёт сохранён лидом без правок по существу.

**Вердикт: ACCEPT WITH CONDITIONS.** Направление принимается; до первой строки кода — условия 1–5 из раздела «Что изменить до кода».

## Баллы по идеям

| # | Идея | Балл | Почему |
|---|---|---|---|
| a | Виджет — единица размещения, окна у оболочки | **8** | Правильный и проверенный шаблон; развёрнутый Р-E — единственное, что в T4.1 вело против него. Сегодня в коде нуля докинга, так что цена реальная, но фундамент T4.1 §6 (разбор `main_window.py` на шелл/прикладное) уже лежит в нужную сторону. Минус два: оболочка должна владеть ещё и замком через N окон и пресетами по ролям, а запись это только называет. |
| b | Контекст виджета — одна дверь; три канала | **7** | Идея верна и дешёвая там, где запись обещает: прямых импортов между пакетами вкладок всего **2** (`services ↔ pipeline`). Дорогая часть не названа: вкладки сегодня получают `RuntimeDeps` = **13 прикладных + 25 полей `FrameworkRuntime`** = 38 зависимостей, а дверь — 4. Веер кадров и блокирующий `subscribe` не оговорены (находка 2). |
| c | Раскладка как данные, пресеты, замок | **8** | Верно. Не решено, что источник правды: YAML-декларация или бинарный `saveState` (проба: 88 байт `QByteArray`, `restoreState` чужого состояния вернул `True` — возвратом валидировать нельзя). Замок обязан переживать восстановление — в приёмку. |
| d | Слои: framework = конструктор / Services = срезы с пакетами / прототип тонкий | **7** | Направление верное и совпадает с gui-service ред. 2. Но «пакет виджетов в Services» упирается в объявленные Qt-free контракты Services (`Services/line_sim/__init__.py:3`, `rules.toml:148-155`) и расходится с `architecture.md:37-38` («пакет живёт при приложении: симулятор — `apps/line_sim`»). Нужна конвенция подпакета и правило (находка 5). |
| e | Эталоны `minimal_app` + `minimal_gui`, рост в 4 шага | **8** | Единственный измеримый критерий во всей записи; `minimal_app` живой (smoke зелёный, `BackendHarness` существует: `backend_ctl/harness.py:313`). «Добавлять, когда тянет» — правильная дисциплина. |
| f | Правило двух потребителей | **7** | Как гейт «когда строить» — верно. Но память владельца `feedback_unused_paths_are_contracts` (07-13: «не используется ≠ не нужно») и rework 4.5 («нет вызывающих ≠ не нужен») говорят про уже существующие пути. Запись должна явно разграничить «строить по двум» и «не резать по нулю», иначе Gen-1 станет прецедентом для ножа. |
| g | Переходный `inspector.classic` | **6** | Разблокирует 1.4, но: (1) целый `MainWindow` — это `QMainWindow` со своим статус-баром, F11, `QSettings("INNOTECH")` внутри дока другого `QMainWindow`; виджетом должна стать центральная часть (header/banner/tab-host), не окно; (2) ему нужны все 38 полей — у контекста появится «легаси-дверь», и без sunset-теста она станет единственной. |
| h | `GuiHostWindow` (T4.6) вперёд, к 1.4 | **6** | Нужен, иначе «окна у оболочки» нечем исполнить. Но T4.1 §6 кладёт его в `frontend_module/windows/` — каталог Gen-1, который rework Ф3 ступень 3.0 **удаляет**; план frontend-constructor (`plan.md:7,105`) всё ещё держит T4.6 в Блоке В за окном codemod; gui-service Task 3.1 строит тот же докинг в `apps/pult/workspace.py`. Три документа против одной строки записи. |
| i | Пульт-программа во фреймворке, `apps/pult` = конфиг | **7** | Это уже утверждённая архитектура gui-service (`architecture.md:24-25`: `apps/pult = GuiBootstrap(fw) + RemoteGuiRuntime(fw) + N × GuiAppSpec`, «~сотня строк»). Слова владельца «Пульт в Services» 09-26 читаются как «Пульт — отдельный сервис» из решения 09-23, а не как путь `Services/pult`. Вопрос не «открыт», а требует одного подтверждения у владельца. |

## Сверка баллов страницы

| Балл лида | CTO | Почему |
|---|---|---|
| Идея 8.5 | **8** | Согласен с −1.5 за «универсальный». Ещё −0.5: веер кадров и вопрос двух форматов раскладки не адресованы. |
| T4.1 vs идея 6 | **6.5** | Рантайм, загрузчик пакетов, стадии, контракт hot-reload и §6 переиспользуются как есть; неверны только Р-E и единица. |
| Готовность кода 4.5 | **4** | Ни одного символа из дизайна в коде: `grep -rnE "^\s*(class\|def)\s+(GuiHostRuntime\|GuiBootstrap\|GuiAppSpec\|WidgetSpec\|WidgetContext\|GuiHostWindow)\b"` → 0; `grep -c "process\._" multiprocess_prototype/frontend/app.py` → **47**; один `_frame_cb` в шине; `PySide6QtAds` не установлен. |
| Поэтапно 8.5 | **7.5** как записано, 8.5 после правки T4.1 | Шаг 1 «T4.2–T4.4 как в дизайне» вшивает один рантайм на процесс (находка 1); шаги 2–3 будут это переписывать. |
| Big-bang 3.5 | **3** | Согласен. |

## Находки (по убыванию)

**1. HIGH — «`GuiHostRuntime` почти без изменений; их может быть N» противоречит T4.1 §4.** Protocol (`gui-bootstrap-design.md:221-238`) — один `command_sender`, один `state_proxy`, один `bus`; `BootContext` (§2) держит один `runtime`. Раскладка записи даёт каждому доку `conn`, виджету — `backend_role`. Значит бутстрап держит реестр рантаймов, а контекст разрешается парой (виджет, подключение) — это правка стадий `runtime`/`state` T4.3–T4.4, а не «добавить позже в Ф3». Записано как факт, фактом не является.

**2. HIGH — веер кадров и блокирующая подписка не оговорены в контракте контекста.** Сегодня: `multiprocess_prototype/frontend/bridge_impl.py:47` — `set_frame_callback` хранит **один** `_frame_cb`; `frontend_module/bridge/remote_frame_source.py:228-240` — `subscribe(senders, on_frame, timeout=5.0)`: «блокирует до ответа хоста», один запрос на вызов. `ctx.frames.subscribe(camera, view.show)` из фабрики каждого виджета = N подписок на хосте и N блокировок GUI-потока при применении раскладки. Страница называет риск («один поток на источник»), запись — нет. В приёмку контекста: «N виджетов на один источник → 1 подписка на хосте (число по `introspect_router_stats`)», подписка не блокирует поток UI.

**3. MEDIUM — gui-service Task 3.1 и запись строят один докинг дважды.** `phase-3-multi-backend.md:9-35`: `apps/pult/workspace.py` — «верхнеуровневый `QMainWindow` с `QDockWidget` на бэкенд», `saveState` в файл рядом с `pult.yaml`. Запись: доки, раскладка и замок — в оболочке фреймворка к 1.4. Таблица «Что меняется в T4.1» это не отмечает; 3.1 надо переписать в «раскладка = данные оболочки; `apps/pult` — только подключения».

**4. MEDIUM — путь `GuiHostWindow` попадает под нож codemod.** T4.1 §6: `frontend_module/windows/host_window.py`. `frontend_module/STATUS.md:33`: `windows/` — «LEGACY, frozen». `framework-architecture-rework/plan.md:361`: ступень 3.0 — «Удалить Gen-1 (Р-6)». Живой файл в удаляемом каталоге, и его нет в списке разреза 2б.2 (`plan.md:262-263` перечисляет только `bootstrap/*`). Плюс `plans/frontend-constructor/plan.md:7,105` по-прежнему держат T4.6 в Блоке В — статус плана отстаёт от решения.

**5. MEDIUM — «пакеты виджетов в Services» vs объявленные контракты Services.** Qt в Services только в автономных инструментах — `grep -rlE "^\s*(from|import)\s+(PySide6|PyQt|qtpy)" Services --include='*.py'` → `Services/robot_comm/server/sim_robot.py`, `Services/robot_comm/server/sim_monitor.py`, `Services/hikvision_camera/sdk_app/main_window.py`. В `Services/line_sim` — **0**, и `Services/line_sim/__init__.py:3`: «Публичный API (numpy/opencv/pydantic/yaml, без torch и PySide6)». `rules.toml:148-155` запрещают `Services/auth → frontend_module` и Qt. `architecture.md:37-38` кладёт пакет симулятора в `apps/line_sim`. Нужны: подпакет `Services/<x>/gui/` (не импортируется корнем пакета), правило `Services/* ↛ PySide6` с исключением `*/gui/*`, и один ответ «пакет при приложении или в Services» в обоих документах. Утверждение лида «Qt в `Services/line_sim`» — неверно (греп лида поймал слово `PySide6` в докстринге).

**6. LOW — числа.** `grep -rlE "^\s*(from|import)\s+.*frontend_module" multiprocess_prototype/frontend --include='*.py' | wc -l` → **89** файлов (строк импорта — 129, верно); **97** — это `grep -rl "frontend_module"` (любое упоминание, включая комментарии). `examples/minimal_app/plugins` — 148 строк всеми файлами, 146 — два `plugin.py`.

**7. LOW — нативные доки: утверждение наполовину.** Проба offscreen (PySide6 6.10.3): после `setFloating(True)` родитель остаётся `A`, `isWindow: True`; `a.removeDockWidget(d); b.addDockWidget(Right, d)` → `parent: B | B area: RightDockWidgetArea | A area: NoDockWidgetArea`. Программный перенос между главными окнами — штатный; нет только drag-and-drop мышью между окнами. Пункт меню «Переместить в окно…» закрывает «быстро раскидывать» без ADS. Context7: привязка `PySide6QtAds` существует (`/mborgerson/pyside6_qtads`, High); в `.venv` не установлена; лицензия и колёса aarch64 не проверены.

**8. LOW — «Пульт» занят четырежды**, не трижды: `apps/line_sim/pipeline.yaml:141` — процесс `pult` (хост `pult_web`). Ссылка `.sentrux/rules.toml:128` в gui-service — на деле `129-131` (дрейф после правок файла).

**9. LOW — `inspector.classic` без sunset.** Назвать легаси-дверь (`ctx.legacy_deps`), тест «`grep -c ctx.legacy` = 1 по прототипу», и виджетом делать центральную часть, не `QMainWindow`.

**10. LOW — hot-reload.** `multiprocess_prototype/frontend/process.py:392` чистит только `multiprocess_prototype.frontend*`. Пакеты в `Services/*/gui` и общие виджеты фреймворка кнопкой «Перезапустить интерфейс» не перезагрузятся; T4.1 §5 говорит это про фреймворк, запись — ни слова про Services. `reload_namespace` должен стать списком от пакетов, или регресс записан.

## Проверенные утверждения записи

| Утверждение | Команда | Результат |
|---|---|---|
| докинга в коде нет | `grep -rnE "QDockWidget\|saveState\|restoreState" … --include='*.py' \| wc -l` | **0 / 0** ✔ |
| 46 594 строк `prototype/frontend` без тестов | `find … -not -path '*/tests/*' \| xargs cat \| wc -l` (и `tokei`, 280 файлов) | **46594** ✔ |
| 13 998 вне `frontend/` | аналогично, `-not -path '*/frontend/*'` | **13998** ✔; разбивка по каталогам точна |
| smoke `minimal_app` | `QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest examples/minimal_app -q --tb=short -p no:cacheprovider` | `1 passed in 2.77s` ✔ |
| `rules.toml:119-122` | `grep -nE '^\[\[boundaries\]\]\|^from\|^to' .sentrux/rules.toml` | `119 / 120 from "examples/*" / 121 to "multiprocess_prototype/*"` ✔ |
| Gen-1 ~1250 строк | чтение `STATUS.md:35` | ~1253 LOC ✔ |
| бэкенд через `app_module`, два хука | `grep -nE "GenericProcessManagerApp\|hook" multiprocess_prototype/orchestrator.py` | ✔ (хуки в `backend/orchestrator_hooks.py`) |
| память dual-write | `diff` двух копий | IDENTICAL ✔ |
| Qt в `Services/{hikvision_camera,robot_comm,line_sim}` | см. находку 5 | hikvision ✔, robot_comm ✔, **line_sim ✘** |

## Что изменить до кода

1. **Редакция T4.1** (обязательна и так: 43 727 байт при лимите 32 КБ): рантайм = подключение, бутстрап держит N; `WidgetContext` с требованиями к вееру кадров и неблокирующей подписке; `inspector.classic` = центральная часть окна + именованная легаси-дверь с sunset-тестом; путь оболочки вне `windows/` (например `frontend_module/host/`) и строка в rework 2б.2; раскладка: YAML декларирует, `saveState`-блоб хранит правки пользователя, оба по `objectName`, замок переживает `restoreState`; `reload_namespace` — список.
2. **Синхронизировать соседей:** `frontend-constructor/plan.md:7,105` (T4.6-минимум выходит из Блока В, к 1.4); gui-service `phase-3` Task 3.1 (докинг → оболочка, `apps/pult` = подключения); `architecture.md:37-38` (одно место пакета); rework 2б.2 (+`host_window`, +контекст).
3. **Правила:** `Services/* ↛ PySide6` кроме `*/gui/*`; `examples/* ↛ Services/*, Plugins/*`.
4. **Один вопрос владельцу** по (i) и развести четыре «Пульта» до кода 1.4.
5. Поправить числа (89 / метод счёта; `line_sim` Qt-free).

## Рекомендуемый порядок

Редакция T4.1 (п. 1–2) → T4.2 характеризация boot-порядка → T4.3/T4.4 с реестром рантаймов (одна реализация, но через реестр) → минимальная оболочка: доки + файл раскладки + замок, путь вне `windows/` → gui-service 1.4 с `inspector.classic` (центральная часть) → `examples/minimal_gui` как приёмка 1.4 со стороны фреймворка → gui-service Ф3 (второй рантайм, пакет симулятора, шина с объявленными событиями) → дробление `classic` по нужде, перенос срезов в Services по инвентарю T3.0.

## Что оставлено открытым и что ненадёжно в оценке

- Лицензия Qt Advanced Docking System и колёса `PySide6QtAds` под PySide6 6.10 / aarch64 — не проверены.
- `restoreState(True)` на чужом состоянии — наблюдён только возврат, не эффект; нативный drag между окнами проверен отрицательно лишь по документации Qt, не жестом.
- Веер кадров не измерен живьём: стенд не поднимался, qt-mcp не подключился; вывод из одного `_frame_cb` и одного запроса на `subscribe`.
- Счёт «2 кросс-импорта между вкладками» — только по путям импорта; связь через `RuntimeDeps`/`QtEventBus` не считалась.
- `phase-1b`, `phase-2` и `frontend-constructor/plan.md` прочитаны грепом, не целиком; слова владельца 09-26 известны только в пересказе записи.
- Все баллы — суждение, не замер. qex не использовался (Ollama выключена); все числа — grep.
