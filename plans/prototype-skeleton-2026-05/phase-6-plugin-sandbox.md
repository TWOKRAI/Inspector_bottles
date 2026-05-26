# Phase 6 — Sandbox-тест плагина в PluginManagerTab

> **Master plan**: [plan.md](plan.md)
> **Branch**: `feat/plugin-sandbox`
> **Дней**: 2-3
> **Зависимости**: Phase 3 (для webcam snapshot)
> **Refs trailer**: `Refs: plans/prototype-skeleton-2026-05/phase-6-plugin-sandbox.md, plans/prototype-skeleton-2026-05/plan.md`

## Цель

На карточке плагина — кнопка «Тест», открывает мини-панель: вход (файл-изображение или snapshot активного webcam-сервиса) → параметры → «Применить» → preview результата.

## Реюз готового

- `PluginConfigPanel` — редактирование конфига плагина.
- `SubPluginContext` из process_module — изолированный контекст (но с ограничениями — см. ниже).
- `RegistersManager` для валидации параметров.

## Новое

- `multiprocess_prototype/frontend/widgets/tabs/plugins/sandbox.py` — `PluginSandboxWidget`:
  - QFileDialog для изображения **или** snapshot текущего webcam-кадра (через `ServiceRegistry.get("webcam_camera").get_current_frame()`, если сервис RUNNING).
  - Создаёт `SubPluginContext` с mock-`RegistersManager` (для плагинов, которые читают регистры).
  - Вызывает `plugin.process(frame, metadata)` в QThread.
  - Показывает before/after side-by-side через QLabel или существующий `ImagePanelWidget`.
- На карточке плагина кнопка «Тест» открывает sandbox в правой панели.

## Ограничения (явно зафиксировать)

- Sandbox только для **stateless single-frame** плагинов категории `processing` / `render` (gray, color_mask, negative, flip, resize, blur).
- Для `sources` (camera, capture) — кнопка disabled с тултипом «используйте превью сервиса в ServicesTab».
- Для `runtime` (chain_executor, worker_pool) — disabled.
- Для multi-input плагинов (stitcher — собирает несколько регионов) — disabled с пометкой «требует pipeline-контекст».

## Acceptance

- Выбрали `color_mask`, загрузили jpg, покрутили H/S/V → preview обновился.
- Выбрали `stitcher` — кнопка disabled с понятной причиной.
- 10-15 unit-тестов.

---

## Декомпозиция (Tasks)

### Task 6.1 — SandboxPresenter: классификатор плагинов + контракт процессора

**Level:** Middle (Sonnet, normal thinking)
**Assignee:** developer
**Goal:** реализовать `SandboxPresenter` — pure-Python presenter с логикой определения sandbox-совместимости плагина и выполнением `plugin.process()` на одном кадре.
**Context:** Это ядро sandbox-функциональности без GUI. Presenter изолирован от Qt и тестируется без `qtbot`. Классификатор определяет по атрибутам plugin entry (category, кол-во inputs, наличие expected_regions в config), может ли плагин работать в sandbox. Именно здесь живёт логика «disabled с причиной». Все остальные задачи зависят от этого presenter.

**Files:**
- `multiprocess_prototype/frontend/widgets/tabs/plugins/sandbox_presenter.py` — создать
- `multiprocess_prototype/frontend/widgets/tabs/plugins/tests/test_sandbox_presenter.py` — создать

**Steps:**
1. Определить `SandboxCompatibility` — dataclass или TypedDict: `{"ok": bool, "reason": str}`. Reason — русская строка для tooltip (например: «источник — используйте превью сервиса», «требует pipeline-контекст»).
2. Реализовать `SandboxPresenter.__init__(ctx: AppContext)`.
3. Реализовать `SandboxPresenter.check_compatibility(plugin_name: str) -> SandboxCompatibility`:
   - Запросить entry из `ctx.plugin_registry().get(plugin_name)`.
   - `category == "source"` → `ok=False, reason="источник данных — используйте превью сервиса в ServicesTab"`.
   - `category in ("runtime", "control")` → `ok=False, reason="требует pipeline-контекст"`.
   - Плагин имеет `len(inputs) > 1` (multi-input) → `ok=False, reason="требует несколько входных потоков (pipeline-контекст)"`. Stitcher попадает сюда через: его `inputs` имеет один элемент, но семантика N:1 — проверять по атрибуту `name == "stitcher"` или наличию `expected_regions` в `config_class`. **Реши через атрибут класса `multi_input: ClassVar[bool] = False`** — если атрибута нет, считать False. Для stitcher достаточно проверять имя `"stitcher"` как hardcode-исключение (задокументировать TODO для будущего атрибута).
   - Иначе → `ok=True, reason=""`.
4. Реализовать `SandboxPresenter.run_once(plugin_name: str, frame: np.ndarray, config_overrides: dict) -> np.ndarray | None`:
   - Получить plugin class из registry (через `entry.plugin_class` или import).
   - Инстанцировать плагин. Создать `SubPluginContext(config=config_overrides, process_name="sandbox")`.
   - Вызвать `plugin.configure(ctx)` затем `plugin.process([{"frame": frame}])`.
   - Извлечь `result[0]["frame"]` если result непустой, иначе вернуть None.
   - Исключения поймать и вернуть None (логировать через `ctx.log_warning` или print).
5. Написать тесты (без qtbot):
   - `test_check_source_disabled` — capture → ok=False.
   - `test_check_stitcher_disabled` — stitcher → ok=False.
   - `test_check_grayscale_ok` — grayscale → ok=True.
   - `test_run_once_grayscale` — передать реальный numpy array 10×10 BGR, получить не-None результат.
   - `test_run_once_no_registry` — ctx без registry → check_compatibility не падает, возвращает ok=False.

**Acceptance criteria:**
- [x] `pytest multiprocess_prototype/frontend/widgets/tabs/plugins/tests/test_sandbox_presenter.py` — 5+ тестов зелёные (11 passed, 9e8c95e6).
- [x] `SandboxPresenter` не импортирует ничего из PySide6.
- [x] `run_once` не поднимает исключений при любом входе (graceful degradation).

**Out of scope:** webcam snapshot, QThread, GUI виджеты, blur-плагин (его нет в репо, проверялось).
**Edge cases:** entry есть в registry, но plugin_class не импортируется → `run_once` возвращает None без краша.
**Dependencies:** нет (первая задача).
**Module contract:** new-lite

---

### Task 6.2 — PluginSandboxWidget: вертикальный срез (загрузка файла → preview)

**Level:** Middle+ (Sonnet, extended thinking)
**Assignee:** developer
**Goal:** создать `PluginSandboxWidget` — QWidget с полным E2E-сценарием: выбор файла-изображения → «Применить» → before/after preview — в одном тонком vertical slice без webcam и параметров.
**Context:** Это tracer bullet через все слои GUI sandbox. После этой задачи можно показать живой результат. Webcam и параметры конфига добавляются в 6.3. MVP-паттерн обязателен: `ISandboxView` (Protocol) + `PluginSandboxWidget` (реализует Protocol) — presenter инжектируется снаружи.

**Files:**
- `multiprocess_prototype/frontend/widgets/tabs/plugins/sandbox.py` — создать
- `multiprocess_prototype/frontend/widgets/tabs/plugins/tests/test_sandbox_widget.py` — создать

**Steps:**
1. Объявить Protocol `ISandboxView` в начале `sandbox.py`:
   ```python
   class ISandboxView(Protocol):
       def show_result(self, before: np.ndarray, after: np.ndarray | None) -> None: ...
       def show_error(self, msg: str) -> None: ...
       def set_running(self, is_running: bool) -> None: ...
   ```
2. Создать `PluginSandboxWidget(QWidget)`:
   - Конструктор принимает `presenter: SandboxPresenter`, `plugin_name: str`, `parent: QWidget | None`.
   - Внутри: `QVBoxLayout` с тремя зонами:
     - **Зона источника** (input_zone): `QPushButton("Выбрать файл…")` + `QLabel` с именем файла (начально: «файл не выбран»).
     - **Зона действия**: `QPushButton("Применить")` (disabled пока нет кадра).
     - **Зона preview**: два `QLabel` рядом (`before_label`, `after_label`) в `QHBoxLayout`, каждый фиксированной высоты 200px с `setScaledContents(True)`.
3. Слот `_on_file_selected()`: открыть `QFileDialog.getOpenFileName` с фильтром `"Images (*.png *.jpg *.jpeg *.bmp)"`, прочитать через `cv2.imread`, сохранить в `self._current_frame`. Если файл не читается — вызвать `show_error`. Показать before-preview. Активировать кнопку «Применить».
4. Слот `_on_apply_clicked()`: вызвать `SandboxPresenter.run_once(plugin_name, frame, {})` **синхронно** (QThread добавляется в Task 6.3 как расширение). Вызвать `show_result(before, after)`.
5. Реализовать `show_result`: конвертировать BGR numpy → QPixmap через `QImage.fromData` или `cv2.imencode` + `QImage`. Отобразить в `before_label` / `after_label`.
6. Реализовать `show_error(msg)`: показать msg в `QLabel` красного цвета над preview-зоной.
7. Реализовать `set_running(is_running)`: disable/enable кнопку «Применить», менять текст «Применяется…» / «Применить».
8. Тесты (`qtbot`):
   - `test_widget_creates_for_compatible_plugin` — для grayscale виджет создаётся без исключений.
   - `test_apply_button_disabled_initially` — кнопка «Применить» disabled при старте.
   - `test_show_result_displays_pixmaps` — вызвать `show_result` с двумя numpy-кадрами 10×10, проверить что `after_label.pixmap()` не None.
   - `test_show_error_shows_label` — после `show_error("bad")` — error label видим.

**Acceptance criteria:**
- [ ] `pytest .../test_sandbox_widget.py` — 4+ тестов зелёные.
- [ ] Кнопка «Применить» disabled пока `_current_frame is None`.
- [ ] `show_result` не роняет исключений при `after=None` (показывает only before).
- [ ] E2E: выбрать jpg из тест-фикстуры → нажать «Применить» для grayscale → `after_label.pixmap()` не None (проверяется в тесте через mock `QFileDialog`).

**Out of scope:** QThread (синхронный apply — ок для MVP), webcam snapshot, параметры конфига, кнопка disabled для несовместимых плагинов.
**Edge cases:** `cv2.imread` вернул None (файл повреждён) → show_error. `run_once` вернул None (плагин не дал output) → `after_label` остаётся пустым, сообщение «нет результата».
**Dependencies:** Task 6.1.
**Module contract:** new-lite

---

### Task 6.3 — Webcam snapshot + параметры конфига + QThread

**Level:** Middle+ (Sonnet, extended thinking)
**Assignee:** developer
**Goal:** расширить `PluginSandboxWidget` поддержкой webcam snapshot и редактируемыми параметрами конфига плагина, перенести `run_once` в `QThread`.
**Context:** WebcamCameraService сейчас — shell без реального `get_current_frame()`. Нужно добавить этот метод в сервис с условием «если cv2.VideoCapture открыта → grab; иначе вернуть None». Параметры конфига (для color_mask это H/S/V диапазоны) берутся из `register_class.model_fields` плагина и рендерятся как `QSpinBox`-ы. QThread нужен чтобы не замораживать GUI при тяжёлых плагинах.

**Files:**
- `Services/webcam_camera/service.py` — добавить `get_current_frame() -> np.ndarray | None`
- `multiprocess_prototype/frontend/widgets/tabs/plugins/sandbox.py` — расширить
- `multiprocess_prototype/frontend/widgets/tabs/plugins/tests/test_sandbox_widget.py` — расширить тесты

**Steps:**
1. В `WebcamCameraService`:
   - Добавить `_cap: cv2.VideoCapture | None = None`.
   - В `start()`: если config содержит `device_id` — открыть `cv2.VideoCapture(device_id)`.
   - В `stop()`: освободить `_cap.release()` если открыта.
   - Добавить `get_current_frame() -> np.ndarray | None`: если `_cap` открыта и `_cap.isOpened()` — вызвать `_cap.read()`, вернуть кадр или None при ошибке. Если сервис stopped или cap=None → вернуть None.
2. В `PluginSandboxWidget`:
   - Добавить кнопку «Снимок с камеры» рядом с «Выбрать файл». Disabled если webcam_camera service не running.
   - Слот `_on_webcam_snapshot()`: получить сервис через `ctx.service_registry().get("webcam_camera")`, вызвать `get_current_frame()`. Если None — `show_error("Камера недоступна")`. Иначе — сохранить кадр и показать before-preview (тот же путь что при file load).
   - Добавить `_params_widget: QWidget` — зона параметров между источником и кнопкой «Применить»: динамически строит `QSpinBox` (или `QDoubleSpinBox`) для каждого поля `register_class` если плагин имеет `register_class`. Подпись берётся из `FieldMeta.label`. Диапазон из `FieldMeta.min/max`. Значения по умолчанию из `register_class()` (инстанс с дефолтами). Результат — словарь `config_overrides` для передачи в `run_once`.
   - Перенести вызов `run_once` в `QRunnable` / `QThread`: в слоте `_on_apply_clicked` — `set_running(True)`, запустить worker. По завершении (через `pyqtSignal` / `Signal`) — `set_running(False)`, `show_result`.
3. Расширить тесты:
   - `test_webcam_button_disabled_when_service_stopped` — mock ctx с stopped webcam → кнопка disabled.
   - `test_params_widget_builds_for_color_mask` — sandbox для color_mask → виджет содержит >= 6 спинбоксов (h_min, h_max, s_min, s_max, v_min, v_max).
   - `test_params_widget_empty_for_grayscale` — grayscale нет register_class → params_widget пуст или скрыт.

**Acceptance criteria:**
- [ ] `WebcamCameraService.get_current_frame()` возвращает None если status != "running".
- [ ] `test_sandbox_widget.py` — все 7+ тестов зелёные.
- [ ] Кнопка «Применить» не блокирует UI при `time.sleep(0.1)` в mock run_once (проверяется через `QApplication.processEvents()` в тесте).
- [ ] Параметры color_mask (h_min … v_max) отображаются как спинбоксы с правильными min/max.

**Out of scope:** сохранение результата в файл, история предыдущих запусков, blur-плагин (не в репо).
**Edge cases:** `get_current_frame()` вызван при `_cap is None` — не падает, возвращает None. Плагин без `register_class` (grayscale, flip) → params_widget скрыт, `config_overrides = {}`.
**Dependencies:** Task 6.2.
**Module contract:** impl-only (WebcamCameraService), new-lite (sandbox.py расширение)

---

### Task 6.4 — Интеграция кнопки «Тест» в _sections.py + disabled для несовместимых

**Level:** Middle (Sonnet, normal thinking)
**Assignee:** developer
**Goal:** добавить кнопку «Тест» в карточку каждого плагина (`_PluginSection`), которая открывает `PluginSandboxWidget` в content-панели; для несовместимых плагинов кнопка disabled с tooltip.
**Context:** `_PluginSection.action_buttons()` сейчас возвращает `[]`. Нужно добавить QPushButton «Тест» — он появится в action-колонке таба (через `DiffScrollTabLayout`). Когда плагин совместим — клик заменяет content на sandbox widget (новая страница в `content_stack`). Когда несовместим — tooltip объясняет причину.

**Files:**
- `multiprocess_prototype/frontend/widgets/tabs/plugins/_sections.py` — изменить `_PluginSection`
- `multiprocess_prototype/frontend/widgets/tabs/plugins/tab.py` — добавить метод `show_sandbox(plugin_name)`
- `multiprocess_prototype/frontend/widgets/tabs/plugins/tests/test_sandbox_integration.py` — создать

**Steps:**
1. В `_PluginSection.__init__` добавить `self._sandbox_widget: QWidget | None = None`.
2. В `_PluginSection.action_buttons()` создать `QPushButton("Тест")`:
   - Запросить `SandboxPresenter(ctx).check_compatibility(plugin_name)`.
   - Если `ok=False`: `btn.setEnabled(False)`, `btn.setToolTip(reason)`.
   - Если `ok=True`: подключить `btn.clicked.connect(self._on_test_clicked)`.
   - Вернуть `[btn]`.
3. Реализовать `_PluginSection._on_test_clicked()`:
   - Если `_sandbox_widget is None`: создать `PluginSandboxWidget(SandboxPresenter(ctx), plugin_name)`, добавить в `content_stack` через колбэк в tab (передать через конструктор или signal).
   - Переключить `content_stack` на страницу sandbox widget.
4. В `PluginsTab` добавить метод `open_sandbox(plugin_name: str, sandbox_widget: QWidget) -> None`:
   - Добавить `sandbox_widget` в `content_stack` (если ещё нет).
   - `content_stack.setCurrentWidget(sandbox_widget)`.
   - `_PluginSection` вызывает этот метод через weak ref на tab или через callback, переданный в `__init__`.
   - **Выбери паттерн callback**: передать `open_sandbox_callback: Callable[[str, QWidget], None]` в `_PluginSection.__init__`. `_sections.py` получает этот callback от tab'а через `build_plugin_sections(ctx, open_sandbox_cb)`.
5. Тесты (qtbot):
   - `test_test_button_disabled_for_source` — для capture кнопка disabled с непустым tooltip.
   - `test_test_button_enabled_for_grayscale` — для grayscale кнопка enabled.
   - `test_test_button_disabled_for_stitcher` — для stitcher кнопка disabled.
   - `test_open_sandbox_switches_content` — клик по кнопке «Тест» для grayscale → `content_stack.currentWidget()` является `PluginSandboxWidget`.

**Acceptance criteria:**
- [ ] `pytest .../test_sandbox_integration.py` — 4+ тестов зелёные.
- [ ] `build_plugin_sections` сигнатура совместима с существующим вызовом в `tab.py` (обратная совместимость через default `open_sandbox_cb=None`).
- [ ] Для source/stitcher/runtime — tooltip непустой, понятная по-русски причина.
- [ ] После клика «Тест» — `PluginSandboxWidget` создаётся ровно один раз (singleton per plugin).

**Out of scope:** анимация перехода, история sandbox-сессий, кнопка «Закрыть sandbox» (content переключается обратно через обычный клик в дереве).
**Edge cases:** `build_plugin_sections` вызывается повторно через `refresh_catalog()` — callback должен сохраняться (передаётся из tab'а, не пересоздаётся).
**Dependencies:** Task 6.1, Task 6.2.
**Module contract:** public-api-change (`build_plugin_sections` получает новый аргумент)

---

### Task 6.5 — Финальные тесты + smoke-проверка

**Level:** Middle (Sonnet, normal thinking)
**Assignee:** tester
**Goal:** написать итоговые интеграционные тесты sandbox-сценария end-to-end и убедиться, что gate `make check` + `make test` проходит на ветке `feat/plugin-sandbox`.
**Context:** Отдельная задача тестировщика чтобы не смешивать реализацию с верификацией. Тестируются сценарии из раздела Acceptance плана: color_mask E2E + stitcher disabled.

**Files:**
- `multiprocess_prototype/frontend/widgets/tabs/plugins/tests/test_sandbox_e2e.py` — создать
- _(не изменять реализационные файлы)_

**Steps:**
1. Подготовить pytest-фикстуру `minimal_bgr_frame` — `np.zeros((50, 50, 3), dtype=np.uint8)` с заполненными пикселями (не всё чёрное, чтобы проверить трансформацию).
2. Тест `test_color_mask_full_pipeline`:
   - Создать `SandboxPresenter` с mock ctx (color_mask совместим).
   - Вызвать `run_once("color_mask", frame, {"h_min": 0, "h_max": 179, "s_min": 0, "s_max": 255, "v_min": 0, "v_max": 255})`.
   - Проверить что результат — numpy array той же формы (H, W, 3).
3. Тест `test_grayscale_full_pipeline`:
   - `run_once("grayscale", frame, {})` → результат не None, shape == frame.shape.
4. Тест `test_stitcher_is_disabled_in_ui` (qtbot):
   - Создать `PluginsTab` с mock registry включая stitcher.
   - Выбрать stitcher в дереве.
   - Найти кнопку «Тест» в action-колонке.
   - Assert `not btn.isEnabled()`.
5. Тест `test_sandbox_widget_apply_grayscale` (qtbot):
   - Создать `PluginSandboxWidget(presenter, "grayscale")`.
   - Напрямую установить `widget._current_frame = minimal_bgr_frame`.
   - Активировать кнопку «Применить» и вызвать слот.
   - Assert `widget.after_label.pixmap() is not None`.
6. Тест `test_sandbox_no_crash_on_bad_file` (qtbot):
   - `widget.show_error("тест")` → не падает, label видим.
7. Запустить `make gate` (или `pytest --tb=short`) в конце задачи.

**Acceptance criteria:**
- [ ] Все 6 тестов в `test_sandbox_e2e.py` зелёные.
- [ ] `make check` (ruff + pyright + bandit) — без новых ошибок.
- [ ] Итого по всем файлам sandbox: ≥ 15 тестов (6.1: 5, 6.2: 4, 6.3: 3, 6.4: 4, 6.5: 6 → 22).

**Out of scope:** тестирование webcam с реальной камерой (mock), тестирование QThread timing.
**Edge cases:** color_mask с `h_max < h_min` → результат может быть чёрной маской, не crash.
**Dependencies:** Task 6.1, 6.2, 6.3, 6.4 (все реализованы).
**Module contract:** n/a

---

## Порядок выполнения

```
6.1 (SandboxPresenter)
  → 6.2 (Widget vertical slice)
      → 6.3 (Webcam + params + QThread)
  → 6.4 (Кнопка «Тест» + интеграция)
      → 6.5 (E2E тесты + gate)
```

6.3 и 6.4 можно вести параллельно после 6.2.

## Оценка трудозатрат

| Task | Сложность | Часов |
|------|-----------|-------|
| 6.1 | Middle | 2-3 ч |
| 6.2 | Middle+ | 3-4 ч |
| 6.3 | Middle+ | 4-5 ч |
| 6.4 | Middle | 3-4 ч |
| 6.5 | Middle (tester) | 2-3 ч |
| **Итого** | | **14-19 ч** |

> 2-3 рабочих дня при одном разработчике, соответствует оценке из шапки плана.

## Опасные места

1. **WebcamCameraService — shell без реального бэкенда.** `get_current_frame()` добавляется в Task 6.3, но сервис помечен «TODO Phase 6» с полноценной реализацией. Не вносить реальный cv2.VideoCapture в production-путь без проверки на Windows (DirectShow backend). В тестах всегда mock.

2. **Stitcher multi-input классификация.** У stitcher только 1 Port в inputs (по коду), но семантика N:1. Нет атрибута `multi_input` на классе. В Task 6.1 хардкодим `name == "stitcher"` и документируем TODO. Риск: другие fan-in плагины в будущем пройдут в sandbox некорректно.

3. **`_init_register` требует `register_class` на плагине.** ColorMaskPlugin вызывает `_init_register(ctx)` в `configure()`. В sandbox передаётся `SubPluginContext` с `registers=None` → плагин создаст локальный регистр через fallback (строка `reg = cls()`). Это ожидаемое поведение, но нужно убедиться что `SubPluginContext` не ломает `ctx.registers.get_register()` — он вернёт `AttributeError` если `registers` это None и плагин вызывает `ctx.registers.get_register(...)`. Проверить: в `_init_register` есть guard `if ctx.registers is not None`.

4. **`build_plugin_sections` изменение сигнатуры** (Task 6.4) требует обратной совместимости — `tab.py` вызывает её дважды: в `__init__` и в `refresh_catalog()`. Добавить `open_sandbox_cb=None` как optional kwargs чтобы не сломать существующий код и тесты.
