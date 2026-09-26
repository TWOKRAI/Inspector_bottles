# Phase 2 — Инструмент разметки

Часть плана [`plan.md`](plan.md). Цель фазы: человек открывает датасет, листает снимки, размечает рамки и класс
снимка с клавиатуры и мыши, сохраняет без риска затереть чужую правку. Всё — через команды Ф1 и канал «файлы по id».

**Где живёт код:** `Services/dataset/gui/` — подпакет с Qt, корень `Services/dataset` импортирует его **никогда**
(ревью CTO, находка 5). Пакет видит только `AnnotationPorts` (Task 2.1) — подмножество контекста виджета из
`plans/gui-constructor/`. До готовности конструктора порты собирает один адаптер (2.5a), после — контекст (2.5b).

**Канон каждой задачи:** как в Ф1 (`phase-1-dataset-service.md`, шапка). Для Qt-задач tester пишет pytest-qt
(`qt_api = pyside6`, `QT_QPA_PLATFORM=offscreen`); любой тест, который может заблокироваться, — с дедлайном.

## Что уже решено для всей фазы

- **UI-поток не блокируется никогда.** Загрузка миниатюр и полных снимков, команды — асинхронно, результат
  возвращается в UI-поток сигналом. Это то же требование, что ревью CTO поставило подписке кадров (находка 2).
- **Черновик, undo и грязность — в клиенте, сохранение — командой с ревизией** (как черновик рецепта в gui-service
  1b). На бэкенде истории правок нет.
- **Горячие клавиши:** `1`–`9` — класс по `hotkey`; `D`/`→` — следующий, `A`/`←` — предыдущий; `Ctrl+Z` /
  `Ctrl+Shift+Z` — undo/redo; `Del` — удалить выбранную рамку; `C` — копировать рамки с предыдущего; `E` — «объектов
  нет» (labeled, пусто); `S` — пропустить (skipped); `Ctrl+S` — сохранить. Сочетания действуют, только когда фокус в
  пакете разметки (`Qt.WidgetWithChildrenShortcut`), — конфликт с сочетаниями окна проверяет 2.4.

---

### Task 2.1 — Канал «файлы по id»: клиент во фреймворке + `AnnotationPorts`

**Level:** Senior · **Assignee:** teamlead · **Module contract:** new-lite (`frontend_module/bridge/remote_file_source.py`) · **Layer:** framework + services
**Handoff:** `tester`(RED) → `teamlead`(GREEN) → `reviewer`

**Goal:** четвёртый канал контекста виджета (`constructor-layers.md:171`) реализован: виджет получает байты по ссылке
`{provider, name, id, variant}`, не блокируя GUI-поток.

**Канал файлов (согласовано 2026-09-26; одинаковый текст в `gui-constructor/design-connection-context.md` §3.4 и `dataset-annotation/phase-2-annotation-widget.md` Task 2.1).** Ссылка: `ref = {provider, name, id, variant}`, `variant ∈ {"thumb", "full"}`. Два слоя: (1) `RemoteFileSource.fetch(ref) -> tuple[bytes | None, str | None]` — во фреймворке (`frontend_module/bridge/remote_file_source.py`), без Qt, вызывается в потоке пула; (2) `FileChannel.fetch(ref, on_done) -> Cancel` — член контекста виджета `ctx.files`, неблокирующий; `on_done(FileResult(ok, data, mime, error))` вызывается в GUI-потоке; `Cancel` — вызываемое без аргументов. Подключение виджета — поле `ctx.connection: str`, каналы лежат прямо на `ctx`; метода `ctx.connection(name)` нет (это `BootContext`). Заглушка gui-constructor 1.5 возвращает `FileResult(ok=False, data=None, mime=None, error="files channel not implemented")`; реализацию делает dataset-annotation 2.1. Qt-обёртка `qt_files.py` адаптера `AnnotationPorts` уходит вместе с адаптером в sunset 2.5b.

**DESIGN (поверх абзаца выше, не вместо него):**
- Слой 1 — `RemoteFileSource(endpoint_resolver)`: один синхронный `urllib.request`-запрос, таймаут 5 с; второй
  элемент кортежа — текст ошибки (`"connection_refused"`, `"not_found"`, `"timeout"`, …), при успехе `None`.
  `endpoint_resolver` — функция «провайдер → {host, port}»; предметных слов в классе нет (провайдер — строка).
- Слой 2 — реализация `FileChannel`: пул потоков stdlib (`ThreadPoolExecutor`, `max_workers=4`) зовёт слой 1,
  результат переносится в GUI-поток; LRU-кэш **только для `"thumb"`**, потолок по байтам (дефолт 64 МБ); `"full"`
  не кэшируется; повторный `fetch` той же ссылки в полёте — один HTTP-запрос, все `on_done`; `Cancel()` после
  прихода данных — no-op, до — `on_done` не вызывается. `mime` — по сигнатуре байтов (JPEG/PNG), кортеж слоя 1 его не
  несёт. Место класса: там, где gui-constructor 1.5 держит заглушку `FileChannel` (реализация заменяет заглушку);
  если 1.5 ещё не слит — класс живёт в `Services/dataset/gui/qt_files.py` и переезжает в 2.5b.
- `endpoint_resolver` пакета датасета читает `dataset.files.endpoint` через `ctx.state` (подписка).
- `Services/dataset/gui/ports.py` — `AnnotationPorts` (Protocol) — **структурное подмножество `WidgetContext`**
  (`design-connection-context.md` §3), имена один в один: `connection: str`; `state` —
  `subscribe(glob, cb) -> Handle`, `get(path)`; `commands` — `request(target, command, data, timeout) -> Reply(ok,
  data, error)` через `RequestRunner`, результат колбэком (§3.2); `files` — `fetch(ref, on_done) -> Cancel`.
  Настоящий `WidgetContext` удовлетворяет `AnnotationPorts` без адаптера — это проверяется тестом, как только
  Protocol контекста слит (до того — тестом на фейковом контексте с теми же именами).
- Правило `Services ↛ Qt` кроме `*/gui/*` (условие 3 ревью CTO) **владеет gui-constructor Task 1.0** — грепным
  контракт-тестом `Services/tests/test_no_qt_outside_gui.py`, не строкой sentrux (в синтаксисе sentrux исключений
  нет). Здесь — только проверка, что тест есть и краснеет на пробе.

**FILES:** 1) `multiprocess_framework/modules/frontend_module/bridge/remote_file_source.py` 2) `…/frontend_module/bridge/README.md`
3) файл реализации `FileChannel` (место заглушки gui-constructor 1.5) **или** `Services/dataset/gui/qt_files.py`, если
1.5 не слит 4) `Services/dataset/gui/__init__.py` + `ports.py` 5) `multiprocess_framework/modules/frontend_module/STATUS.md`
6) тесты.

**Acceptance criteria:**
- [ ] Против живого `files_server` Task 1.3 (in-process, `port=0`): `RemoteFileSource.fetch({… "variant": "full"})`
      → `(байты, None)`, байты побайтно равны файлу.
- [ ] Сервер с искусственной задержкой 2 с: `FileChannel.fetch` возвращается < 5 мс (литерал); `on_done` приходит
      после задержки **в GUI-потоке** (`QThread.currentThread() is app.thread()` внутри колбэка); pytest-qt: за время
      ожидания UI-цикл обрабатывает таймер (≥ 10 тиков по 50 мс).
- [ ] 10 одновременных `fetch` одной ссылки `"thumb"` → на сервере 1 запрос (счётчик сервера), 10 `on_done`.
- [ ] `Cancel()` до ответа → `on_done` не вызван за 3 с.
- [ ] Недоступный сервер → `on_done(FileResult(ok=False, data=None, mime=None, error="connection_refused"))` ≤ 6 с,
      исключение наружу не летит.
- [ ] Кэш: 100 миниатюр по 1 МБ при потолке 64 МБ → кэш ≤ 64 МБ; повторный `fetch` недавней — без HTTP.
- [ ] `grep -rn "dataset" multiprocess_framework/modules/frontend_module/bridge/remote_file_source.py` → 0;
      `sentrux check .` зелёный.
- [ ] `Services/tests/test_no_qt_outside_gui.py` (gui-constructor 1.0) существует; проба — временный
      `import PySide6` в `Services/dataset/store.py` → тест красный; тот же импорт в `Services/dataset/gui/` → зелёный.

**Инъекции:** `fetch` слоя 2 синхронный → тест «< 5 мс» и тест тиков; `on_done` из потока пула без переноса → тест
«в GUI-потоке»; убрать слияние запросов в полёте → тест «1 запрос»; `Cancel` не снимает колбэк → тест отмены; кэш
без потолка → тест 64 МБ.

**Out of scope:** токен/TLS (gui-service 2.2); загрузка на сервер; кэш на диске клиента.
**Dependencies:** 1.3; место класса слоя 2 — от статуса gui-constructor 1.5 (см. DESIGN).

---

### Task 2.2 — Модель документа разметки без Qt

**Level:** Middle+ · **Assignee:** developer · **Module contract:** new-lite (`Services/dataset/annotation_doc.py`) · **Layer:** services
**Handoff:** `tester`(RED) → `developer`(GREEN) → `reviewer`

**Goal:** вся логика правки — вне Qt, покрыта тестами без виджета; холст (2.4) только рисует и переводит жесты в
вызовы модели.

**DESIGN:**
- `AnnotationDoc(image_id, rev, boxes, image_class_id, status)`: `add_box`, `move_box`, `resize_box`, `set_box_class`,
  `delete_box`, `set_image_class`, `set_status`, `paste_boxes(from_doc)`; каждая операция — команда с `undo()`
  (стек undo/redo в памяти, как решено аудитом `docs/audits/2026-06-18_command-undo-system.md` §4); `dirty` —
  «отличается от сохранённого», а не «была операция» (undo до сохранённого → `dirty=False`).
- Координаты — доли [0, 1]; рамка обрезается по краю снимка; рамка меньше 2×2 пикселей снимка не создаётся (порог —
  аргумент, дефолт 2 px) — случайный клик не плодит мусор.
- `to_save_args()` → аргументы `dataset_save_labels`; `apply_saved(rev)` сбрасывает `dirty`; `on_conflict(server_rev)`
  → состояние `conflict` (правки не теряются, решение — у UI 2.4).
- `paste_boxes` — копия рамок предыдущего снимка одной операцией undo.

**FILES:** 1) `Services/dataset/annotation_doc.py` 2) `Services/dataset/README.md`.

**Acceptance criteria:**
- [ ] `add_box` → `undo` → `redo` → рамка на месте, `dirty` = True; `undo` до исходного → `dirty == False`.
- [ ] Рамка, выходящая за край (`cx=0.95, w=0.2`), после `add_box` лежит в [0, 1] целиком.
- [ ] Рамка 1×1 px на снимке 1000×1000 → не добавлена, стек undo не изменился.
- [ ] `paste_boxes` трёх рамок → один `undo` снимает все три.
- [ ] `to_save_args()` после `set_status("labeled")` без рамок → `boxes == []`, `status == "labeled"`.
- [ ] `on_conflict(5)` → `state == "conflict"`, рамки и стек undo не изменились.

**Инъекции:** `dirty` как флаг «была операция» → тест «undo до исходного»; `paste_boxes` тремя операциями → тест
«один undo»; убрать обрезку по краю → тест края.

**Out of scope:** отрисовка, клавиши (2.4); полигоны.
**Dependencies:** 1.2 (формат меток и классов).

---

### Task 2.3 — Браузер снимков

**Level:** Middle · **Assignee:** developer · **Module contract:** impl-only · **Layer:** services
**Handoff:** `tester`(RED) → `developer`(GREEN) → `reviewer`

**Goal:** сетка миниатюр с фильтрами и страницами; выбор снимка открывает его на холсте (сигнал, не прямой вызов).

**DESIGN:**
- `Services/dataset/gui/browser.py`: `QListView` в режиме `IconMode` + своя модель, страница = `dataset_list` ≤ 200
  (Task 1.2); миниатюры — `ports.files` по мере прокрутки (видимые строки), до прихода — заглушка.
- Фильтры: статус (все / не размечено / размечено / проверено / пропущено), класс, источник (`import/capture/reject/
  synthetic/archive`), «есть рамки». Смена фильтра сбрасывает страницу.
- Подпись миниатюры: значок статуса + число рамок. Обновление при сохранении — по ответу команды, без перезагрузки
  страницы.
- Сигнал `image_selected(image_id)`; порядок навигации «следующий/предыдущий» (2.4) берётся отсюда — одна модель
  порядка на пакет.

**FILES:** 1) `Services/dataset/gui/browser.py` 2) `Services/dataset/gui/browser_model.py` 3) `Services/dataset/gui/__init__.py`.

**Acceptance criteria (pytest-qt, фейковые порты + один тест на настоящих портах с `BackendHarness`):**
- [ ] 450 снимков: первая страница запрашивает `limit=200`; прокрутка до конца — вторая; всего 3 запроса на все 450.
- [ ] Видно 20 ячеек → запрошено ≤ 40 миниатюр (литерал; не все 200 страницы).
- [ ] Фильтр «не размечено» → запрос с `filter.status == "unlabeled"`, страница с 0.
- [ ] После сохранения снимка его значок меняется без нового `dataset_list`.
- [ ] Тест на настоящих объектах: `BackendHarness` + `files_server` + `RemoteFileSource` → в ячейке реальная миниатюра
      (не заглушка) ≤ 3 с (правило «тест на фейках доказывает фейк», `.claude/CLAUDE.md`).

**Инъекции:** запрашивать миниатюры всей страницы → тест «≤ 40»; сброс страницы убрать → тест фильтра.
**Out of scope:** массовые операции над выделением (после 4.2 по нужде).
**Dependencies:** 2.1.

---

### Task 2.4 — Холст и рабочий цикл

**Level:** Senior · **Assignee:** teamlead · **Module contract:** impl-only · **Layer:** services
**Handoff:** `tester`(RED) → `teamlead`(GREEN) → `reviewer`

**Goal:** быстрый цикл «снимок → рамки → следующий» с клавиатуры; сохранение без потерь и без молчаливого затирания.

**DESIGN:**
- `Services/dataset/gui/canvas.py`: `QGraphicsView` + `QGraphicsScene`; колесо — зум к курсору, средняя кнопка /
  пробел + перетаскивание — пан; «вписать» по `F`. Рамка — элемент сцены с 8 ручками; рисование — перетаскивание по
  пустому месту текущим классом. Всё меняется только через `AnnotationDoc` (2.2).
- `Services/dataset/gui/workbench.py`: браузер + холст + список классов (цвет, клавиша, число рамок на снимке) +
  класс снимка + строка статуса. Переход на другой снимок при `dirty` → автосохранение; ответ `conflict` →
  диалог «На сервере новая версия (rev N): оставить свою / взять серверную / сравнить» — «оставить свою» =
  повторное сохранение с `base_rev = N`, **явным** действием человека.
- Полный снимок — `ports.files` `full`; до прихода — растянутая миниатюра; предзагрузка следующего снимка.
- Ошибки команды (`invalid_labels`, недоступный бэкенд) — в строке статуса, правки остаются в документе.

**FILES:** 1) `Services/dataset/gui/canvas.py` 2) `Services/dataset/gui/box_item.py` 3) `Services/dataset/gui/workbench.py`
4) `Services/dataset/gui/class_list.py` 5) `Services/dataset/gui/conflict_dialog.py`.

**Acceptance criteria (pytest-qt):**
- [ ] Сценарий клавиатурой: `2` → перетаскивание мышью (`qtbot.mousePress/Move/Release`) → `D` → на бэкенд ушла
      одна `dataset_save_labels` с одной рамкой класса `hotkey=2`, открыт следующий снимок.
- [ ] `C` на новом снимке → рамки предыдущего; `Ctrl+Z` → рамок нет.
- [ ] Два клиента на одном снимке: A сохраняет, B сохраняет со старой ревизией → у B диалог конфликта, рамки B не
      потеряны; B «взять серверную» → на холсте рамки A. До явного выбора B на бэкенде ровно одно успешное
      сохранение — от A (молчаливого сохранения B нет).
- [ ] Бэкенд недоступен при `D` → переход не выполнен, строка статуса с ошибкой, `dirty == True`.
- [ ] Клавиша `1` при фокусе в другом виджете окна (не в пакете) класс не меняет.
- [ ] Зум колесом 10 шагов и обратно → масштаб вернулся к исходному (±1 %), рамки в координатах снимка не сдвинулись.

**Инъекции:** автосохранение с `base_rev` сервера вместо своего → тест двух клиентов (затирание станет молчаливым);
переход без ожидания ответа сохранения → тест «бэкенд недоступен»; сочетания с `Qt.ApplicationShortcut` → тест фокуса.

**Out of scope:** режим проверки (4.2), подсказки (Ф5), полигоны.
**Dependencies:** 2.2, 2.3.

---

### Task 2.5 — Встраивание: адаптер сейчас, `WidgetSpec` после конструктора

**Level:** Middle · **Assignee:** developer · **Module contract:** impl-only · **Layer:** prototype + services
**Handoff:** `tester`(RED) → `developer`(GREEN) → `reviewer`

**Канон (не пропускается).** Механизма в задаче нет — это проводка, — но независимый `tester` всё равно идёт первым,
в worktree на пред-коммите, по приёмке ниже (правило «тестер на каждой задаче», `.claude/CLAUDE.md`, решение
владельца 2026-08-13). Его ценность здесь — тест «на настоящих объектах» (адаптер собран из реальных портов, не из
фейков) и sunset-тест 2.5b, которые автор проводки склонен написать под свою модель. Инъекции лида: адаптер отдаёт
фейковые `files` → тест на живом бэкенде красный; оставить `dataset_section.py` в 2.5b → sunset-тест красный.

**2.5a — секция в текущем GUI.** Один файл `multiprocess_prototype/frontend/widgets/tabs/services/neural/dataset_section.py`
с функцией `build_annotation_ports(...)` собирает объект, удовлетворяющий `AnnotationPorts` (поля `connection`,
`state`, `commands`, `files` — имена `WidgetContext`), из того, что есть сегодня (отправитель команд, подписка на
состояние, `FileChannel` из Task 2.1 через `qt_files.py`), и регистрирует секцию «Разметка датасета» в
`neural/__init__.py`. `frontend/app.py` **не трогать** (очередь одного писателя с gui-service 1b.2b и T4.2–T4.4).
Приёмка: в собранном GUI на живом бэкенде — импорт через `backend_ctl`, разметка трёх снимков в секции, `dataset_get`
через `backend_ctl` видит рамки; скриншот offscreen в отчёт. `grep -rln "build_annotation_ports(" multiprocess_prototype
--include='*.py'` без `tests/` → ровно 1 файл.

**2.5b — после gui-constructor Ф1.** `Services/dataset/gui/widgets.py` объявляет `WidgetSpec` (`dataset.browser`,
`dataset.workbench`, `dataset.stats` после 4.1); фабрика передаёт пакету сам `ctx` (он удовлетворяет `AnnotationPorts`;
подключение — поле `ctx.connection: str`). Удаляются `dataset_section.py` и `Services/dataset/gui/qt_files.py`
(sunset по согласованному абзацу канала файлов, Task 2.1); реализация `FileChannel` к этому моменту — на месте
заглушки gui-constructor 1.5. Sunset-тест: `grep -rn "dataset_section\|build_annotation_ports" multiprocess_prototype`
→ 0 и `test -e Services/dataset/gui/qt_files.py` → ложь. Поведение приёмки 2.5a повторяется в `apps/gui_client` на
localhost (если gui-service 1.4 к тому времени сделан — иначе только встроенный GUI, и это сказать).

**FILES (2.5a):** 1) `…/neural/dataset_section.py` 2) `…/neural/__init__.py` 3) `…/neural/tests/test_dataset_section.py`.
**FILES (2.5b):** 1) `Services/dataset/gui/widgets.py` 2) удаление `dataset_section.py` 3) удаление
`Services/dataset/gui/qt_files.py` 4) `…/neural/__init__.py` 5) тест.
**Dependencies:** 2.5a — 2.4; 2.5b — `plans/gui-constructor/` Ф1 (контекст виджета, реализация `FileChannel` на месте
заглушки 1.5).
