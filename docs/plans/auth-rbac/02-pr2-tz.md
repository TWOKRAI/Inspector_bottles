# ТЗ PR2 — Login Flow + Administration UI

> **Ветка:** `feat/auth-rbac-pr2-login-admin`
> **Базовый план:** [02-pr2-login-admin.md](02-pr2-login-admin.md)
> **Метаплан:** [00-metaplan.md](00-metaplan.md)
> **Дата:** 2026-05-11
> **Статус:** DRAFT

---

## 1. Goal

PR2 завершает видимую часть auth-системы: к готовому backend из PR1 добавляются глобальная кнопка «Войти» в header, LoginDialog, ConfirmWithPasswordDialog, подвкладка «Настройки → Администрация» с управлением пользователями и read-only просмотром ролей, реактивный объект AuthState как primary source of truth для состояния авторизации (совместим с WindowManager для будущей интеграции), middleware-блокировка мутаций до login. Результат: полностью рабочий UI входа и CRUD пользователей, наложенный на существующий каркас без переписывания фреймворка.

---

## 2. Architectural Decisions

### AD-1 — PreAuthGuard: расширение ActionBus через `set_pre_execute_hook`

**Выбрано:** Вариант 1 — минимальное расширение `ActionBus` в фреймворке.

В `multiprocess_framework/modules/actions_module/bus.py` добавляется один метод:

```
ActionBus.set_pre_execute_hook(
    hook: Callable[[Action], bool],
    on_blocked: Callable[[Action], None] | None = None,
) -> None
```

`execute()` вызывает `hook(action)` перед `handler.apply()`. Если hook вернул `False` — `apply` не вызывается, `_undo_stack` не трогается; если задан `on_blocked` — вызывается он. `undo()` и `redo()` хук **не** проходят — блокируется только новая мутация.

**Почему не Вариант 2 (HandlerProxy в bus_factory):** proxy обёртки дублируются для каждого handler-а, при добавлении нового handler блокировка теряется. hook — единственная точка входа, легко тестировать изолированно.

**Почему минимальное расширение фреймворка, а не обёртка в prototype:** sentrux boundaries допускают `application → framework` импорт, а вот держать security-логику целиком в prototype и дублировать её при каждом добавлении ActionBus в новые приложения — антипаттерн. Один метод `set_pre_execute_hook` в фреймворке универсален.

**Ограничение:** хук один (last-write wins). Если в будущем понадобится цепочка — вводится middleware-stack в PR4.

**Регистрация в prototype:** `bus_factory.create_action_bus()` принимает опциональный `auth_state: AuthState | None`. Если передан — регистрирует `PreAuthGuard(auth_state).hook` через `bus.set_pre_execute_hook`.

---

### AD-2 — AuthState: реактивное состояние авторизации

**Контекст:** `WindowManager` не используется в `multiprocess_prototype` (там один QMainWindow без WindowManager). Нужен lightweight QObject с сигналами для fan-out уведомлений. При этом WindowManager **планируется** подключить к prototype в будущем, поэтому AuthState должен быть совместим с его API — не заменять, а **дополнять/опционально интегрироваться**.

**Выбрано:** `multiprocess_prototype/frontend/state/auth_state.py` — `class AuthState(QObject)`.

Размещение в `state/` — в ряду с `bindings.py`. AuthState не знает про конкретные виджеты, только излучает сигналы.

**Архитектурная роль AuthState:**
- `AuthState` — **primary source of truth** для состояния авторизации. Хранит `current_user: dict | None`, `access_context: AccessContext`. Излучает сигналы: `access_context_changed(AccessContext)`, `current_user_changed(object)` (object = dict | None).
- `WindowManager` (когда будет подключён к prototype) — **optional consumer/propagator**. Слушает `AuthState.access_context_changed` и вызывает свой `set_access_context(ctx)` для пропагации в окна, зарегистрированные в нём.
- Пока WindowManager не подключён в prototype — AuthState работает автономно, виджеты подписываются на него напрямую.
- После подключения WindowManager — переписывать виджеты **не нужно**: AuthState остаётся источником истины, WindowManager — потребителем и усилителем (раздаёт context в окна, которые в нём зарегистрированы).

**Сигнатура сигналов совместима с WindowManager:** сигнал `access_context_changed` эмитирует ровно один аргумент типа `AccessContext` (не dict) — это соответствует сигнатуре `WindowManager.set_access_context(ctx: AccessContext)`. Прямой `connect` без адаптера.

**Совместимость с WindowManager (forward-compat):**

Опциональная wire-up функция создаётся в том же файле `auth_state.py`:

```
def wire_auth_state_to_window_manager(
    auth_state: AuthState,
    window_manager: "WindowManager",
) -> None:
    """Соединить AuthState с WindowManager одним connect.

    Вызывается в run_gui() когда window_manager появляется в ctx.extras.
    В PR2 НЕ ВЫЗЫВАЕТСЯ — WindowManager в prototype отсутствует.
    Готова к подключению без изменения виджетов.
    """
    auth_state.access_context_changed.connect(window_manager.set_access_context)
```

В PR2 эта функция присутствует в коде, но **не вызывается**. Когда WindowManager будет подключён к prototype — в `run_gui()` добавится один вызов `wire_auth_state_to_window_manager(auth_state, window_manager)`.

**Почему не использовать state_store_module напрямую:** `state_store_module` предназначен для сериализуемых данных, передаваемых через IPC. Auth-состояние — GUI-only, in-memory, без persistence. Добавление ветки `auth/current_user` в state_store потребовало бы изменений в GuiStateBindings и создало бы зависимость от IPC-пайплайна. QObject + сигналы — правильный паттерн для GUI-only реактивности в Qt.

**Альтернатива:** callback-список без Qt сигналов — хуже (нет автоматической очистки при удалении виджета, нет поддержки queued connections).

---

### AD-3 — AppContext: новые методы-аксессоры

**Выбрано:** расширить `AppContext` двумя методами-аксессорами, хранить объекты в `extras`.

```python
def auth_manager(self) -> "IAuthManager | None": ...
def auth_state(self) -> "AuthState | None": ...
```

Ключи в extras: `"auth_manager"`, `"auth_state"`.

**Почему extras, а не явные поля dataclass:** AppContext — dataclass с `extras: dict[str, Any]` для опциональных зависимостей (паттерн уже установлен для `action_bus`, `topology_holder`, `topology_bridge`, `bindings`). Добавление auth-зависимостей в extras сохраняет единообразие и не ломает существующие callsites `build_app_context(process, ...)`.

---

### AD-4 — Место инициализации AuthManager

**Выбрано:** `frontend/app.py:run_gui()`, **до** создания `MainWindow`, в отдельном блоке между шагом «3c» (TopologyBridge) и шагом «3d» (ActionBus).

**Порядок в run_gui():**

1. Применить тему (уже есть)
2. PluginRegistry + RegistersManager (уже есть)
3. AppContext base (уже есть)
4. TopologyHolder (уже есть)
5. StartupChecker (уже есть)
6. GuiStateBindings (уже есть)
7. TopologyBridge (уже есть)
8. **[НОВЫЙ] AuthManager init + AuthState + bootstrap-check**
9. ActionBus с optional PreAuthGuard (уже есть create_action_bus, расширяем)
10. MainWindow (уже есть)
11. ...

**Bootstrap-check:** если `YamlUserStorage(users_path).exists() == False` — показать блокирующий `StartupBlockingDialog` с текстом «Хранилище пользователей не найдено. Запустите: python -m Services.auth.bootstrap» и вызвать `sys.exit(1)`. Диалог появляется до `MainWindow` (нет смысла строить всё GUI при невозможности работы).

**Почему до MainWindow:** bootstrap-check может завершить процесс; строить MainWindow а потом бросать sys.exit — расточительно и создаёт побочные эффекты в тестах.

---

### AD-5 — bcrypt latency

**Решение для PR2:** bcrypt-хеширование (~50-100 мс при rounds=12) выполняется **в main thread**. Добавить `TODO(PR4): обернуть login() в QThread если замер > 150 мс на целевом оборудовании` в `LoginDialog._on_ok_clicked()`.

**Обоснование:** измеренное время bcrypt rounds=12 на современном x86 — ~70 мс. На ARM (macOS) — ~120 мс. Это ниже 200 мс UX-порога «заметная задержка». Блокировка main thread на 120 мс за одно нажатие «Войти» при редкой операции — приемлемо. Усложнять PR2 QThread ради гипотетической проблемы — нарушение YAGNI. В PR4 добавить `QProgressDialog` + QThread если тесты на production-железе покажут > 150 мс.

---

## 3. Группы задач

---

### Group A — Инфраструктура (Foundation)

**Цель:** создать AuthState, расширить AppContext, инициализировать AuthManager в run_gui, добавить PreAuthGuard hook в ActionBus, добавить QSS-правило.

**Зависимости:** только PR1 (уже в main). Группа A не зависит ни от B, C, D, E.

**Сложность:** Senior (Opus, normal thinking)

**Estimated effort:** 4–6 часов / 3 SP

---

#### A.1 — `AuthState(QObject)`

**Файл создать:**
`/Users/twokrai/Project_code/Inspector_bottles/multiprocess_prototype/frontend/state/auth_state.py`

**Контракт:**

```python
from PySide6.QtCore import QObject, Signal
from multiprocess_framework.modules.frontend_module.managers.access_context import AccessContext

class AuthState(QObject):
    """Primary source of truth для состояния авторизации.

    Виджеты подписываются напрямую на сигналы этого объекта.
    WindowManager (когда будет подключён к prototype) — optional consumer:
    слушает access_context_changed и пропагирует в зарегистрированные окна.
    Прямая интеграция через wire_auth_state_to_window_manager() — см. ниже.
    """

    # Эмитируется при смене пользователя (login/logout)
    current_user_changed = Signal(object)          # dict | None

    # Эмитируется при смене контекста прав (login/logout/role_change).
    # Сигнатура совместима с WindowManager.set_access_context(ctx: AccessContext):
    # один аргумент AccessContext — прямой connect без адаптера.
    access_context_changed = Signal(AccessContext)

    def __init__(self, parent: QObject | None = None) -> None: ...

    @property
    def current_user(self) -> dict | None: ...

    @property
    def access_context(self) -> AccessContext: ...

    @property
    def is_authenticated(self) -> bool: ...

    def set_user(self, user_dict: dict, access_context: AccessContext) -> None:
        """Установить нового пользователя. Эмитирует оба сигнала."""

    def clear(self) -> None:
        """Сбросить состояние (logout). Устанавливает AccessContext() дефолтный."""


def wire_auth_state_to_window_manager(
    auth_state: AuthState,
    window_manager: "WindowManager",
) -> None:
    """Опциональная интеграция AuthState с WindowManager.

    В PR2 НЕ ВЫЗЫВАЕТСЯ — WindowManager в prototype отсутствует.
    При подключении WindowManager к prototype — добавить вызов в run_gui():
        wire_auth_state_to_window_manager(auth_state, window_manager)
    Переписывать виджеты при этом не нужно: AuthState остаётся primary source,
    WindowManager — consumer/propagator для окон, зарегистрированных в нём.
    """
    auth_state.access_context_changed.connect(window_manager.set_access_context)
```

**Инварианты:**
- `clear()` устанавливает `current_user = None`, `access_context = AccessContext()` (все нули).
- `set_user()` принимает dict (Dict at Boundary — результат `login()` из AuthManager), AccessContext строится через `AccessContext.from_dict(login_result)`.
- Сигналы эмитируются **в том же вызове** (`set_user` → `current_user_changed`, `access_context_changed`; `clear` → те же два сигнала).
- Если новый user_dict тот же объект — сигналы всё равно эмитируются (нет кэширования).
- `access_context_changed` эмитирует строго `AccessContext` (не dict) — это обеспечивает прямую совместимость с `WindowManager.set_access_context`.

**Подзадача forward-compat:** функция `wire_auth_state_to_window_manager` создаётся в том же файле `auth_state.py`. В PR2 не вызывается, но готова к подключению. Сигнатура `access_context_changed(AccessContext)` специально согласована с `WindowManager.set_access_context(ctx: AccessContext)`.

**Acceptance criteria:**
- [ ] `auth_state.is_authenticated` == False при инициализации.
- [ ] После `set_user({"username": "alice", ...}, ctx)` → `current_user["username"] == "alice"`, `is_authenticated == True`.
- [ ] После `clear()` → `is_authenticated == False`, `current_user is None`.
- [ ] Оба сигнала эмитируются при каждом `set_user` и `clear` (проверяется в тестах Group E).
- [ ] `access_context_changed` эмитирует `AccessContext`, не dict (проверить через `qtbot.waitSignal`).
- [ ] Функция `wire_auth_state_to_window_manager` присутствует в модуле и импортируется без ошибок.

---

#### A.2 — Расширение `AppContext`

**Файл изменить:**
`/Users/twokrai/Project_code/Inspector_bottles/multiprocess_prototype/frontend/app_context.py`

**Изменения:**
1. В секцию `TYPE_CHECKING` добавить:
   ```python
   from multiprocess_prototype.frontend.state.auth_state import AuthState
   from Services.auth.interfaces import IAuthManager
   ```
2. Добавить два метода-аксессора:
   ```python
   def auth_manager(self) -> "IAuthManager | None":
       """IAuthManager из extras, если был инициализирован в run_gui."""
       return self.extras.get("auth_manager")

   def auth_state(self) -> "AuthState | None":
       """AuthState из extras, если был инициализирован в run_gui."""
       return self.extras.get("auth_state")
   ```
3. `build_app_context` — не изменять (auth-зависимости кладутся в extras вручную в run_gui).

**Acceptance criteria:**
- [ ] `ctx.auth_manager()` возвращает `None` если ключ отсутствует в extras.
- [ ] `ctx.auth_state()` возвращает `None` если ключ отсутствует в extras.
- [ ] TYPE_CHECKING импорты корректны (mypy/pyright не падают).

---

#### A.3 — Инициализация AuthManager и AuthState в `run_gui`

**Файл изменить:**
`/Users/twokrai/Project_code/Inspector_bottles/multiprocess_prototype/frontend/app.py`

**Новый блок между шагом «3c» (TopologyBridge) и шагом «3d» (ActionBus):**

```
# ── Auth: инициализация AuthManager + AuthState ──────────────────────
# Шаг 3e: загрузить AuthConfig из env, создать YamlUserStorage, проверить bootstrap
import os
from Services.auth import AuthManager, AuthConfig, YamlUserStorage
from multiprocess_prototype.frontend.state.auth_state import AuthState

_users_path = os.environ.get(
    "INSPECTOR_AUTH_USERS_PATH",
    str(Path.home() / ".inspector_bottles" / "auth" / "users.yaml"),
)
_auth_config = AuthConfig(users_path=_users_path)
_storage = YamlUserStorage(_auth_config)

if not _storage.exists():
    # Bootstrap не запускался — показать блокирующий диалог и выйти
    from multiprocess_prototype.frontend.widgets.dialogs import StartupBlockingDialog
    _dlg = StartupBlockingDialog(
        "Хранилище пользователей не найдено.\n\n"
        "Запустите перед запуском приложения:\n"
        "    python -m Services.auth.bootstrap"
    )
    _dlg.exec()
    sys.exit(1)

_auth_manager = AuthManager(_auth_config)
_auth_manager.initialize()
ctx.extras["auth_manager"] = _auth_manager

_auth_state = AuthState()
ctx.extras["auth_state"] = _auth_state
# ─────────────────────────────────────────────────────────────────────
```

**Отдельный файл для StartupBlockingDialog:**
`/Users/twokrai/Project_code/Inspector_bottles/multiprocess_prototype/frontend/widgets/dialogs/__init__.py`
— реэкспорт `StartupBlockingDialog`, `LoginDialog`, `ConfirmWithPasswordDialog` (Group B).

`/Users/twokrai/Project_code/Inspector_bottles/multiprocess_prototype/frontend/widgets/dialogs/startup_blocking_dialog.py`

```python
class StartupBlockingDialog(QDialog):
    """Блокирующий диалог при отсутствии bootstrap (не дает открыть основное окно)."""

    def __init__(self, message: str, parent: QWidget | None = None) -> None: ...
    # Кнопка только «Выход», текст — сообщение, без возможности закрыть через X
    # setWindowFlags(...) — убрать кнопку закрытия
```

**Acceptance criteria:**
- [ ] Если `users.yaml` не существует — запускается `StartupBlockingDialog` и `sys.exit(1)`.
- [ ] Если `users.yaml` существует — `ctx.auth_manager()` не None, `ctx.auth_state()` не None.
- [ ] `AuthManager.initialize()` вызывается до создания `MainWindow`.
- [ ] При ошибке `initialize()` (StorageCorrupted) — `process._log_error(...)` и отображение `StartupBlockingDialog` с текстом ошибки.

---

#### A.4 — PreAuthGuard: расширение `ActionBus` + middleware

**Файл изменить:**
`/Users/twokrai/Project_code/Inspector_bottles/multiprocess_framework/modules/actions_module/bus.py`

**Добавить в класс `ActionBus`:**

```python
# В __init__:
self._pre_execute_hook: Callable[[Action], bool] | None = None
self._on_blocked_callback: Callable[[Action], None] | None = None

def set_pre_execute_hook(
    self,
    hook: Callable[[Action], bool],
    on_blocked: Callable[[Action], None] | None = None,
) -> None:
    """Установить pre-execute хук.

    hook(action) -> bool: True — выполнять, False — заблокировать.
    on_blocked(action): вызывается при блокировке (например, показ диалога).
    Если None — предыдущий хук сбрасывается.
    """
    self._pre_execute_hook = hook
    self._on_blocked_callback = on_blocked

def clear_pre_execute_hook(self) -> None:
    """Сбросить pre-execute хук."""
    self._pre_execute_hook = None
    self._on_blocked_callback = None
```

В начале метода `execute(self, action: Action)` добавить:

```python
if self._pre_execute_hook is not None:
    if not self._pre_execute_hook(action):
        if self._on_blocked_callback is not None:
            self._on_blocked_callback(action)
        return
```

**Файл создать:**
`/Users/twokrai/Project_code/Inspector_bottles/multiprocess_prototype/frontend/actions/middleware/__init__.py`
`/Users/twokrai/Project_code/Inspector_bottles/multiprocess_prototype/frontend/actions/middleware/pre_auth_guard.py`

```python
"""PreAuthGuard — блокирует WriteAction до логина."""

from __future__ import annotations
from typing import TYPE_CHECKING, Callable
from multiprocess_framework.modules.actions_module.schemas import Action

if TYPE_CHECKING:
    from multiprocess_prototype.frontend.state.auth_state import AuthState

# Типы действий, разрешённые без логина (read-only / навигация)
_READ_ONLY_ACTION_TYPES = frozenset({
    "node_move",   # перемещение в GUI-только операция без state-мутации
    # При необходимости расширяется
})

class PreAuthGuard:
    """Хук для ActionBus: блокирует мутации до авторизации.

    Использование:
        guard = PreAuthGuard(auth_state)
        bus.set_pre_execute_hook(guard.hook, on_blocked=guard.show_auth_required)
    """

    def __init__(self, auth_state: "AuthState") -> None:
        self._auth_state = auth_state

    def hook(self, action: Action) -> bool:
        """True — разрешить выполнение, False — заблокировать."""
        if action.action_type in _READ_ONLY_ACTION_TYPES:
            return True
        return self._auth_state.is_authenticated

    def show_auth_required(self, action: Action) -> None:
        """Показать информационный диалог «Требуется вход».

        Вызывается ActionBus при блокировке (on_blocked callback).
        Импорт QMessageBox здесь — не в верхнем уровне, чтобы PreAuthGuard
        был тестируем без Qt-окружения (hook() не требует Qt).
        """
        from PySide6.QtWidgets import QMessageBox
        QMessageBox.information(
            None,
            "Требуется вход",
            f"Для выполнения действия «{action.description or action.action_type}» "
            "необходимо войти в систему.",
        )
```

**Файл изменить:**
`/Users/twokrai/Project_code/Inspector_bottles/multiprocess_prototype/frontend/actions/bus_factory.py`

Изменить сигнатуру `create_action_bus`:

```python
def create_action_bus(
    rm: Any,
    topology_holder: "TopologyHolder",
    *,
    topology_bridge: "TopologyBridge | None" = None,
    auth_state: "AuthState | None" = None,   # НОВЫЙ параметр
    max_history: int = 50,
) -> ActionBus:
```

В конце функции, перед `return bus`, добавить:

```python
if auth_state is not None:
    from .middleware.pre_auth_guard import PreAuthGuard
    guard = PreAuthGuard(auth_state)
    bus.set_pre_execute_hook(guard.hook, on_blocked=guard.show_auth_required)
```

**Файл изменить:**
`/Users/twokrai/Project_code/Inspector_bottles/multiprocess_prototype/frontend/app.py`

В вызов `create_action_bus(...)` передать `auth_state=_auth_state`.

---

#### A.5 — QSS-правило `readOnly`

**Файл изменить:**
`/Users/twokrai/Project_code/Inspector_bottles/multiprocess_prototype/frontend/styles/themes/innotech_theme/main.qss`

Добавить в конец файла:

```qss
/* ===== Auth RBAC: readOnly state (PR2) ===== */
/* Виджеты с property readOnly="true" → приглушённый вид (можно видеть, нельзя менять) */
*[readOnly="true"] {
    opacity: 0.5;
}
```

**Примечание:** Qt QSS поддерживает динамические properties через `setProperty("readOnly", True)`. `BaseConfigurableWidget._apply_access()` уже устанавливает это свойство (из PR1). QSS-правило замыкает цепочку.

**Acceptance criteria:**
- [ ] Виджет с `setProperty("readOnly", True)` после `style()->unpolish/polish()` отображается с opacity 0.5.
- [ ] Виджет без этого property — без изменений.

---

### Group B — Chrome Login (зависит от A)

**Цель:** кнопка «Войти/Выйти» в AppHeaderWidget, LoginDialog, ConfirmWithPasswordDialog, интеграция в MainWindow.

**Зависимости:** Group A (AuthState, AppContext.auth_state/auth_manager).

**Сложность:** Middle+ (Sonnet, extended thinking)

**Estimated effort:** 6–8 часов / 4 SP

---

#### B.1 — `LoginButton`

**Файл создать:**
`/Users/twokrai/Project_code/Inspector_bottles/multiprocess_prototype/frontend/widgets/chrome/login_button.py`

**Контракт:**

```python
class LoginButton(QPushButton):
    """Кнопка «Войти» / «<имя> ▾» в header.

    Состояния:
    - Не авторизован: текст «Войти», клик → LoginDialog.
    - Авторизован: текст «<username> ▾», клик → popup-меню (Выйти, Сменить пароль*).
      * «Сменить пароль» — disabled в PR2, задел для PR4.

    Presenter-логика встроена (View+Presenter в одном классе, т.к. виджет простой).
    Подписывается на auth_state.current_user_changed через Qt соединение.
    """

    def __init__(
        self,
        auth_state: "AuthState",
        auth_manager: "IAuthManager",
        parent: QWidget | None = None,
    ) -> None: ...

    def _on_user_changed(self, user_dict: dict | None) -> None:
        """Обновить текст и поведение кнопки при смене пользователя."""

    def _on_login_clicked(self) -> None:
        """Открыть LoginDialog."""

    def _on_logout_clicked(self) -> None:
        """Вызвать auth_manager.logout(), затем auth_state.clear()."""
```

**Детали реализации:**
- Popup-меню через `QMenu` с двумя действиями: «Выйти», «Сменить пароль» (disabled).
- Текст кнопки при логине: `f"{username} ▾"`, при логауте: `"Войти"`.
- Подключение: `auth_state.current_user_changed.connect(self._on_user_changed)`.

---

#### B.2 — `LoginDialog`

**Файл создать:**
`/Users/twokrai/Project_code/Inspector_bottles/multiprocess_prototype/frontend/widgets/dialogs/login_dialog.py`

**Контракт:**

```python
class LoginDialog(QDialog):
    """Диалог входа: поля «Логин» и «Пароль» + кнопки «Войти» / «Отмена».

    Результат: LoginDialog.login_result: dict | None.
    Если None — пользователь отменил или произошла ошибка.
    """

    login_result: dict | None  # устанавливается при успешном login

    def __init__(
        self,
        auth_manager: "IAuthManager",
        auth_state: "AuthState",
        parent: QWidget | None = None,
    ) -> None: ...

    def _on_ok_clicked(self) -> None:
        """Вызвать auth_manager.login(username, password).

        Успех:
            login_result = result_dict
            AccessContext.from_dict(result_dict) → auth_state.set_user(result_dict, ctx)
            self.accept()

        Ошибки (каждая — свой текст под полями):
            InvalidCredentials  → «Неверный логин или пароль»
            AccountLocked       → «Аккаунт заблокирован. Попыток: {N}. Подождите {M} сек.»
            AuthError (прочее)  → «Ошибка входа: {str(e)}»

        Поле пароля очищается при любой ошибке.
        Фокус возвращается на поле логина при InvalidCredentials, на поле пароля при AccountLocked.
        """

    # TODO(PR4): обернуть в QThread если bcrypt latency > 150 мс на целевом оборудовании
```

**Детали UI:**
- `QFormLayout`: строка «Логин» → `QLineEdit`, строка «Пароль» → `QLineEdit(echoMode=Password)`.
- `QLabel` для ошибки (пустой, красный, под формой) — `_error_label`.
- `QDialogButtonBox(Ok | Cancel)` внизу.
- Поле «Логин» с `setPlaceholderText("Имя пользователя")`.
- Enter в любом поле — эквивалент нажатия «Войти».

---

#### B.3 — `ConfirmWithPasswordDialog`

**Файл создать:**
`/Users/twokrai/Project_code/Inspector_bottles/multiprocess_prototype/frontend/widgets/dialogs/confirm_with_password.py`

**Контракт:**

```python
class ConfirmWithPasswordDialog(QDialog):
    """Диалог подтверждения деструктивного действия с вводом пароля.

    Используется при: удалении пользователя, сбросе пароля.

    Параметры конструктора:
        auth_manager  — для verify_admin_password()
        action_text   — описание действия (e.g., «Удалить пользователя "alice"»)
        parent        — родительский виджет

    После exec():
        .confirmed: bool — True если пользователь ввёл верный пароль и нажал OK.
    """

    confirmed: bool

    def __init__(
        self,
        auth_manager: "IAuthManager",
        action_text: str,
        parent: QWidget | None = None,
    ) -> None: ...

    def _on_ok_clicked(self) -> None:
        """auth_manager.verify_admin_password(password) → accept() или показать ошибку."""
```

**Детали UI:**
- Текст действия (`QLabel` с action_text, жирный).
- Поле «Пароль администратора» (`QLineEdit(echoMode=Password)`).
- `QLabel` для ошибки «Неверный пароль» (скрыт по умолчанию).
- `QDialogButtonBox(Ok | Cancel)`.

---

#### B.4 — Интеграция LoginButton в AppHeaderWidget и MainWindow

**Файл изменить:**
`/Users/twokrai/Project_code/Inspector_bottles/multiprocess_prototype/frontend/widgets/chrome/app_header.py`

Добавить метод:

```python
def set_login_button(self, button: "LoginButton") -> None:
    """Вставить LoginButton между _status_label и правым краем layout.

    Вставляется в layout на позицию перед последним stretch:
      [BrandLabel] [stretch] [StatusLabel] [LoginButton]
    """
```

**Файл изменить:**
`/Users/twokrai/Project_code/Inspector_bottles/multiprocess_prototype/frontend/app.py`

После создания `MainWindow` (шаг 4) добавить:

```python
# Кнопка входа в header (зависит от auth_state и auth_manager)
if ctx.auth_state() is not None and ctx.auth_manager() is not None:
    from .widgets.chrome.login_button import LoginButton
    _login_btn = LoginButton(ctx.auth_state(), ctx.auth_manager())
    window.header.set_login_button(_login_btn)
```

**Acceptance criteria Group B:**
- [ ] `/run-proto` → в правой части header видна кнопка «Войти».
- [ ] Нажать «Войти» → открывается LoginDialog с двумя полями.
- [ ] Ввести неверный пароль → ошибка под формой, диалог не закрывается.
- [ ] Ввести `AccountLocked` ситуацию (5 неверных попыток подряд в тесте) → отображается задержка в секундах.
- [ ] Успешный вход → кнопка меняется на `«<username> ▾»`.
- [ ] Клик по `«<username> ▾»` → popup-меню «Выйти» + «Сменить пароль» (disabled).
- [ ] «Выйти» → кнопка возвращается в «Войти», auth_state.is_authenticated == False.
- [ ] `ConfirmWithPasswordDialog`: неверный пароль → ошибка; верный → `confirmed == True`.

---

### Group C — Users Panel (зависит от A, B)

**Цель:** секция «Пользователи» в подвкладке «Настройки → Администрация».

**Зависимости:** Group A (AppContext), Group B (ConfirmWithPasswordDialog).

**Сложность:** Middle+ (Sonnet, extended thinking)

**Estimated effort:** 8–10 часов / 5 SP

---

#### C.1 — Директория и секция

**Файлы создать:**
```
/Users/twokrai/Project_code/Inspector_bottles/multiprocess_prototype/frontend/widgets/tabs/settings/administration/__init__.py
/Users/twokrai/Project_code/Inspector_bottles/multiprocess_prototype/frontend/widgets/tabs/settings/administration/section.py
```

**Контракт `AdministrationSection`:**

```python
class AdministrationSection(QWidget):
    """Секция «Администрация» — SideNavLayout с двумя подсекциями.

    Структура:
      SideNavLayout
        «Пользователи» → UsersPanel(ctx)
        «Роли»         → RolesPanel(ctx)

    Права: секция видима только при наличии хотя бы одного из permissions
    "users.view" или "roles.view". При отсутствии обоих — отображает
    placeholder «Недостаточно прав».
    """

    def __init__(self, ctx: "AppContext", parent: QWidget | None = None) -> None: ...
```

**Файл изменить:**
`/Users/twokrai/Project_code/Inspector_bottles/multiprocess_prototype/frontend/widgets/tabs/settings/tab.py`

В словаре `section_widgets` заменить:

```python
# БЫЛО:
# section_widgets строится без "administration" — fallback на _build_placeholder

# СТАЛО:
section_widgets: dict[str, QWidget] = {
    "administration": self._build_administration_section(),
    "system_settings": self._build_system_section(),
    "history": self._build_history_section(),
}
```

Добавить метод:

```python
def _build_administration_section(self) -> QWidget:
    """Секция «Администрация» — AdministrationSection или placeholder если нет ctx."""
    if self._ctx is None:
        return self._build_placeholder("Администрация")
    from .administration.section import AdministrationSection
    return AdministrationSection(self._ctx)
```

---

#### C.2 — `UsersPanel`

**Файл создать:**
`/Users/twokrai/Project_code/Inspector_bottles/multiprocess_prototype/frontend/widgets/tabs/settings/administration/users_panel.py`

**Layout (по образцу RecipesTab):**

```
QVBoxLayout
  +-- QHBoxLayout (заголовок «Пользователи» + ViewModeToggle справа)
  +-- QHBoxLayout (stretch=1)
        +-- QListWidget (список логинов, ширина 180px)
        +-- QStackedWidget (stretch=1)
              0: StructuredTableWidget (Table mode)
              1: QWidget-заглушка Cards mode (в PR2 только Table, Cards — TODO)
        +-- QVBoxLayout (кнопки, ширина 110px):
              «Добавить»
              «Удалить»
              «Сменить роль»
              «Сбросить пароль»
              ---
              stretch
```

**Контракт:**

```python
class UsersPanel(QWidget):
    """Панель управления пользователями.

    Колонки таблицы: Логин | Роль | Создан | Последний вход | Входов | Активен
    """

    _TABLE_COLUMNS = [
        ("username",       "Логин",           160),
        ("role_name",      "Роль",            100),
        ("created_at",     "Создан",          120),
        ("last_login_at",  "Последний вход",  120),
        ("login_count",    "Входов",           60),
        ("is_active",      "Активен",          70),
    ]

    def __init__(self, ctx: "AppContext", parent: QWidget | None = None) -> None: ...

    def _load_users(self) -> None:
        """Загрузить список через auth_manager.list_users() и заполнить таблицу и список."""

    def _on_add_clicked(self) -> None:
        """Открыть UserForm в диалоге. При accept → auth_manager.create_user() → reload."""

    def _on_delete_clicked(self) -> None:
        """ConfirmWithPasswordDialog → auth_manager.delete_user(selected) → reload."""

    def _on_change_role_clicked(self) -> None:
        """Диалог смены роли (QInputDialog.getItem с list_roles()) → auth_manager.update_user_role() → reload."""

    def _on_reset_password_clicked(self) -> None:
        """ConfirmWithPasswordDialog → auth_manager.reset_password(selected)
           → QMessageBox с новым паролем + автоматически копируется в clipboard."""
```

**Обработка ошибок:**
- `LastAdminError` при удалении → `QMessageBox.warning(None, "Ошибка", str(e))`.
- `UserNotFound` при любой операции → `QMessageBox.warning(...)`.
- Любое другое `AuthError` → `QMessageBox.critical(None, "Ошибка", str(e))`.

**Clipboard при reset_password:**
```python
from PySide6.QtGui import QClipboard
from PySide6.QtWidgets import QApplication
QApplication.clipboard().setText(new_password)
QMessageBox.information(
    self, "Новый пароль",
    f"Новый пароль для «{username}»:\n\n{new_password}\n\n"
    "(Пароль скопирован в буфер обмена. Сохраните его — он больше не отобразится.)"
)
```

---

#### C.3 — `UserForm`

**Файл создать:**
`/Users/twokrai/Project_code/Inspector_bottles/multiprocess_prototype/frontend/widgets/tabs/settings/administration/user_form.py`

**Контракт:**

```python
class UserForm(QDialog):
    """Диалог создания нового пользователя.

    Поля:
      - «Логин»   QLineEdit  (username, обязательное)
      - «Пароль»  QLineEdit  (echoMode=Password, обязательное, валидация PasswordPolicy)
      - «Роль»    QComboBox  (role_name, список из list_roles(), скрыть hidden_in_ui=True роли)
      - «Активен» QCheckBox  (is_active, по умолчанию True)

    Результат:
      .result_data: dict | None  — dict с полями username/password/role_name/is_active
                                    или None при отмене.
    """

    result_data: dict | None

    def __init__(
        self,
        auth_manager: "IAuthManager",
        parent: QWidget | None = None,
    ) -> None: ...

    def _validate(self) -> bool:
        """Проверить username непустой, пароль не пустой. Вернуть bool."""

    def _on_ok_clicked(self) -> None:
        """Собрать result_data и accept()."""
```

**Валидация пароля:**
- Не пустой — обязательное условие (иначе подсветить поле красным, не закрывать).
- Полная проверка через `PasswordPolicy` делается в `auth_manager.create_user()` на стороне backend — если `WeakPassword` → показать текст из исключения под полем пароля.

---

**Acceptance criteria Group C:**
- [ ] В Settings → Администрация → Пользователи: видна таблица с пользователями.
- [ ] «Добавить» → UserForm → заполнить → OK → пользователь появляется в таблице.
- [ ] `users.yaml` обновлён атомарно (проверить через `cat ~/.inspector_bottles/auth/users.yaml`).
- [ ] «Удалить» → ConfirmWithPasswordDialog → верный пароль → пользователь удалён.
- [ ] «Удалить» последнего admin → сообщение об ошибке, пользователь не удалён.
- [ ] «Сбросить пароль» → QMessageBox с новым паролем, скопирован в clipboard.
- [ ] «Сменить роль» → QInputDialog.getItem → роль изменена в таблице.

---

### Group D — Roles Panel (параллельно C, зависит от A)

**Цель:** секция «Роли» в подвкладке «Настройки → Администрация» (read-only).

**Зависимости:** Group A (AppContext), Group C.1 (AdministrationSection создаётся в C.1).

**Сложность:** Middle (Sonnet, normal thinking)

**Estimated effort:** 4–5 часов / 2 SP

---

#### D.1 — `RolesPanel`

**Файл создать:**
`/Users/twokrai/Project_code/Inspector_bottles/multiprocess_prototype/frontend/widgets/tabs/settings/administration/roles_panel.py`

**Layout:**

```
QVBoxLayout
  +-- QHBoxLayout (заголовок «Роли» + метка «(только чтение)» серая)
  +-- QHBoxLayout (stretch=1)
        +-- QListWidget (список ролей, ширина 160px)
              скрыть роли с hidden_in_ui=True (роль dev)
        +-- PermissionMatrix (stretch=1, read-only)
        +-- QVBoxLayout (кнопки, все disabled в PR2):
              «Создать роль» [disabled]
              «Изменить права» [disabled]
              «Удалить роль» [disabled]
              stretch
```

**Контракт:**

```python
class RolesPanel(QWidget):
    """Панель просмотра ролей (read-only в PR2).

    Кнопки управления ролями disabled — активируются в PR4.
    Роли с hidden_in_ui=True (dev) не отображаются в списке.
    """

    def __init__(self, ctx: "AppContext", parent: QWidget | None = None) -> None: ...

    def _load_roles(self) -> None:
        """Загрузить роли через auth_manager.list_roles(), заполнить список."""

    def _on_role_selected(self, role_name: str) -> None:
        """Передать выбранную роль в PermissionMatrix для отображения."""
```

---

#### D.2 — `PermissionMatrix`

**Файл создать:**
`/Users/twokrai/Project_code/Inspector_bottles/multiprocess_prototype/frontend/widgets/tabs/settings/administration/permission_matrix.py`

**Контракт:**

```python
class PermissionMatrix(QWidget):
    """Read-only матрица permissions: строки = ресурсы, колонки = View / Edit.

    В PR2 все чекбоксы disabled (read-only).
    Данные загружаются через set_role(role_dict).

    Структура отображения (дерево по scope.resource):
      ┌──────────────────┬──────┬──────┐
      │ Ресурс           │ View │ Edit │
      ├──────────────────┼──────┼──────┤
      │ tabs.recipes     │  ✓   │  ✓   │
      │ tabs.pipeline    │  ✓   │      │
      │ ...              │      │      │
      └──────────────────┴──────┴──────┘
    """

    def __init__(self, parent: QWidget | None = None) -> None: ...

    def set_role(self, role_dict: dict) -> None:
        """Отобразить permissions роли. Все чекбоксы disabled."""

    def clear(self) -> None:
        """Очистить матрицу."""
```

**Алгоритм построения строк:**
- Из `role_dict["permissions"]` (список строк `scope.resource.action`) извлечь уникальные `scope.resource`.
- Для каждого `scope.resource` — одна строка таблицы. Чекбокс View = наличие `...view` в permissions, Edit = наличие `...edit`.
- `QTableWidget` с двумя колонками «View» / «Edit», каждая ячейка — `QCheckBox` в `QWidget(setCentralWidget)` через `setCellWidget`.
- Все чекбоксы: `setEnabled(False)`.

**Acceptance criteria Group D:**
- [ ] Settings → Администрация → Роли: виден список ролей (dev скрыт).
- [ ] Выбор роли → PermissionMatrix показывает permissions без возможности изменить.
- [ ] Кнопки «Создать/Изменить/Удалить роль» — disabled.

---

### Group E — Tests (параллельно, после A)

**Цель:** pytest-qt тесты для всех новых компонентов PR2.

**Зависимости:** Group A (минимально — для запуска тестов AuthState без Qt), Groups B/C/D для UI-тестов.

**Сложность:** Middle (Sonnet, normal thinking)

**Estimated effort:** 5–6 часов / 3 SP

---

#### E.1 — Тест `AuthState`

**Файл создать:**
`/Users/twokrai/Project_code/Inspector_bottles/multiprocess_prototype/frontend/state/tests/test_auth_state.py`

**Тест-кейсы:**
- `test_initial_state`: `is_authenticated == False`, `current_user is None`, `access_context == AccessContext()`.
- `test_set_user_emits_signals(qtbot)`: `set_user(user_dict, ctx)` → оба сигнала эмитированы.
- `test_clear_emits_signals(qtbot)`: после `set_user`, `clear()` → `is_authenticated == False`, сигналы эмитированы.
- `test_access_context_after_login`: `access_context.role_name == "admin"` после `set_user({..., "role_name": "admin"}, ctx)`.

---

#### E.2 — Тест `PreAuthGuard`

**Файл создать:**
`/Users/twokrai/Project_code/Inspector_bottles/multiprocess_prototype/frontend/actions/middleware/tests/__init__.py`
`/Users/twokrai/Project_code/Inspector_bottles/multiprocess_prototype/frontend/actions/middleware/tests/test_pre_auth_guard.py`

**Тест-кейсы:**
- `test_blocks_write_when_not_authenticated`: `guard.hook(Action(action_type="field_set", ...))` == False при `auth_state.is_authenticated == False`.
- `test_allows_read_only_action`: `guard.hook(Action(action_type="node_move", ...))` == True при `is_authenticated == False`.
- `test_allows_write_when_authenticated`: `guard.hook(Action(action_type="field_set", ...))` == True после `auth_state.set_user(...)`.
- `test_action_bus_integration(qtbot)`: bus с хуком → execute(write_action) до login → handler.apply **не** вызывается.

**Фикстуры:**
- `auth_state`: `AuthState()` без QApplication (QObject требует).
- `mock_action_handler`: объект с `apply = MagicMock()`, `revert = MagicMock()`.

---

#### E.3 — Тест `LoginDialog`

**Файл создать:**
`/Users/twokrai/Project_code/Inspector_bottles/multiprocess_prototype/frontend/widgets/dialogs/tests/__init__.py`
`/Users/twokrai/Project_code/Inspector_bottles/multiprocess_prototype/frontend/widgets/dialogs/tests/test_login_dialog.py`

**Тест-кейсы:**
- `test_login_success(qtbot)`: mock `auth_manager.login` → возвращает успешный dict → `auth_state.is_authenticated == True` после `_on_ok_clicked`.
- `test_login_invalid_credentials(qtbot)`: mock throws `InvalidCredentials` → ошибка под полем, диалог не закрыт (`result()` не вызван).
- `test_login_account_locked(qtbot)`: mock throws `AccountLocked(failures=5, delay_sec=60)` → ошибка с задержкой.
- `test_cancel_does_not_set_user(qtbot)`: нажать Cancel → `auth_state.is_authenticated == False`.

**Фикстуры:**
- `mock_auth_manager`: `MagicMock(spec=IAuthManager)`.
- `auth_state`: `AuthState()`.

---

#### E.4 — Тест `ConfirmWithPasswordDialog`

**Файл создать:**
`/Users/twokrai/Project_code/Inspector_bottles/multiprocess_prototype/frontend/widgets/dialogs/tests/test_confirm_with_password.py`

**Тест-кейсы:**
- `test_correct_password_confirms(qtbot)`: mock `verify_admin_password` → True → `dlg.confirmed == True`.
- `test_wrong_password_shows_error(qtbot)`: mock → False → ошибка под полем, `dlg.confirmed == False`.
- `test_cancel_not_confirmed(qtbot)`: Cancel → `dlg.confirmed == False`.

---

#### E.5 — Тест `UsersPanel`

**Файл создать:**
`/Users/twokrai/Project_code/Inspector_bottles/multiprocess_prototype/frontend/widgets/tabs/settings/administration/tests/__init__.py`
`/Users/twokrai/Project_code/Inspector_bottles/multiprocess_prototype/frontend/widgets/tabs/settings/administration/tests/test_users_panel.py`

**Тест-кейсы:**
- `test_load_users(qtbot)`: mock `list_users` → 2 пользователя → таблица содержит 2 строки.
- `test_add_user(qtbot)`: stub UserForm → accept с valid data → `create_user` вызван, `list_users` перезапрошен.
- `test_delete_user_calls_confirm(qtbot)`: выбрать строку → кликнуть «Удалить» → `ConfirmWithPasswordDialog` вызван (проверить через mock).
- `test_reset_password_shows_alert(qtbot)`: mock `reset_password` → новый пароль → QMessageBox показан (проверить через `monkeypatch`).
- `test_last_admin_error_shows_warning(qtbot)`: mock `delete_user` throws `LastAdminError` → предупреждение, пользователь не удалён.

---

## 4. Sentrux rules update

**Файл изменить:**
`/Users/twokrai/Project_code/Inspector_bottles/.sentrux/rules.toml`

### 4.1 — Разрешить импорт `Services/auth` из `multiprocess_prototype`

Текущий barrier `Services/* → multiprocess_prototype/*` и наоборот уже закрыты. Однако нет явного правила, которое **разрешает** `multiprocess_prototype → Services/auth`. В sentrux разрешение задаётся через слои (`layers`) — импорт из `application` в `services` разрешён по `order = 3 > 1`.

Никаких новых `[[boundaries]]` для разрешения не требуется — он уже разрешён слоёвой моделью.

**Но:** текущий `[[boundaries]]` блок уже содержит:
```toml
[[boundaries]]
from   = "Services/auth/*"
to     = "multiprocess_framework/modules/frontend_module/*"
reason = "..."
```
Добавить зеркальный запрет (на всякий случай, чтобы auth не импортировал Qt-код prototype):

```toml
# Добавить в .sentrux/rules.toml после существующего auth-boundary:

[[boundaries]]
from   = "Services/auth/*"
to     = "multiprocess_prototype/*"
reason = "Services/auth — чистый backend без импортов Qt-prototype (PR2 auth-rbac)"
```

### 4.2 — Разрешить `multiprocess_prototype/frontend/actions/middleware/*` в слое `application`

Новая директория `actions/middleware/` находится внутри `multiprocess_prototype/*` — уже в слое `application`. Никаких дополнительных rules не требуется.

### 4.3 — Порог quality после PR2

После добавления ~8 новых файлов в prototype модульность может незначительно просесть. Пороги в `[constraints]` не изменяем — они уже выставлены с запасом (`min_quality = 0.60`). Запустить `/sentrux-diff` после Group A, B, C, D и убедиться в отсутствии деградации.

**Финальный блок для добавления в `.sentrux/rules.toml`:**

```toml
# ── PR2 auth-rbac: Services/auth не импортирует prototype ──────────────
[[boundaries]]
from   = "Services/auth/*"
to     = "multiprocess_prototype/*"
reason = "Services/auth — чистый backend, импорт Qt-виджетов и app-кода запрещён (PR2)"
```

---

## 5. Risks & Mitigations

### R1 — bcrypt latency ≥ 150 мс на production-оборудовании

**Вероятность:** низкая (промышленные ПК быстрее макбука).
**Влияние:** зависание UI на ~150 мс при нажатии «Войти» — заметно, но редко (один раз при старте смены).
**Митигация:** TODO-заметка в `LoginDialog._on_ok_clicked`. Метрика для измерения: логировать `time.perf_counter()` до/после `auth_manager.login()`. Если > 150 мс по итогам PR3-тестирования — обернуть в `QThread` в PR4.

---

### R2 — Многооконный режим

**Контекст:** `MainWindow` существует в одном экземпляре в prototype. `WindowManager` не используется в PR2.
**Риск:** если в будущем добавится второе окно (например, детекционный монитор) — оно не получит `access_context_changed` сигнал от AuthState напрямую (если виджеты второго окна не подписались).
**Митигация:**
- В PR2: все виджеты, которым нужен AccessContext, подписываются на `auth_state.access_context_changed` напрямую. Это правило закрепить в docstring `AuthState`.
- При подключении WindowManager к prototype: вызов `wire_auth_state_to_window_manager(auth_state, window_manager)` в `run_gui()` автоматически решает задачу fan-out для всех окон, зарегистрированных в WindowManager. Виджеты, уже подписанные напрямую на AuthState, переписывать не нужно — они получат сигналы дважды (напрямую от AuthState и через WindowManager). При необходимости — переключить на WindowManager-подписку в отдельном PR.

### R7 — WindowManager в prototype отсутствует, API AuthState совместим

**Контекст:** WindowManager существует в `frontend_module` фреймворка, но к `multiprocess_prototype` не подключён.
**Риск:** при подключении WindowManager окажется, что сигнал `access_context_changed` несовместим с `WindowManager.set_access_context` по сигнатуре.
**Митигация:** сигнал `access_context_changed` эмитирует строго `AccessContext` (не dict, не tuple) — та же сигнатура что у `WindowManager.set_access_context(ctx: AccessContext)`. Прямой `connect` без адаптера. `wire_auth_state_to_window_manager` уже написана и протестирована на момент PR2. Будущая интеграция — одна строка в `run_gui()` без переписывания виджетов.

---

### R3 — pytest-qt в CI без дисплея

**Контекст:** `pytest-qt` с `qt_api = pyside6` требует X11/Wayland на Linux. CI-раннеры GitLab/GitHub Actions — headless.
**Митигация:**
- Проверить наличие `xvfb-run` в CI-конфигурации. Если отсутствует — добавить `QT_QPA_PLATFORM=offscreen` в переменные окружения CI.
- В тест-файлах использовать `qtbot` из pytest-qt — он автоматически управляет жизненным циклом виджета.
- `StartupBlockingDialog` тестировать без реального `sys.exit(1)`: мокировать `sys.exit`.

---

### R4 — Обратная совместимость существующих табов

**Риск:** добавление `AdministrationSection` в `SettingsTab` может сломать `test_settings_tab.py` (ожидает placeholder).
**Митигация:**
- `_build_administration_section()` проверяет `self._ctx is not None` перед созданием `AdministrationSection`. В тестах `SettingsTab` создаётся без `auth_manager` в extras — секция деградирует до placeholder.
- После PR2 обновить `test_settings_tab.py`: добавить тест `test_administration_section_requires_ctx`.

---

### R5 — Коллизия ключей в `extras` AppContext

**Риск:** кто-то уже использует ключ `"auth_manager"` или `"auth_state"` в extras.
**Митигация:** `grep -r '"auth_manager"' multiprocess_prototype/` — проверить до PR2. На момент написания ТЗ этих ключей нет.

---

### R6 — Атомарность YAML при параллельном доступе

**Контекст:** `YamlUserStorage.save()` использует `tempfile + os.replace` (атомарная замена). В Python GIL защищает только от гонок в одном процессе.
**Риск:** если два виджета одновременно вызовут `create_user` (double-click «Добавить») — второй перезапишет файл.
**Митигация:** кнопки CRUD-панели делать `setEnabled(False)` на время выполнения операции и `setEnabled(True)` в finally-блоке. Это простая UI-блокировка без lock-файлов.

---

## 6. Sequence Diagram — Login Flow

```mermaid
sequenceDiagram
    actor User
    participant LB as LoginButton
    participant LD as LoginDialog
    participant AM as AuthManager
    participant AS as AuthState
    participant AW as Widget(AccessTrait)
    participant Guard as PreAuthGuard
    participant WM as WindowManager (future)

    User->>LB: click «Войти»
    LB->>LD: open (exec())
    User->>LD: ввести username + password → OK
    LD->>AM: login(username, password)
    AM-->>LD: result_dict {success, role_name, permissions, level, ...}
    Note over LD: AccessContext.from_dict(result_dict)
    LD->>AS: set_user(result_dict, access_context)
    AS-->>LB: current_user_changed(user_dict)
    AS-->>AW: access_context_changed(AccessContext)
    AS--.->WM: access_context_changed(AccessContext) [когда подключён]
    Note over WM: set_access_context(ctx) → пропагирует в окна
    LB->>LB: setText(f"{username} ▾")
    AW->>AW: _apply_access(ctx) → setEnabled/setVisible
    Note over Guard: hook(action) теперь True (is_authenticated)
    LD-->>LD: accept()

    User->>LB: click «<username> ▾» → «Выйти»
    LB->>AM: logout()
    LB->>AS: clear()
    AS-->>LB: current_user_changed(None)
    AS-->>AW: access_context_changed(AccessContext())
    AS--.->WM: access_context_changed(AccessContext()) [когда подключён]
    LB->>LB: setText("Войти")
    AW->>AW: _apply_access(AccessContext()) → disabled
    Note over Guard: hook(action) снова False
```

---

## 7. Rollback Plan

Если PR2 необходимо откатить (например, критический баг в UsersPanel за 5 минут до релиза):

1. **Откат `settings/tab.py`:** вернуть исходный словарь `section_widgets` без ключа `"administration"` (секция снова использует `_build_placeholder("Администрация")`). Один метод — `_build_administration_section` удалить.

2. **Откат `app.py`:** удалить блок «Auth init» между TopologyBridge и ActionBus. Убрать передачу `auth_state` в `create_action_bus`. Убрать `_login_btn` интеграцию в header.

3. **Откат `app_context.py`:** удалить методы `auth_manager()` и `auth_state()`.

4. **Откат `actions/bus.py`:** удалить `set_pre_execute_hook` и `clear_pre_execute_hook`, убрать вызов хука из `execute()`.

5. **Новые файлы** (`auth_state.py`, `login_button.py`, `dialogs/`, `administration/`, `actions/middleware/`) — не трогать (они не импортируются если app.py и settings/tab.py откачены). Можно оставить или удалить — не критично.

6. **QSS:** строка `*[readOnly="true"] { opacity: 0.5; }` безвредна без виджетов с этим property.

7. **`.sentrux/rules.toml`:** откатить добавленный `[[boundaries]]` блок (1 строка).

8. **Services/auth** — не трогать. Backend остаётся полностью работоспособным и используется при следующем запуске после откатного исправления.

После отката — `python scripts/validate.py` + `/sentrux-check` должны быть зелёными.

---

## Definition of Done (Checklist)

- [ ] `/run-proto` → кнопка «Войти» видна в правой части header.
- [ ] Login → редактируемые контролы доступны (PreAuthGuard пропускает); logout → блокированы.
- [ ] Settings → Администрация → Пользователи: список, таблица, CRUD работают.
- [ ] `users.yaml` обновляется атомарно при каждой операции CRUD.
- [ ] «Сбросить пароль» → QMessageBox с паролем, пароль в clipboard.
- [ ] До login → попытка мутации через ActionBus → QMessageBox «Требуется вход».
- [ ] Settings → Администрация → Роли: список ролей без dev, read-only PermissionMatrix.
- [ ] `pytest` из корня → все тесты Groups A–E зелёные.
- [ ] `/sentrux-diff` → качество не ниже baseline PR1.
- [ ] `sentrux check` → exit 0.
- [ ] Новое правило `[[boundaries]]` в `.sentrux/rules.toml` добавлено.
- [ ] PR-описание: скриншоты LoginButton, LoginDialog, UsersPanel, RolesPanel.
- [ ] Все новые файлы содержат docstring на русском языке.
- [ ] `password_hash` не появляется ни в одном логе/repr/snapshot (audit grep).
