"""state_store_manager.py — Серверная часть StateStore.

StateStoreManager живёт в ProcessManagerProcess и обрабатывает
IPC-сообщения от процессов: state.set, state.get, state.subscribe и т.д.

НЕ наследует ProcessModule — это компонент, встраиваемый в ProcessManagerProcess.
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

from ...base_manager import BaseManager, ObservableMixin

from ..core.delta import STATE_ENVELOPE_MARKER
from ..core.subscription_manager import SubscriptionManager
from ..core.tree_store import TreeStore
from ..interfaces import IRouter, IStateStoreManager
from ..middleware.base import MiddlewarePipeline, StateMiddleware
from ..middleware.throttle import ThrottleMiddleware
from .delta_dispatcher import DeltaDispatcher


class StateStoreManager(BaseManager, ObservableMixin, IStateStoreManager):
    """Серверная часть StateStore. Живёт в ProcessManagerProcess.

    Содержит TreeStore + SubscriptionManager + DeltaDispatcher.
    Обрабатывает IPC-сообщения от процессов:
    - state.set -> TreeStore.set() -> dispatch deltas
    - state.merge -> TreeStore.merge() -> dispatch deltas
    - state.get -> TreeStore.get() -> response
    - state.subscribe -> SubscriptionManager.subscribe()
    - state.unsubscribe -> SubscriptionManager.unsubscribe()
    """

    def __init__(
        self,
        router: IRouter | None = None,
        initial_state: dict[str, Any] | None = None,
        manager_name: str = "StateStoreManager",
        logger: Any = None,
        stats: Any = None,
        auto_register_ipc: bool = True,
    ) -> None:
        """
        Args:
            router: реализация IRouter для IPC (None допустимо для тестов).
            initial_state: начальное состояние дерева.
            manager_name: имя менеджера для BaseManager.
            logger: LoggerManager или ObservableMixin-совместимый объект.
            stats: StatsManager или ObservableMixin-совместимый объект.
            auto_register_ipc: регистрировать ли inbound IPC-обработчики state.*
                напрямую (RAW) в event_dispatcher при initialize(). True —
                legacy-путь (тесты, in_memory_router). False (prod) — state.*
                регистрируются как команды CommandManager (register_commands), а
                kind-router в RouterManager.receive() диспатчит их туда по
                type=="command"; reply делает транспорт по request_id (P4.4.1/B2).
        """
        BaseManager.__init__(self, manager_name=manager_name)
        ObservableMixin.__init__(self, managers={"logger": logger, "stats": stats})
        self._store = TreeStore(initial=initial_state)
        self._subs = SubscriptionManager()
        self._dispatcher = DeltaDispatcher(
            subscription_mgr=self._subs,
            router=router,
            sender_name="StateStore",
            logger=self,
        )
        self._pipeline = MiddlewarePipeline()
        self._router = router
        self._auto_register_ipc = auto_register_ipc

    @property
    def pipeline(self) -> MiddlewarePipeline:
        """Доступ к middleware pipeline (для тестов и конфигурации)."""
        return self._pipeline

    def use(self, middleware: StateMiddleware) -> None:
        """Добавить middleware в pipeline.

        Args:
            middleware: экземпляр StateMiddleware.
        """
        self._pipeline.use(middleware)

    def get_middleware(self, name: str) -> StateMiddleware | None:
        """Вернуть живой middleware из pipeline по имени (или None).

        Тонкая обёртка над ``MiddlewarePipeline.get`` — точка доступа для
        рантайм-команд (PC 0.1/Фаза 3), которым нужно достать конкретный
        middleware (напр. ``ThrottleMiddleware``) и позвать его мутатор.

        Args:
            name: имя middleware (например ``"throttle"``).

        Returns:
            Экземпляр StateMiddleware, если зарегистрирован; иначе None.
        """
        return self._pipeline.get(name)

    @property
    def store(self) -> TreeStore:
        """Доступ к внутреннему TreeStore (для тестов и bootstrap)."""
        return self._store

    @property
    def subscription_manager(self) -> SubscriptionManager:
        """Доступ к SubscriptionManager (для тестов)."""
        return self._subs

    @property
    def dispatcher(self) -> DeltaDispatcher:
        """Доступ к DeltaDispatcher (для тестов)."""
        return self._dispatcher

    def initialize(self) -> bool:
        """Инициализация. Регистрирует IPC-обработчики если router задан.

        Returns:
            True если инициализация успешна.
        """
        if self._router is not None and self._auto_register_ipc:
            self.register_message_handlers(self._router)

        self.is_initialized = True
        self._log_info("StateStoreManager инициализирован")
        return True

    def shutdown(self) -> bool:
        """Остановка. Отписывает все подписки.

        Returns:
            True если остановка успешна.
        """
        total = 0
        for subscriber in self._subs.subscribers():
            total += self._subs.unsubscribe_all(subscriber)

        self.is_initialized = False
        self._log_info(f"StateStoreManager остановлен, отписано подписок: {total}")
        return True

    # -------------------------------------------------------------------
    # Извлечение данных из IPC-сообщения
    # -------------------------------------------------------------------

    @staticmethod
    def _extract_data(msg: dict) -> dict:
        """Извлечь данные из IPC-сообщения.

        Совместимость с CommandManager (data-поле) и прямыми dict-сообщениями.
        Если в msg есть ключ 'data' и это dict — берём оттуда.
        Иначе — сам msg является данными.

        Args:
            msg: входящее IPC-сообщение.

        Returns:
            dict с данными запроса.
        """
        data = msg.get("data")
        if isinstance(data, dict):
            return data
        return msg

    # -------------------------------------------------------------------
    # IPC-обработчики
    # -------------------------------------------------------------------

    def handle_state_set(self, msg: dict) -> dict | None:
        """Обработчик state.set: установить значение по пути.

        msg.data: {path: str, value: Any, source: str}

        Returns:
            dict с результатом операции или ошибкой.
        """
        data = self._extract_data(msg)
        path = data.get("path")
        value = data.get("value")
        source = data.get("source", "")

        # Валидация обязательных полей
        if not path or not isinstance(path, str):
            return {"status": "error", "error": "Поле 'path' обязательно и должно быть строкой"}

        try:
            # --- MIDDLEWARE BEFORE ---
            proceed, value, context = self._pipeline.run_before_set(path, value, source)
            if not proceed:
                return {
                    "status": "rejected",
                    "path": path,
                    "reason": context.get("rejection_reason", "middleware"),
                }

            delta = self._store.set(path, value, source=source)
            if delta is not None:
                # --- MIDDLEWARE AFTER ---
                self._pipeline.run_after_set(delta, context)
                # Рассылка дельт подписчикам
                self._dispatcher.dispatch_single(delta)
                return {"status": "ok", "path": path, "changed": True}
            return {"status": "ok", "path": path, "changed": False}
        except (ValueError, TypeError) as exc:
            self._log_warning(f"state.set ошибка: {exc}")
            return {"status": "error", "error": str(exc)}

    def handle_state_merge(self, msg: dict) -> dict | None:
        """Обработчик state.merge: глубокий merge dict в поддерево.

        msg.data: {path: str, data: dict, source: str}

        Returns:
            dict с результатом операции или ошибкой.
        """
        # Явный маркер конверта (Ф7 G.2 шаг 4, RS-ревью 2026-07-13) — вместо
        # shape-sniffing по наличию top-level "path"/"data". Конверт команды —
        # ``{path, data, source, STATE_ENVELOPE_MARKER: True}``, где ВЛОЖЕННЫЙ
        # "data" = merge-payload. Билдер (``StateProxy.merge``) ставит маркер;
        # получатель НЕ гадает по содержимому. Два входа:
        #   (B) развёрнутый конверт (expects_full_message=False): маркер на верхнем
        #       уровне самого msg → msg И есть конверт.
        #   (A) full message (router, expects_full_message=True): конверт вложен в
        #       msg["data"] → разворачиваем один раз (маркер сиблингом внутри).
        # Прежний риск снят: будущий отправитель с top-level "path" без маркера
        # НЕ будет принят за конверт (тихого merge конверта как payload не будет).
        if msg.get(STATE_ENVELOPE_MARKER):
            envelope = msg  # (B): msg — помеченный конверт, payload = msg["data"]
        else:
            inner = msg.get("data")
            envelope = inner if isinstance(inner, dict) else msg  # (A): развернуть один раз
        path = envelope.get("path", "")
        merge_data = envelope.get("data")
        source = envelope.get("source", "")

        # F2 (ревью G.2): path обязателен и непустой (симметрично handle_state_set) —
        # маркированный конверт с пустым/отсутствующим path НЕ мёржим в корень, а
        # громко отклоняем (иначе тихий merge в root затирает всё дерево).
        if not path or not isinstance(path, str):
            return {"status": "error", "error": "Поле 'path' обязательно и должно быть строкой"}

        if merge_data is None or not isinstance(merge_data, dict):
            return {"status": "error", "error": "Поле 'data' обязательно и должно быть dict"}

        try:
            # --- MIDDLEWARE BEFORE ---
            proceed, merge_data, context = self._pipeline.run_before_merge(path, merge_data, source)
            if not proceed:
                return {
                    "status": "rejected",
                    "path": path,
                    "reason": context.get("rejection_reason", "middleware"),
                }

            deltas = self._store.merge(path, merge_data, source=source)
            if deltas:
                # --- MIDDLEWARE AFTER ---
                self._pipeline.run_after_merge(deltas, context)
                self._dispatcher.dispatch(deltas)
            return {
                "status": "ok",
                "path": path,
                "changes_count": len(deltas),
            }
        except (ValueError, TypeError) as exc:
            self._log_warning(f"state.merge ошибка: {exc}")
            return {"status": "error", "error": str(exc)}

    def handle_state_delete(self, msg: dict) -> dict | None:
        """Обработчик state.delete: удалить узел/поддерево по пути.

        msg.data: {path: str, source: str}

        Нужен для честной очистки дерева при cleanup процесса (RS-2/Ж-2/LP-4):
        после switch снятые процессы не должны висеть как ``running`` — их
        поддерево ``processes.<name>`` удаляется единой точкой очистки
        (``PM._cleanup_process_resources``). Идемпотентен: удаление отсутствующего
        узла — не ошибка (``changed: False``).

        При реальном удалении поддерева заодно чистит тайминги/pending
        ``ThrottleMiddleware`` под этим же префиксом (:meth:`ThrottleMiddleware.prune`,
        Task 3.4, находка G) — иначе они висели бы в словарях бессрочно после
        того, как процесс/его поддерево исчезли из дерева.

        Returns:
            dict с результатом операции или ошибкой.
        """
        data = self._extract_data(msg)
        path = data.get("path", "")
        source = data.get("source", "")

        if not path or not isinstance(path, str):
            return {"status": "error", "error": "Поле 'path' обязательно и должно быть строкой"}

        try:
            delta = self._store.delete(path, source=source)
            if delta is not None:
                self._dispatcher.dispatch_single(delta)
                throttle = self.get_middleware("throttle")
                if isinstance(throttle, ThrottleMiddleware):
                    throttle.prune(path)
                return {"status": "ok", "path": path, "changed": True}
            return {"status": "ok", "path": path, "changed": False}
        except (ValueError, TypeError) as exc:
            self._log_warning(f"state.delete ошибка: {exc}")
            return {"status": "error", "error": str(exc)}

    def handle_state_get(self, msg: dict) -> dict:
        """Обработчик state.get: прочитать значение по пути.

        msg.data: {path: str, request_id: str}

        Returns:
            dict с value и request_id, или ошибкой.
        """
        data = self._extract_data(msg)
        path = data.get("path", "")
        request_id = data.get("request_id", "")

        try:
            value = self._store.get(path)
            return {
                "status": "ok",
                "request_id": request_id,
                "value": value,
            }
        except KeyError:
            return {
                "status": "error",
                "request_id": request_id,
                "error": f"Путь не существует: '{path}'",
            }

    def handle_state_get_subtree(self, msg: dict) -> dict:
        """Обработчик state.get_subtree: прочитать поддерево по пути.

        msg.data: {path: str, request_id: str}
            ИЛИ (Ф4.9b, watch-from-revision resync): {paths: list[str], request_id: str} —
            список glob-паттернов (те же, что в state.subscribe). Используется
            StateProxy для resync при обнаруженном разрыве revision — переиспользует
            этот же канал вместо отдельной команды (см. ADR-SS-015), т.к.
            семантика идентична: "дай мне текущее состояние поддерева(ьев)".

        Returns:
            dict с value (поддерево) и request_id, или ошибкой.
            'revision' (Ф4.9a) — текущая revision дерева на момент ответа,
            аддитивное поле, старые клиенты его игнорируют.

        Ф4.9-фикс (MED-5, ревью 2026-07-11): value и revision читаются АТОМАРНО
        через TreeStore.snapshot_with_revision()/get_subtree_with_revision() —
        одна блокировка на оба чтения. Раньше это были два отдельных обращения
        к TreeStore (снимок, потом отдельно revision) — между ними другой поток
        мог смутировать дерево, и клиент получал revision новее, чем то, что
        реально попало в snapshot (resync считал кэш "сошедшимся" преждевременно).
        """
        data = self._extract_data(msg)
        path = data.get("path", "")
        paths = data.get("paths")
        request_id = data.get("request_id", "")

        try:
            if paths:
                # resync по нескольким glob-паттернам: снимок объединяет все
                # поддеревья, совпадающие хотя бы с одним паттерном.
                value, revision = self._store.snapshot_with_revision(paths=list(paths))
            else:
                value, revision = self._store.get_subtree_with_revision(path)
            return {
                "status": "ok",
                "request_id": request_id,
                "value": value,
                "revision": revision,
            }
        except (KeyError, TypeError) as exc:
            return {
                "status": "error",
                "request_id": request_id,
                "error": str(exc),
            }

    def handle_state_subscribe(self, msg: dict) -> dict:
        """Обработчик state.subscribe: подписаться на изменения.

        msg.data: {pattern: str, subscriber: str, exclude_sources?: list[str]}

        Returns:
            dict с sub_id или ошибкой.
        """
        data = self._extract_data(msg)
        pattern = data.get("pattern")
        subscriber = data.get("subscriber")
        exclude_sources = data.get("exclude_sources", ())

        if not pattern or not isinstance(pattern, str):
            return {"status": "error", "error": "Поле 'pattern' обязательно"}
        if not subscriber or not isinstance(subscriber, str):
            return {"status": "error", "error": "Поле 'subscriber' обязательно"}

        # Приводим exclude_sources к tuple
        if isinstance(exclude_sources, list):
            exclude_sources = tuple(exclude_sources)

        sub_id = self._subs.subscribe(
            pattern=pattern,
            subscriber=subscriber,
            exclude_sources=exclude_sources,
        )
        self._log_debug(f"Подписка создана: sub_id={sub_id}, subscriber={subscriber}, pattern={pattern}")

        # Initial-state replay: адресно отправить новому подписчику снимок
        # текущих значений, матчащих pattern. Без этого подписчик, подключившийся
        # ПОСЛЕ публикации разовых дельт (типичный GUI: status публикуется один раз
        # при старте процесса), никогда их не увидит — только будущие изменения.
        self._replay_initial_state(pattern, subscriber)

        return {"status": "ok", "sub_id": sub_id}

    def _replay_initial_state(self, pattern: str, subscriber: str) -> None:
        """Отправить подписчику снимок текущих листовых значений store по pattern.

        Решает startup-race реактивной телеметрии: значения, опубликованные ДО
        подписки, иначе теряются для нового подписчика (нет реплея). Шлём адресно
        ТОЛЬКО новому подписчику (не broadcast). Только листья (не промежуточные
        dict-узлы) — клиентские bindings матчат конкретные пути. Best-effort:
        сбой реплея не ломает саму подписку.

        Args:
            pattern: glob-паттерн подписки.
            subscriber: имя процесса-подписчика (адрес доставки).
        """
        try:
            from ..core.delta import MISSING, Delta

            # Адресный реплей (Ф-GUI-read-model 0.3): копируем не всё дерево, а
            # только поддерево статического префикса паттерна — каждый путь,
            # матчащий pattern, обязан начинаться с этого префикса. Множество
            # (path, value) эквивалентно прежнему get_subtree("") + iter_matches.
            pairs = list(self._iter_replay_pairs(pattern))
            # revision реплея (Ф4.9, ADR-SS-014) — фиксируем ПОСЛЕ снимка,
            # т.к. store.revision читается под собственным локом и может уйти
            # вперёд; для реплея это не критично (best-effort, как и весь метод).
            replay_revision = self._store.revision
            deltas = [
                Delta(
                    path=p,
                    old_value=MISSING,
                    new_value=v,
                    source="__replay__",
                    revision=replay_revision,
                )
                for p, v in pairs
                if not isinstance(v, dict)
            ]
            if deltas:
                self._dispatcher._send_state_changed(subscriber, deltas)
                self._log_debug(f"Initial replay: {len(deltas)} значений → '{subscriber}' (pattern={pattern})")
        except Exception as exc:  # nosec B110 — реплей best-effort, не критичен для подписки
            self._log_warning(f"Initial replay для '{subscriber}' (pattern={pattern}) не удался: {exc}")

    def _iter_replay_pairs(self, pattern: str) -> Iterator[tuple[str, Any]]:
        """Пары (полный_путь, значение) для реплея pattern — по статическому префиксу.

        Эквивалент прежнего ``iter_matches(get_subtree(''), pattern)``, но
        копирует только поддерево статического префикса (до первого wildcard),
        а не всё дерево. Корректность: каждый путь, матчащий pattern, начинается
        с префикса (литеральные сегменты матчатся буквально), значит матч
        pattern по всему дереву ≡ матч остатка по поддереву префикса с обратным
        приклеиванием префикса к путям.

        Три случая:
          - prefix == '' (pattern с wildcard'а): поддерево = всё дерево, обычный
            iter_matches по абсолютному pattern.
          - prefix == pattern (нет wildcard): pattern адресует ровно один узел —
            берём его значение точечно (get), без копии поддерева.
          - prefix — собственный префикс (есть wildcard после литералов):
            берём поддерево prefix, матчим ОСТАТОК pattern, приклеиваем prefix.

        Отсутствующий префикс / префикс-лист → пустой результат (как старый
        код: pattern по такому дереву ничего не матчил).

        Yields:
            Кортежи (точечный_путь, значение). Как и прежде, промежуточные
            dict-узлы отсеиваются вызывающим (`if not isinstance(v, dict)`).
        """
        from ..core.glob_walker import iter_matches
        from ..core.subscription_manager import static_prefix

        _missing = object()  # локальный sentinel «путь отсутствует»

        prefix = static_prefix(pattern)

        if prefix == "":
            # Паттерн начинается с wildcard — префикса нет, нужен весь корень.
            root = self._store.get_subtree("")  # thread-safe deep-copy всего дерева
            yield from iter_matches(root, pattern)
            return

        if prefix == pattern:
            # Полностью статический паттерн: ровно один целевой путь. Забираем
            # значение точечно вместо копирования поддерева. Отсутствует → ничего.
            value = self._store.get(pattern, default=_missing)
            if value is not _missing:
                yield (pattern, value)
            return

        # Собственный префикс: копируем только поддерево префикса и матчим остаток.
        try:
            subtree = self._store.get_subtree(prefix)
        except (KeyError, TypeError):
            # Префикс отсутствует или указывает на лист — pattern ничего не матчит.
            return
        prefix_len = len(prefix.split("."))
        remainder = ".".join(pattern.split(".")[prefix_len:])
        for relpath, value in iter_matches(subtree, remainder):
            full = f"{prefix}.{relpath}" if relpath else prefix
            yield (full, value)

    def handle_state_unsubscribe(self, msg: dict) -> dict:
        """Обработчик state.unsubscribe: отписаться от подписки.

        msg.data: {sub_id: str}

        Returns:
            dict с success.
        """
        data = self._extract_data(msg)
        sub_id = data.get("sub_id")

        if not sub_id:
            return {"status": "error", "error": "Поле 'sub_id' обязательно"}

        success = self._subs.unsubscribe(sub_id)
        return {"status": "ok", "success": success}

    def handle_state_unsubscribe_all(self, msg: dict) -> dict:
        """Обработчик state.unsubscribe_all: отписать все подписки процесса.

        msg.data: {subscriber: str}

        Returns:
            dict с count удалённых подписок.
        """
        data = self._extract_data(msg)
        subscriber = data.get("subscriber")

        if not subscriber:
            return {"status": "error", "error": "Поле 'subscriber' обязательно"}

        count = self._subs.unsubscribe_all(subscriber)
        return {"status": "ok", "count": count}

    # -------------------------------------------------------------------
    # Регистрация в CommandManager и RouterManager
    # -------------------------------------------------------------------

    def register_commands(self, command_manager: Any) -> None:
        """Регистрирует все обработчики в CommandManager ProcessManager'а.

        Вызывается из ProcessManagerProcess при инициализации.

        Args:
            command_manager: экземпляр CommandManager.
        """
        commands = {
            "state.set": (self.handle_state_set, "Установить значение в дереве"),
            "state.merge": (self.handle_state_merge, "Глубокий merge dict в поддерево"),
            "state.delete": (self.handle_state_delete, "Удалить узел/поддерево по пути"),
            "state.get": (self.handle_state_get, "Прочитать значение из дерева"),
            "state.get_subtree": (self.handle_state_get_subtree, "Прочитать поддерево"),
            "state.subscribe": (self.handle_state_subscribe, "Подписаться на изменения"),
            "state.unsubscribe": (self.handle_state_unsubscribe, "Отписаться от подписки"),
            "state.unsubscribe_all": (
                self.handle_state_unsubscribe_all,
                "Отписать все подписки процесса",
            ),
        }

        for name, (handler, description) in commands.items():
            command_manager.register_command(
                name,
                handler,
                metadata={"description": description},
                tags=["state_store"],
            )

        self._log_info(f"StateStoreManager: зарегистрировано {len(commands)} команд в CommandManager")

    def register_message_handlers(self, router: IRouter) -> None:
        """Регистрирует message handlers в Router.

        Args:
            router: реализация IRouter (RouterManager или InMemoryRouter в тестах).
        """
        handlers = {
            "state.set": self.handle_state_set,
            "state.merge": self.handle_state_merge,
            "state.delete": self.handle_state_delete,
            "state.get": self.handle_state_get,
            "state.get_subtree": self.handle_state_get_subtree,
            "state.subscribe": self.handle_state_subscribe,
            "state.unsubscribe": self.handle_state_unsubscribe,
            "state.unsubscribe_all": self.handle_state_unsubscribe_all,
        }

        for key, handler in handlers.items():
            router.register_message_handler(key, handler, expects_full_message=True)

        self._log_info(f"StateStoreManager: зарегистрировано {len(handlers)} обработчиков в Router")
