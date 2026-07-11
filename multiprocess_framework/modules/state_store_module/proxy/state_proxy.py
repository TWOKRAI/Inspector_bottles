"""state_proxy.py — Клиент StateStore для ProcessModule.

StateProxy живёт в каждом ProcessModule. Общается с StateStoreManager
через IPC (любой router, реализующий IRouter Protocol).
Кэширует подписанные пути для быстрого чтения.

IPC-протокол (Dict at Boundary):
  Отправка:  state.set / state.merge / state.subscribe / state.unsubscribe / state.get
  Получение: state.changed → on_state_changed()

ADR-SS-002: server_target — конфигурируемое имя процесса-сервера StateStore.
По умолчанию "ProcessManager" — для обратной совместимости.
"""

from __future__ import annotations

import uuid
from typing import Any, Callable

from ...base_manager import BaseManager, ObservableMixin
from ..core import iter_matches, match_pattern, split_pattern
from ..core.delta import MISSING, Delta
from ..interfaces import IRouter, IStateProxy

# Sentinel для отличия "default не передан" от None
_SENTINEL = object()


class StateProxy(BaseManager, ObservableMixin, IStateProxy):
    """Клиент StateStore. Создаётся в каждом ProcessModule.

    Общается с StateStoreManager через IPC (любой IRouter).
    Кэширует подписанные пути для быстрого чтения.

    Пример использования:
        proxy = StateProxy("camera_0", router=router, server_target="ProcessManager")
        router.register_message_handler("state.changed", proxy.on_state_changed)

        # Запись
        proxy.set("cameras.0.config.fps", 30)

        # Подписка
        proxy.subscribe("cameras.0.**", my_callback)

        # Чтение (из кэша или IPC fallback)
        fps = proxy.get("cameras.0.config.fps", default=25)
    """

    def __init__(
        self,
        process_name: str,
        router: IRouter | None = None,
        server_target: str = "ProcessManager",
        manager_name: str | None = None,
        logger: Any = None,
    ) -> None:
        """
        Args:
            process_name: имя этого процесса (используется как sender и subscriber).
            router: реализация IRouter для IPC (None допустимо для тестов).
            server_target: имя процесса, в котором живёт StateStoreManager.
                По умолчанию "ProcessManager" (обратная совместимость, ADR-SS-002).
            manager_name: имя для BaseManager (по умолчанию StateProxy:<process_name>).
            logger: LoggerManager или ObservableMixin-совместимый объект.
        """
        BaseManager.__init__(self, manager_name=manager_name or f"StateProxy:{process_name}")
        ObservableMixin.__init__(self, managers={"logger": logger})
        self._process_name = process_name
        self._router = router
        self._server_target = server_target
        # Кэш подписанных данных: path → значение
        self._cache: dict[str, Any] = {}
        # Реестр callbacks: sub_id → список Callable[[list[Delta]], None]
        self._callbacks: dict[str, list[Callable]] = {}
        # sub_id → pattern (нужен для фильтрации входящих дельт по подписке)
        self._sub_patterns: dict[str, str] = {}
        # Список активных sub_id для shutdown cleanup
        self._sub_ids: list[str] = []
        # ensure_subscription refcount: pattern → server sub_id, pattern → счётчик.
        # Дедуп идемпотентных подписок: N подписчиков на один pattern → одна
        # серверная подписка, снимается при обнулении refcount.
        self._pattern_sub_id: dict[str, str] = {}
        self._pattern_refcount: dict[str, int] = {}
        # Обратная карта sub_id → pattern: O(1)-очистка ensure-реестра в
        # unsubscribe без линейного скана (5.20 review #10).
        self._sub_id_pattern: dict[str, str] = {}
        # Watch-from-revision (Ф4.9b, ADR-SS-014/015): revision последнего
        # успешно применённого пакета state.changed. None — ещё не было ни
        # одного пакета с revision (либо proxy только создан, либо все
        # входящие пакеты были от старых отправителей без revision).
        self._last_revision: int | None = None

    def initialize(self) -> bool:
        self.is_initialized = True
        return True

    # -------------------------------------------------------------------
    # Свойства
    # -------------------------------------------------------------------

    @property
    def process_name(self) -> str:
        """Имя этого процесса."""
        return self._process_name

    @property
    def cache(self) -> dict[str, Any]:
        """Копия текущего кэша (только для чтения/тестов)."""
        return dict(self._cache)

    # -------------------------------------------------------------------
    # Запись
    # -------------------------------------------------------------------

    def set(self, path: str, value: Any) -> None:
        """Отправить state.set в StateStoreManager через IPC.

        Args:
            path: путь к узлу, например 'cameras.0.config.fps'.
            value: новое значение (должно быть pickle-совместимым).
        """
        msg = {
            "type": "command",
            "sender": self._process_name,
            "targets": [self._server_target],
            "command": "state.set",
            "data": {
                "path": path,
                "value": value,
                "source": self._process_name,
            },
        }
        self._send(msg)

    def merge(self, path: str, data: dict) -> None:
        """Отправить state.merge в StateStoreManager через IPC.

        Args:
            path: путь к поддереву.
            data: dict с ключами и значениями для слияния.
        """
        msg = {
            "type": "command",
            "sender": self._process_name,
            "targets": [self._server_target],
            "command": "state.merge",
            "data": {
                "path": path,
                "data": data,
                "source": self._process_name,
            },
        }
        self._send(msg)

    # -------------------------------------------------------------------
    # Чтение
    # -------------------------------------------------------------------

    def get(self, path: str, default: Any = _SENTINEL) -> Any:
        """Чтение значения. Сначала из кэша, потом IPC fallback.

        Args:
            path: путь к узлу.
            default: значение по умолчанию если путь не найден.

        Returns:
            Значение из кэша или IPC.

        Raises:
            KeyError: если путь не в кэше, default не передан, и router=None.
        """
        # Сначала проверяем кэш
        if path in self._cache:
            return self._cache[path]

        # Fallback: IPC-запрос
        if self._router is not None:
            request_id = str(uuid.uuid4())
            msg = {
                "type": "command",
                "sender": self._process_name,
                "targets": [self._server_target],
                "command": "state.get",
                "data": {
                    "path": path,
                    "request_id": request_id,
                },
            }
            response = self._send_sync(msg)
            if response is not None and response.get("status") == "ok":
                return response["value"]

        # Возвращаем default или бросаем KeyError
        if default is not _SENTINEL:
            return default

        raise KeyError(f"Путь не найден в кэше: '{path}' (router={self._router!r})")

    def get_subtree(self, path: str) -> dict:
        """Запросить поддерево через IPC.

        Args:
            path: путь к поддереву.

        Returns:
            dict с содержимым поддерева, или пустой dict при ошибке/нет router.
        """
        if self._router is None:
            return {}

        request_id = str(uuid.uuid4())
        msg = {
            "type": "command",
            "sender": self._process_name,
            "targets": [self._server_target],
            "command": "state.get_subtree",
            "data": {
                "path": path,
                "request_id": request_id,
            },
        }
        response = self._send_sync(msg)
        if response is not None and response.get("status") == "ok":
            value = response.get("value", {})
            return value if isinstance(value, dict) else {}
        return {}

    # -------------------------------------------------------------------
    # Подписки
    # -------------------------------------------------------------------

    def subscribe(
        self,
        pattern: str,
        callback: Callable[[list[Delta]], None],
        exclude_self: bool = True,
    ) -> str:
        """Подписаться на изменения по паттерну.

        1. Отправляет state.subscribe в StateStoreManager через IPC.
        2. Регистрирует callback локально по sub_id.
        3. exclude_self=True → exclude_sources=(self._process_name,).

        Args:
            pattern: glob-паттерн пути (например 'cameras.*.config.*').
            callback: функция, вызываемая при получении дельт.
            exclude_self: исключить изменения от этого же процесса.

        Returns:
            sub_id — строка-идентификатор подписки.
        """
        exclude_sources: list[str] = [self._process_name] if exclude_self else []

        # Генерируем локальный sub_id — он может быть переопределён ответом сервера
        local_sub_id = str(uuid.uuid4())

        msg = {
            "type": "command",
            "sender": self._process_name,
            "targets": [self._server_target],
            "command": "state.subscribe",
            "data": {
                "pattern": pattern,
                "subscriber": self._process_name,
                "exclude_sources": exclude_sources,
            },
        }

        # Если есть router — пробуем получить sub_id от сервера.
        # Если ответа нет, сервер вернул error или sub_id отсутствует — логируем
        # warning. Это значит, что серверная подписка не создана (callback не
        # сработает), но локальный sub_id выдаём (чтобы клиентский код не падал).
        if self._router is not None:
            response = self._send_sync(msg)
            if response is None:
                self._log_warning(
                    f"StateProxy '{self._process_name}': подписка на '{pattern}' "
                    "не подтверждена сервером (response=None) — серверная подписка "
                    "не создана, локальный callback срабатывать не будет"
                )
            elif response.get("status") != "ok":
                self._log_warning(
                    f"StateProxy '{self._process_name}': подписка на '{pattern}' "
                    f"отклонена сервером: {response.get('error', response)}"
                )
            else:
                server_sub_id = response.get("sub_id")
                if server_sub_id:
                    local_sub_id = server_sub_id
                else:
                    self._log_warning(
                        f"StateProxy '{self._process_name}': подписка на '{pattern}' не вернула sub_id от сервера"
                    )
        else:
            self._log_debug(f"StateProxy.subscribe: router=None, подписка '{pattern}' только локальная")

        # Регистрируем callback локально
        self._callbacks[local_sub_id] = [callback]
        self._sub_patterns[local_sub_id] = pattern
        self._sub_ids.append(local_sub_id)

        self._log_debug(f"StateProxy '{self._process_name}': подписка sub_id={local_sub_id}, pattern={pattern}")
        return local_sub_id

    def unsubscribe(self, sub_id: str) -> None:
        """Отписаться. Удаляет локальный callback + IPC unsubscribe.

        Args:
            sub_id: идентификатор подписки, полученный из subscribe().
        """
        # Удаляем локальный callback
        self._callbacks.pop(sub_id, None)
        self._sub_patterns.pop(sub_id, None)
        if sub_id in self._sub_ids:
            self._sub_ids.remove(sub_id)

        # Чистим refcount-реестр, если этот sub_id был ensure-подпиской —
        # иначе прямой unsubscribe оставил бы висячий pattern → refcount.
        # O(1) через обратную карту (не линейный скан на каждый unsubscribe).
        pat = self._sub_id_pattern.pop(sub_id, None)
        if pat is not None:
            self._pattern_sub_id.pop(pat, None)
            self._pattern_refcount.pop(pat, None)

        # IPC-отписка
        if self._router is not None:
            msg = {
                "type": "command",
                "sender": self._process_name,
                "targets": [self._server_target],
                "command": "state.unsubscribe",
                "data": {"sub_id": sub_id},
            }
            self._send(msg)

    def ensure_subscription(
        self,
        pattern: str,
        callback: Callable[[list[Delta]], None] | None = None,
        exclude_self: bool = True,
    ) -> str:
        """Идемпотентная подписка на pattern с refcount.

        Если на этот pattern уже есть подписка — переиспользует её серверный
        sub_id (второй state.subscribe НЕ отправляется), добавляет callback (если
        задан) и инкрементит refcount. Иначе создаёт новую подписку.

        Закрывает класс ошибок «панель мертва, забыли wildcard»: потребитель
        (например GUI-биндинг) вызывает ensure_subscription на свой pattern —
        подписка гарантированно существует, дубли схлопываются по refcount.
        Снятие — release_subscription с тем же pattern.

        Args:
            pattern: glob-паттерн пути.
            callback: опциональный callback (для GUI-доставки через delta_sink
                можно не передавать — важно лишь наличие серверной подписки).
            exclude_self: исключить изменения от этого же процесса (учитывается
                только при СОЗДАНИИ подписки; для существующей — first-wins).

        Returns:
            sub_id серверной подписки (общий для всех ensure на этот pattern).
        """
        existing = self._pattern_sub_id.get(pattern)
        if existing is not None:
            if callback is not None:
                self._callbacks.setdefault(existing, []).append(callback)
            self._pattern_refcount[pattern] = self._pattern_refcount.get(pattern, 0) + 1
            return existing

        cb = callback if callback is not None else (lambda _deltas: None)
        sub_id = self.subscribe(pattern, cb, exclude_self=exclude_self)
        self._pattern_sub_id[pattern] = sub_id
        self._pattern_refcount[pattern] = 1
        self._sub_id_pattern[sub_id] = pattern
        return sub_id

    def release_subscription(
        self,
        pattern: str,
        callback: Callable[[list[Delta]], None] | None = None,
    ) -> bool:
        """Уменьшить refcount ensure-подписки; при 0 — снять серверную подписку.

        Идемпотентна: release неизвестного pattern — no-op (False).

        Args:
            pattern: glob-паттерн, ранее переданный в ensure_subscription.
            callback: если задан — снять именно этот callback из подписки.

        Returns:
            True если серверная подписка снята (refcount обнулился), иначе False.
        """
        sub_id = self._pattern_sub_id.get(pattern)
        if sub_id is None:
            return False

        if callback is not None:
            cbs = self._callbacks.get(sub_id)
            if cbs is not None:
                try:
                    cbs.remove(callback)
                except ValueError:
                    pass

        self._pattern_refcount[pattern] = self._pattern_refcount.get(pattern, 0) - 1
        if self._pattern_refcount[pattern] <= 0:
            # unsubscribe сам подчистит _pattern_sub_id/_pattern_refcount
            self.unsubscribe(sub_id)
            return True
        return False

    # -------------------------------------------------------------------
    # Обработка входящих сообщений
    # -------------------------------------------------------------------

    def on_state_changed(self, msg: dict) -> None:
        """Вызывается при получении state.changed от StateStoreManager.

        Регистрируется как message_handler в Router:
            router.register_message_handler("state.changed", proxy.on_state_changed)

        1. Десериализует дельты из msg["data"]["deltas"].
        2. Проверяет непрерывность revision (Ф4.9b) — при разрыве ресинкается
           и ЗАВЕРШАЕТ обработку (кэш уже актуализирован свежим снапшотом,
           дельты устаревшего пакета не применяются и коллбеки не зовутся).
        3. Обновляет кэш.
        4. Вызывает все зарегистрированные callbacks.

        Args:
            msg: IPC-сообщение с полем data.deltas.
        """
        deltas = self._deserialize_deltas(msg)
        if not deltas:
            return

        envelope_revision = msg.get("data", {}).get("revision")
        if self._check_and_handle_revision_gap(envelope_revision):
            return

        self._update_cache(deltas)
        self._invoke_callbacks(deltas)

    # -------------------------------------------------------------------
    # Watch-from-revision + resync (Ф4.9b, ADR-SS-014/015)
    # -------------------------------------------------------------------

    def _check_and_handle_revision_gap(self, envelope_revision: Any) -> bool:
        """Проверить непрерывность revision пакета, при разрыве — ресинк.

        Модель: клиент ожидает, что revision КОНВЕРТА (msg["data"]["revision"],
        проставленная DeltaDispatcher как max revision дельт пакета) растёт
        строго на 1 от пакета к пакету. Разрыв (пришла revision N+k при
        ожидаемой N+1) означает, что клиент пропустил хотя бы один пакет
        state.changed — вызывается resync(). Сверяемся именно с revision
        конверта, а не отдельных дельт: конверт — единица доставки, и именно
        её потерю нужно детектить (см. DeltaDispatcher._send_state_changed).

        Fail-open (Ф4.9a): envelope_revision is None → отправитель не
        поддерживает revision (старый формат) — проверка пропускается,
        _last_revision не трогается, обработка идёт по старому пути.

        Известное ограничение (ADR-SS-015): revision — глобальный счётчик
        дерева, а не per-pattern. Если этот процесс подписан на несколько
        паттернов и где-то ВНЕ его подписок происходят мутации, revision
        всё равно растёт — это может вызвать ложный resync (разрыв, которого
        реально не было для ЭТОГО подписчика). Ресинк идемпотентен и дёшев
        (просто досрочно сверяет кэш с сервером), поэтому ложные срабатывания
        безопасны, лишь не бесплатны.

        Args:
            envelope_revision: msg["data"]["revision"] (int) или None.

        Returns:
            True — обнаружен разрыв, resync запущен, кэш уже актуализирован
            (дельты ЭТОГО пакета применять/коллбеки звать не нужно).
            False — либо revision отсутствует (fail-open), либо разрыва нет
            (нормальная обработка пакета продолжается как раньше).
        """
        if envelope_revision is None:
            return False

        if self._last_revision is None:
            # Первый пакет с revision — база отсчёта, разрыв не проверяем.
            self._last_revision = envelope_revision
            return False

        expected = self._last_revision + 1
        if envelope_revision == expected:
            self._last_revision = envelope_revision
            return False

        self._log_warning(
            f"StateProxy '{self._process_name}': разрыв revision "
            f"(ожидалось {expected}, пришло {envelope_revision}) — запускаю resync"
        )
        patterns = list(dict.fromkeys(self._sub_patterns.values()))
        self._resync(patterns)
        return True

    def _resync(self, patterns: list[str]) -> None:
        """Ресинк кэша: запросить свежий снапшот поддеревьев по patterns.

        Переиспользует существующий канал state.get_subtree (не заводит
        отдельную команду — ADR-SS-015): передаёт data.paths вместо data.path,
        сервер (handle_state_get_subtree) распознаёт это и строит снимок через
        TreeStore.snapshot(paths). Полностью замещает в кэше все пути,
        попадающие под patterns, свежими значениями с сервера и обновляет
        self._last_revision до серверной revision на момент ответа.

        No-op при router=None или пустом patterns (нечего ресинкать).
        """
        if self._router is None or not patterns:
            return

        request_id = str(uuid.uuid4())
        msg = {
            "type": "command",
            "sender": self._process_name,
            "targets": [self._server_target],
            "command": "state.get_subtree",
            "data": {"paths": patterns, "request_id": request_id},
        }
        response = self._send_sync(msg)
        if response is None or response.get("status") != "ok":
            self._log_warning(f"StateProxy '{self._process_name}': resync не удался: {response}")
            return

        snapshot = response.get("value", {})
        revision = response.get("revision")
        self._apply_resync_snapshot(patterns, snapshot if isinstance(snapshot, dict) else {})
        if isinstance(revision, int):
            self._last_revision = revision
        self._log_debug(f"StateProxy '{self._process_name}': resync выполнен, revision={revision}")

    def _apply_resync_snapshot(self, patterns: list[str], snapshot: dict) -> None:
        """Сойти кэш с серверным снимком для путей, попадающих под patterns.

        1. Удаляет из кэша все закэшированные пути, матчащие любой из patterns
           (устаревшие значения — в т.ч. пути, удалённые на сервере и потому
           отсутствующие в свежем снапшоте, должны исчезнуть из кэша).
        2. Заполняет кэш листовыми значениями снапшота по каждому pattern.

        Args:
            patterns: glob-паттерны (те же, что переданы в _resync()).
            snapshot: dict, полученный от TreeStore.snapshot(paths=patterns).
        """
        pattern_segs_list = [split_pattern(p) for p in patterns]
        stale_keys = [
            path
            for path in self._cache
            if any(match_pattern(segs, tuple(path.split("."))) for segs in pattern_segs_list)
        ]
        for key in stale_keys:
            del self._cache[key]

        for pattern in patterns:
            for path, value in iter_matches(snapshot, pattern):
                if not isinstance(value, dict):
                    self._cache[path] = value

    # -------------------------------------------------------------------
    # Lifecycle
    # -------------------------------------------------------------------

    def shutdown(self) -> bool:
        """Отписать все активные подписки.

        Отправляет state.unsubscribe_all в StateStoreManager и
        очищает локальный реестр callbacks.
        """
        if self._router is not None and self._sub_ids:
            msg = {
                "type": "command",
                "sender": self._process_name,
                "targets": [self._server_target],
                "command": "state.unsubscribe_all",
                "data": {"subscriber": self._process_name},
            }
            self._send(msg)

        self._callbacks.clear()
        self._sub_patterns.clear()
        self._sub_ids.clear()
        self._pattern_sub_id.clear()
        self._pattern_refcount.clear()
        self._sub_id_pattern.clear()
        self.is_initialized = False
        self._log_debug(f"StateProxy '{self._process_name}': shutdown, все подписки удалены")
        return True

    # -------------------------------------------------------------------
    # Вспомогательные методы (используются в GuiStateProxy)
    # -------------------------------------------------------------------

    def _deserialize_deltas(self, msg: dict) -> list[Delta]:
        """Десериализовать дельты из IPC-сообщения.

        Args:
            msg: IPC-сообщение state.changed.

        Returns:
            Список объектов Delta. Пустой список при ошибке или отсутствии дельт.
        """
        try:
            data = msg.get("data", {})
            raw_deltas = data.get("deltas", [])
            return [Delta.from_dict(d) for d in raw_deltas]
        except Exception as exc:
            self._log_error(f"StateProxy '{self._process_name}': ошибка десериализации дельт: {exc}")
            return []

    def _update_cache(self, deltas: list[Delta]) -> None:
        """Обновить кэш на основе списка дельт.

        Правила:
        - delta.new_value is MISSING → удалить path из кэша
        - иначе → записать delta.new_value в кэш

        Args:
            deltas: список Delta для обновления кэша.
        """
        for delta in deltas:
            if delta.new_value is MISSING:
                # Удаление узла
                self._cache.pop(delta.path, None)
            else:
                self._cache[delta.path] = delta.new_value

    def _invoke_callbacks(self, deltas: list[Delta]) -> None:
        """Вызвать callbacks, фильтруя дельты по pattern каждой подписки.

        Сервер группирует дельты по subscriber и шлёт одним пакетом —
        пакет содержит ВСЕ дельты, попавшие в любую подписку процесса.
        Здесь мы для каждого callback оставляем только те дельты, чьи path
        матчат pattern его подписки. Если совпадений нет — callback не вызывается.

        Если pattern по какой-то причине не сохранён (legacy путь) —
        вызываем callback со всеми дельтами (старое поведение).

        Args:
            deltas: список Delta из IPC-пакета.
        """
        for sub_id, cbs in list(self._callbacks.items()):
            pattern = self._sub_patterns.get(sub_id)
            if pattern is None:
                # Legacy / locally-only путь без сохранённого pattern — без фильтрации
                matched = deltas
            else:
                matched = self._filter_deltas_by_pattern(deltas, pattern)
                if not matched:
                    continue

            for cb in cbs:
                try:
                    cb(matched)
                except Exception as exc:
                    self._log_error(f"StateProxy '{self._process_name}': ошибка в callback sub_id={sub_id}: {exc}")

    @staticmethod
    def _filter_deltas_by_pattern(deltas: list[Delta], pattern: str) -> list[Delta]:
        """Отфильтровать дельты, чьи path совпадают с glob-паттерном.

        Использует match_pattern из core (тот же матчер, что на сервере),
        чтобы поведение клиента и сервера совпадало.
        """
        pattern_segs = split_pattern(pattern)
        result: list[Delta] = []
        for delta in deltas:
            path_segs = tuple(delta.path.split(".")) if delta.path else ()
            if match_pattern(pattern_segs, path_segs):
                result.append(delta)
        return result

    # -------------------------------------------------------------------
    # IPC-хелперы
    # -------------------------------------------------------------------

    def _send(self, msg: dict) -> None:
        """Отправить IPC-сообщение асинхронно (fire-and-forget).

        При router=None — только логируем (тестовый режим).

        Args:
            msg: IPC-сообщение для отправки.
        """
        if self._router is not None:
            try:
                self._router.send_async(msg, priority="normal")
            except Exception as exc:
                self._log_error(
                    f"StateProxy '{self._process_name}': ошибка отправки команды '{msg.get('command')}': {exc}"
                )
        else:
            self._log_debug(
                f"StateProxy '{self._process_name}': router=None, команда '{msg.get('command')}' не отправлена"
            )

    def _send_sync(self, msg: dict) -> dict | None:
        """Отправить IPC-сообщение синхронно и вернуть ответ.

        При router=None или ошибке — возвращает None.

        Args:
            msg: IPC-сообщение для отправки.

        Returns:
            dict с ответом или None.
        """
        if self._router is None:
            return None
        try:
            return self._router.send(msg)
        except Exception as exc:
            self._log_error(
                f"StateProxy '{self._process_name}': ошибка синхронной отправки '{msg.get('command')}': {exc}"
            )
            return None
