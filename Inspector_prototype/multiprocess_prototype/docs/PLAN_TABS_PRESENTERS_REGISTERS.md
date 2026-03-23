# План: вкладки, презентеры, регистры (camera_tab → processing_tab → frontend_module)

Документ фиксирует, какие из предложенных улучшений для `CameraTabWidget` считаются уместными в контексте **нескольких вкладок** и будущего рефакторинга `frontend_module/components/tabs`, и **куда что выносить**.

После ревью план **усилен**: контракт регистров для GUI фиксируется **до** переписывания `camera_tab`; презентер отделён от Qt через интерфейс вью; колбэки — конкретный `dataclass`; добавлены фазы **1.5**, **2.5**.

---

## Уже есть во фреймворке (не дублировать)

| Механизм | Где |
|----------|-----|
| `BaseTab`, `TabWidget` | `frontend_module/components/tabs/` |
| `RegistersManagerLike` (минимум для `RegisterAdapter`, в т.ч. ожидание `set_field_value`) | `frontend_module/components/control_v2/base/interfaces.py` |
| `IRegistersManager` (get_register, get_field_metadata, validate_field_value — **без** `set_field_value`) | `frontend_module/interfaces.py` |
| `IRegistersManager` (расширенный) | `registers_module/interfaces.py` — сверить с GUI-нуждами |

Цель — **не плодить третий** независимый протокол, а ввести **один** GUI-ориентированный контракт и **подчинить** ему `RegistersManagerLike` / типы в `control_v2` (см. фазу 1.5).

---

## Контракт регистров для GUI (зафиксировать до рефакторинга вкладки)

Рабочее имя: **`IRegistersManagerGui`** (или переименование существующего типа после согласования).

Размещение: `frontend_module/interfaces.py` (публичный контракт фронтенд-модуля), чтобы и `control_v2`, и вкладки импортировали одно и то же.

Черновик сигнатур (уточнить по реальным `RegistersManager` / `RegisterAdapter`):

```python
from typing import Any, Callable, Optional, Protocol

class IRegistersManagerGui(Protocol):
    """Минимум для GUI: control_v2, вкладки, register_ops в приложении."""

    def set_field_value(self, register_name: str, field_name: str, value: Any) -> None: ...

    def get_register(self, register_name: str) -> Any: ...

    def get_field_metadata(
        self, register_name: str, field_name: str, **kwargs: Any
    ) -> dict: ...  # опционально, если уже есть в IRegistersManager

    # Фаза 4 (SoT / подписка): зарезервировать в протоколе или расширением
    # def subscribe_field(
    #     self, register_name: str, field_name: str, callback: Callable[..., None]
    # ) -> None: ...
```

Дальнейшие шаги по коду (фаза 1.5):

- В `control_v2/base/interfaces.py`: **`RegistersManagerLike` заменить на `IRegistersManagerGui`** или объявить алиас / наследование `RegistersManagerLike(IRegistersManagerGui, Protocol)` так, чтобы `NumericControl` и адаптер ссылались на **один** тип.
- `BaseTab` и фабрики вкладок: параметр `registers_manager: Optional[IRegistersManagerGui]` вместо `Any`.
- `multiprocess_prototype/.../register_ops.py`: аннотации с `IRegistersManagerGui`; проверки `hasattr` заменить на «аргумент соответствует протоколу» (структурная типизация).

**ADR в `DECISIONS.md`** — до или сразу с фазой 1.5: единый GUI-протокол регистров, совместимость с `registers_module`, Dict at Boundary для межпроцессных сообщений (без протаскивания Pydantic через границу процесса).

---

## Презентер и вью (без Qt в презентере)

**Правило:** презентер **не** импортирует `QLabel`, `QSlider` и т.п.

- **`CameraTabView`** — `Protocol` (или ABC) с методами вроде: выставить индекс типа камеры, переключить страницу стека, обновить список устройств, обновить тексты fallback-параметров, обновить подпись FPS. Имена согласовать с реальными операциями виджета.
- **`CameraTabWidget`** реализует `CameraTabView` и в слотах только вызывает методы презентера или дергает вью (свои же методы) для локальных обновлений по сигналам Qt.

Так презентер тестируется с **моком** вью без `QApplication`.

---

## Колбэки: предпочтение `dataclass` в прототипе

Для публичного API вкладки — явный тип, без magic strings и без обязательности `Protocol` с десятком методов.

Пример формы (сигнатуры уточнить при переносе из `GuiCommandHandler`):

```python
@dataclass
class CameraTabCallbacks:
    on_start: Optional[Callable[[], None]] = None
    on_stop: Optional[Callable[[], None]] = None
    on_set_fps: Optional[Callable[[int], None]] = None
    on_enum_devices: Optional[Callable[[], None]] = None
    on_open: Optional[Callable[..., None]] = None  # лучше: on_open(camera_index: int = 0)
    on_close: Optional[Callable[[], None]] = None
    on_start_grabbing: Optional[Callable[[], None]] = None
    on_stop_grabbing: Optional[Callable[[], None]] = None
    on_get_parameters: Optional[Callable[[], None]] = None
    on_set_parameters: Optional[Callable[[float, float, float], None]] = None
    on_camera_type_changed: Optional[Callable[[str], None]] = None
```

`tab_factory` / `FrontendLauncher` собирают один `CameraTabCallbacks`, а не `Dict[str, Callable]`.

---

## RegisterBindingContext (упрощение bind/unbind)

Один класс во фреймворке или в прототипе (после фазы 1.5 — лучше рядом с `control_v2`):

- На вход: `Optional[IRegistersManagerGui]`.
- Методы-фабрики или флаги: «можно ли вызывать `NumericControl.create`», обёртки `bind_numeric_slider` / `bind_numeric_spinbox` / fallback — чтобы **секции** (`fps_section`, `hikvision_params_section`) не дублировали `if registers_manager_can_bind(rm)`.

Секции принимают **`binding: RegisterBindingContext`**, а не сырой `rm`.

---

## Оценка исходных рекомендаций (1–10) — кратко

| № | Вердикт | Примечание |
|---|---------|------------|
| 1 | Да | Презентер + `CameraTabView`; обобщение во `frontend_module/components/tabs/` после стабилизации. |
| 2 | Да | Одна разметка + `RegisterBindingContext`, не два виджета. |
| 3 | Да | Реализуется через **`IRegistersManagerGui`** и фазу 1.5 **до** переписывания вкладки. |
| 4 | Да | **`CameraTabCallbacks` dataclass** в прототипе. |
| 5 | Да | Единые сигнатуры; граница с legacy — тонкие лямбды в launcher. |
| 6 | Да, позже | SoT + опционально `subscribe` в протоколе (задел под фазу 4). |
| 7 | Дозированно | Наблюдатели на презентере; Qt-сигналы только для UI-слоя. |
| 8 | Да | Валидатор `label_attribute` в `schemas.py`. |
| 9 | Вкусовщина | `ui_coerce` оставить отдельно или влить в `schemas.py`. |
| 10 | Да | Реализуется как `CameraTabView` (мок для тестов презентера). |

---

## Что переносить во `frontend_module` (приоритет)

| Приоритет | Артефакт | Назначение |
|-----------|----------|------------|
| **P1** | **`IRegistersManagerGui`** (+ согласование с `RegistersManagerLike`) | единый тип для control_v2 и вкладок |
| **P1b** | **`RegisterBindingContext`** (или аналог) | убрать размазанные проверки bind |
| **P2** | Абстрактный **TabPresenter** / каркас | после двух вкладок |
| **P3** | Расширение **BaseTab** (тип `rm`, хуки) | по необходимости |
| **P4** | Подписка на поля регистра в протоколе | фаза SoT |

**Не переносить:** `CameraTabUiConfig`, имена регистров приложения, `register_ops` с `CAMERA_REGISTER`, содержимое `CameraTabCallbacks` (кроме общих паттернов).

---

## Что остаётся в прототипе

- Схемы вкладок, `register_ops` (импортирует **`IRegistersManagerGui`**).
- **`CameraTabPresenter`**, **`CameraTabView`** (Protocol), **`CameraTabCallbacks`** (dataclass).
- Связка с `GuiCommandHandler` / `tab_factory` (сборка `CameraTabCallbacks`).

---

## Фазы (обновлённый порядок)

### Фаза 1 — Подготовка

- Черновик **`IRegistersManagerGui`** и запись **ADR** в `DECISIONS.md`.

### Фаза 1.5 — Согласование интерфейсов регистров (**до** кода презентера вкладки) ✅

- Ввести `IRegistersManagerGui` в `frontend_module/interfaces.py`.
- Заменить или согласовать **`RegistersManagerLike`** в `control_v2` с этим протоколом.
- Пройтись по **`BaseTab`**, фабрикам вкладок, **`register_ops`**: тип `Optional[IRegistersManagerGui]`, убрать `Any`/`hasattr` где возможно.
- Прогнать импорты / smoke-тесты фреймворка и прототипа.

### Фаза 2 — Пример: `camera_tab` ✅

- **`CameraTabView`** (Protocol): только операции отображения.
- **`CameraTabPresenter`**: принимает `rm: Optional[IRegistersManagerGui]`, `view: CameraTabView`, `callbacks: CameraTabCallbacks`, `ui: CameraTabUiConfig`; методы `on_camera_type_changed`, `on_fps_changed`, `on_hikvision_set_parameters`, …
- **`CameraTabWidget`**: строит UI, подключает сигналы к презентеру, реализует `CameraTabView`.
- Секции получают **`RegisterBindingContext`** вместо повторяющихся проверок.

### Фаза 2.5 — Порядок вызова колбэков ✅

- Колбэки из **`CameraTabCallbacks`** вызываются **после** того, как презентер обновил регистр (если `rm` есть) и/или своё состояние.
- Пример: **`on_set_parameters`** — презентер нормализует triple из регистра или из вью, затем один вызов `callbacks.on_set_parameters(fr, exp, gain)`; дублирующее ветвление в стиле текущего `_on_hikvision_set_params` остаётся **только** в презентере.

### Фаза 3 — `processing_tab`

- Тот же каркас: View + Presenter + Callbacks dataclass + binding context.
- Вынести повторяющееся во `frontend_module/components/tabs/` (P2).

### Фаза 4 — Регистр как источник истины

- Реализовать подписку (если введена в протокол): презентер подписывается на `camera_type` и обновляет вью без ручного `sync_camera_type` снаружи, где это возможно.

### Фаза 5 — Мелочи ✅

- Валидатор **`label_attribute`** в `CameraTabUiConfig`.
- Косметика: `ui_coerce`, константы в схеме.

---

## Связь с `DECISIONS.md`

Зафиксировать:

1. **Единый `IRegistersManagerGui`** и его связь с `registers_module` / `RegistersManagerLike`.
2. **Граница вкладки:** Qt только во вью; презентер без импорта Qt; команды в процессы через колбэки.
3. **Порядок:** обновление модели/регистра → затем колбэки (фаза 2.5).
4. **Dict at Boundary** для межпроцессных сообщений без изменения контракта GUI-протокола внутри процесса GUI.
