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

# Единственная конкретная зависимость модуля от router_module. Развязка через
# ``IRouter`` сохраняется для ВСЕГО остального: прокси по-прежнему работает с
# любым дублем роутера, а этот тип нужен ровно для того, чтобы ОТЛИЧИТЬ ошибку
# программиста (вызов с приёмного потока) от отказа транспорта — их политики
# противоположны (см. :meth:`StateProxy._send_sync`). Цикла нет: router_module
# не импортирует state_store_module ни в одной точке (проверено 2026-08-23).
from ...router_module.core.router_manager import RouterReentrantRequestError
from ..core import iter_matches, match_pattern, pattern_covers, split_pattern
from ..core.delta import MISSING, STATE_ENVELOPE_MARKER, Delta
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
        # Coverage-check (Ф-GUI-read-model 0.1): sub_id'ы «покрытых» паттернов —
        # локальные подписки БЕЗ серверного state.subscribe. Их дельты приезжают
        # потоком покрывающей ПОДТВЕРЖДЁННОЙ серверной подписки. Как они доходят
        # до потребителя, зависит от proxy: в базовом StateProxy их разводит
        # _invoke_callbacks (packet-wide локальный path-матч против _sub_patterns);
        # в GUI (GuiStateProxy с delta_sink) — delta_sink→bridge→GuiStateBindings
        # со своим матчером, а _invoke_callbacks не вызывается. Для таких sub_id
        # unsubscribe НЕ шлёт серверный state.unsubscribe (его там нет).
        self._covered_sub_ids: set[str] = set()
        # Подтверждённые сервером паттерны (Ф-GUI-read-model 0.1, угловое ревью):
        # паттерн попадает сюда ТОЛЬКО после успешного sync=True subscribe, когда
        # сервер вернул валидный sub_id. Async-подписки (sync=False) сюда НЕ
        # попадают — сервер их не подтвердил. Покрывающими в _find_covering_pattern
        # считаются исключительно подтверждённые паттерны: неподтверждённый широкий
        # паттерн (мог тихо не создаться на сервере) не должен «усыновлять» узкий и
        # оставлять его без потока дельт (латентный «мёртвый виджет»).
        self._confirmed_patterns: set[str] = set()
        # Счётчик async-подписок (0.3): fire-and-forget subscribe не виден в
        # request-раундтрипе, отказ сервера не приходит немедленно — счётчик даёт
        # наблюдаемость (можно сверить с числом реально пришедших дельт).
        self._async_subscribe_count: int = 0
        # Счётчик ре-адопций covered-подписок (находка F, Task 3.3): растёт при
        # каждом снятии ПОДТВЕРЖДЁННОГО покрывающего паттерна, для которого хотя
        # бы одна covered-подписка требует переусыновления (на другой покрывающий
        # или собственную async-подписку). Наблюдаемость — как у
        # _async_subscribe_count, сверяется с логом [re-adopt].
        self._re_adopt_count: int = 0
        # Watch-from-revision (Ф4.9b, ADR-SS-014/015): revision последнего
        # успешно применённого пакета state.changed. None — ещё не было ни
        # одного пакета с revision (либо proxy только создан, либо все
        # входящие пакеты были от старых отправителей без revision).
        self._last_revision: int | None = None

        # --- Неблокирующая ресинхронизация (ADR-SS-022, 2026-08-23) ---
        # request_id ресинхронизации, ответ на которую ещё не пришёл. Не None =
        # «идёт ресинк»: второй запрос не отправляем (иначе на каждый разрыв в
        # шторме летел бы свой снимок всего поддерева).
        self._resync_inflight_id: str | None = None
        # Паттерны, снимок которых заказан текущей ресинхронизацией.
        self._resync_patterns: list[str] = []
        # Пути, изменённые дельтами ЗА ОКНО ожидания снимка: path → максимальная
        # revision дельты. Снимок не имеет права затереть значение свежее себя.
        self._resync_dirty: dict[str, int] = {}
        # То же для дельт-удалений: удаление приходит ОДНОЙ дельтой на корень
        # поддерева (TreeStore.delete), поэтому защищать надо и корень, и всё
        # под ним — иначе снимок воскресит листья снятого писателя.
        self._resync_dirty_deletes: dict[str, int] = {}
        # Журнал переполнен (см. _RESYNC_DIRTY_MAX) — защиту гарантировать больше
        # нельзя, снимок в этом заходе не применяется.
        self._resync_dirty_overflow: bool = False
        # Разрыв, обнаруженный ПОКА снимок в полёте: после его применения делаем
        # ровно один догоняющий заход (не N по числу разрывов).
        self._resync_again_pending: bool = False
        # Наблюдаемость ресинхронизации (сверяется с логом и метриками).
        self._resync_started_count: int = 0
        self._resync_coalesced_count: int = 0
        self._resync_completed_count: int = 0
        self._resync_failed_count: int = 0
        self._resync_overflow_count: int = 0
        self._resync_protected_paths_total: int = 0

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
                # Ф7 G.2 шаг 4: явный маркер конверта — получатель не гадает по
                # наличию top-level path/data (см. STATE_ENVELOPE_MARKER).
                STATE_ENVELOPE_MARKER: True,
            },
        }
        self._send(msg)

    def delete(self, path: str) -> None:
        """Отправить state.delete в StateStoreManager через IPC.

        Зеркало set()/merge() — тот же транспорт (fire-and-forget через
        _send), тот же source (имя процесса-отправителя). Приёмная сторона
        (TreeStore.delete, StateStoreManager.handle_state_delete, маршрут
        'state.delete', прун троттла) уже существует — этот метод достраивает
        единственное недостающее звено: клиентский вызов.

        Идемпотентен на сервере: удаление уже отсутствующего пути не
        ошибка (TreeStore.delete возвращает None, handler отвечает
        changed=False). На стороне прокси эквивалентно set()/merge() —
        асинхронная команда, без ожидания ответа.

        Args:
            path: точечный путь к узлу/поддереву, например
                'processes.cam0.state.plugins.capture'.
        """
        msg = {
            "type": "command",
            "sender": self._process_name,
            "targets": [self._server_target],
            "command": "state.delete",
            "data": {
                "path": path,
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
        sync: bool = True,
    ) -> str:
        """Подписаться на изменения по паттерну.

        1. Отправляет state.subscribe в StateStoreManager через IPC.
        2. Регистрирует callback локально по sub_id.
        3. exclude_self=True → exclude_sources=(self._process_name,).

        Args:
            pattern: glob-паттерн пути (например 'cameras.*.config.*').
            callback: функция, вызываемая при получении дельт.
            exclude_self: исключить изменения от этого же процесса.
            sync: True (по умолчанию, обратная совместимость) — блокирующий
                request/response раундтрип: ждём sub_id сервера. False
                (Ф-GUI-read-model 0.2) — fire-and-forget: отправляем
                state.subscribe без ожидания ответа (не блокируем вызывающий
                поток, критично для Qt main thread), sub_id генерируется
                локально. Серверный replay/дельты приедут асинхронно штатным
                потоком state.changed. Отказ сервера в async-режиме не виден
                немедленно — виджет не «мёртв», а пуст до первой дельты.

        Returns:
            sub_id — строка-идентификатор подписки.
        """
        exclude_sources: list[str] = [self._process_name] if exclude_self else []

        # Генерируем локальный sub_id — он может быть переопределён ответом сервера
        # (только в sync-режиме; в async сервер не отвечает, sub_id остаётся локальным).
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

        if self._router is None:
            self._log_debug(f"StateProxy.subscribe: router=None, подписка '{pattern}' только локальная")
        elif not sync:
            # Fire-and-forget (0.2): не блокируем поток раундтрипом. sub_id
            # локальный, серверный ответ не ждём; ошибку транспорта ловит _send
            # (лог-error), отсутствие серверной подписки проявится как пустой
            # виджет до первой дельты, а не как зависание GUI.
            self._send(msg)
            # Наблюдаемость async-подписок (0.3): счётчик + метрика + INFO-лог с
            # чётким маркером. Async — штатный путь (не ошибка), поэтому уровень
            # INFO, а не WARNING (иначе флуд на каждый непокрытый bind); отказ
            # сервера всё равно не виден немедленно — счётчик позволяет сверить
            # число async-подписок с числом пришедших дельт.
            self._async_subscribe_count += 1
            self._record_metric("state_proxy.async_subscribe")
            self._log_info(
                f"StateProxy '{self._process_name}': [async-subscribe] '{pattern}' "
                f"(sub_id={local_sub_id}, ответа сервера не ждём; "
                f"всего async-подписок={self._async_subscribe_count})"
            )
        else:
            # sync: пробуем получить sub_id от сервера через блокирующий request().
            # Если ответа нет, сервер вернул error или sub_id отсутствует — логируем
            # warning. Это значит, что серверная подписка не создана (callback не
            # сработает), но локальный sub_id выдаём (чтобы клиентский код не падал).
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
                    # Подтверждение (0.1, угловое ревью): сервер вернул валидный
                    # sub_id — паттерн реально существует на сервере и стримит
                    # дельты. Только такие паттерны могут покрывать узкие (см.
                    # _find_covering_pattern). Async/отклонённые подписки сюда
                    # не попадают.
                    self._confirmed_patterns.add(pattern)
                else:
                    self._log_warning(
                        f"StateProxy '{self._process_name}': подписка на '{pattern}' не вернула sub_id от сервера"
                    )

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
        removed_pattern = self._sub_patterns.pop(sub_id, None)
        if sub_id in self._sub_ids:
            self._sub_ids.remove(sub_id)

        # Снятие подтверждения (0.1, угловое ревью): если это был ПОСЛЕДНИЙ sub_id
        # данного паттерна — паттерн больше не активен на сервере, убираем его из
        # _confirmed_patterns, иначе _find_covering_pattern считал бы покрывающей
        # уже снятую подписку (и оставил бы узкий паттерн без потока дельт).
        if removed_pattern is not None and removed_pattern not in self._sub_patterns.values():
            was_confirmed = removed_pattern in self._confirmed_patterns
            self._confirmed_patterns.discard(removed_pattern)
            # Ре-адопция covered-подписок (находка F, Task 3.3): снятие ПОСЛЕДНЕГО
            # sub_id подтверждённого покрывающего паттерна могло осиротить
            # covered-подписки, которые он покрывал, — без этого шага они молча
            # остаются без потока дельт (снятая покрывающая больше не стримит).
            if was_confirmed:
                self._readopt_orphaned_covered_subscriptions(removed_pattern)

        # Чистим refcount-реестр, если этот sub_id был ensure-подпиской —
        # иначе прямой unsubscribe оставил бы висячий pattern → refcount.
        # O(1) через обратную карту (не линейный скан на каждый unsubscribe).
        pat = self._sub_id_pattern.pop(sub_id, None)
        if pat is not None:
            self._pattern_sub_id.pop(pat, None)
            self._pattern_refcount.pop(pat, None)

        # Покрытая (local-only) подписка (0.1): серверной подписки за этим sub_id
        # нет — снимаем только локальную регистрацию, IPC state.unsubscribe не шлём
        # (иначе спурьёзное сообщение с несуществующим sub_id + лишний IPC).
        if sub_id in self._covered_sub_ids:
            self._covered_sub_ids.discard(sub_id)
            return

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

        # Coverage-check (0.1): если активная ПОДТВЕРЖДЁННАЯ серверная подписка уже
        # покрывает этот pattern — не слать второй state.subscribe. Реальная
        # гарантия доставки покрытому паттерну = покрывающая подтверждённая
        # серверная подписка стримит эти пути в proxy; далее в базовом StateProxy
        # их разводит _invoke_callbacks (packet-wide локальный path-матч против
        # _sub_patterns), а в GUI (GuiStateProxy с delta_sink) —
        # delta_sink→bridge→GuiStateBindings со своим матчером.
        # Соображения:
        #  - Кандидаты покрытия — только ПОДТВЕРЖДЁННЫЕ паттерны (_confirmed_patterns,
        #    заполняются в subscribe() при валидном серверном sub_id): стартовые
        #    wildcard'ы processes.**/system.** заводятся прямым sync=True subscribe()
        #    (frontend/process.py) ДО открытия вкладок и подтверждаются. Async
        #    (sync=False) паттерны не подтверждены — не покрывают (fallback на
        #    собственную async-подписку), чтобы тихо не создавшаяся на сервере
        #    подписка не оставила узкий паттерн без потока дельт.
        #  - Из кандидатов исключаем сами «покрытые» (local-only) sub_id — покрывать
        #    может только реальная серверная подписка, реально стримящая дельты.
        #  - Консервативно ограничиваемся exclude_self=True (единственный режим
        #    покрывающих в проде): покрытый паттерн наследует exclude_sources
        #    покрывающего потока; при exclude_self=False создаём свою подписку,
        #    чтобы не потерять self-sourced дельты (худший случай — лишняя
        #    подписка, никогда не «мёртвый виджет»).
        covering = self._find_covering_pattern(pattern) if exclude_self else None
        if covering is not None:
            local_sub_id = str(uuid.uuid4())
            self._callbacks[local_sub_id] = [cb]
            self._sub_patterns[local_sub_id] = pattern
            self._sub_ids.append(local_sub_id)
            self._pattern_sub_id[pattern] = local_sub_id
            self._pattern_refcount[pattern] = 1
            self._sub_id_pattern[local_sub_id] = pattern
            self._covered_sub_ids.add(local_sub_id)
            self._log_debug(
                f"StateProxy '{self._process_name}': '{pattern}' покрыт активной "
                f"подпиской '{covering}' — серверный state.subscribe не отправлен "
                f"(local sub_id={local_sub_id})"
            )
            return local_sub_id

        # Не покрыт — создаём серверную подписку. sync=False (0.2): fire-and-forget,
        # не блокируем вызывающий поток (Qt main thread) IPC-раундтрипом.
        sub_id = self.subscribe(pattern, cb, exclude_self=exclude_self, sync=False)
        self._pattern_sub_id[pattern] = sub_id
        self._pattern_refcount[pattern] = 1
        self._sub_id_pattern[sub_id] = pattern
        return sub_id

    def _find_covering_pattern(self, new_pattern: str) -> str | None:
        """Найти активную ПОДТВЕРЖДЁННУЮ серверную подписку, покрывающую new_pattern (0.1).

        Покрывающими считаются только паттерны из _confirmed_patterns —
        подписки, которые сервер реально подтвердил валидным sub_id (см.
        subscribe(), sync=True). Дополнительно исключаются local-only «покрытые»
        (_covered_sub_ids, они и так не подтверждены) и точное совпадение с
        new_pattern (его обрабатывает refcount-ветка выше). Async-подписки
        (sync=False) НЕ подтверждены — они могли тихо не создаться на сервере,
        поэтому не покрывают узкие паттерны (иначе латентный «мёртвый виджет»:
        узкий не получил своей подписки, а покрывающая не стримит дельт).
        Coverage-проверка консервативна (см. pattern_covers): ложное «покрыто»
        невозможно.

        Args:
            new_pattern: паттерн, для которого ищем покрытие.

        Returns:
            Строку покрывающего паттерна или None, если покрытия нет.
        """
        for sub_id, active_pattern in self._sub_patterns.items():
            if sub_id in self._covered_sub_ids:
                continue  # сам покрытый — не может быть источником потока
            if active_pattern not in self._confirmed_patterns:
                continue  # неподтверждённый (async) — не гарантирует поток дельт
            if active_pattern == new_pattern:
                continue  # точное совпадение — не сюда (refcount-ветка)
            if pattern_covers(active_pattern, new_pattern):
                return active_pattern
        return None

    def _readopt_orphaned_covered_subscriptions(self, removed_pattern: str) -> None:
        """Восстановить поток covered-подпискам, осиротевшим при снятии removed_pattern.

        Вызывается из unsubscribe() ТОЛЬКО когда только что снят ПОСЛЕДНИЙ sub_id
        ПОДТВЕРЖДЁННОГО покрывающего паттерна (removed_pattern уже убран из
        _confirmed_patterns к моменту вызова). До этой правки (находка F
        Fable-ревью 2026-07-16) covered-подписка, которую покрывал ТОЛЬКО этот
        паттерн, молча оставалась без потока дельт навсегда — сервер её никогда
        не подтверждал (у неё нет собственного sub_id), а последний источник
        покрывающих пакетов исчез.

        Для каждой covered-подписки (_covered_sub_ids) заново ищем покрывающий
        паттерн (_find_covering_pattern уже учитывает актуальный, урезанный
        _confirmed_patterns):
          - найден другой подтверждённый покрывающий → переусыновление
            бесплатно: его серверная подписка уже стримит пакеты, которые
            _invoke_callbacks локально фильтрует по pattern подписки — никакого
            нового IPC не нужно, только наблюдаемость;
          - не найден ни один → подписка реально осиротела, ей нужен
            собственный поток — отправляем async state.subscribe (паттерн 0.2)
            и убираем sub_id из _covered_sub_ids (дальнейший unsubscribe(sub_id)
            должен слать серверный state.unsubscribe, раз своя подписка есть).

        Args:
            removed_pattern: паттерн, только что снятый из _confirmed_patterns
                (только для сообщения в логе — что вызвало осиротение).
        """
        for sub_id in list(self._covered_sub_ids):
            pattern = self._sub_patterns.get(sub_id)
            if pattern is None:
                continue  # сама снимаемая подписка уже выпала из _sub_patterns
            covering = self._find_covering_pattern(pattern)
            if covering is not None:
                self._re_adopt_count += 1
                self._log_info(
                    f"StateProxy '{self._process_name}': [re-adopt] '{pattern}' "
                    f"(sub_id={sub_id}) переусыновлён на другой подтверждённый "
                    f"покрывающий паттерн '{covering}' (снят '{removed_pattern}'; "
                    f"всего re-adopt={self._re_adopt_count})"
                )
                continue
            self._reactivate_covered_subscription(sub_id, pattern, removed_pattern)

    def _reactivate_covered_subscription(self, sub_id: str, pattern: str, removed_pattern: str) -> None:
        """Отправить осиротевшей covered-подписке собственный async state.subscribe.

        Вызывается из _readopt_orphaned_covered_subscriptions, когда для sub_id
        не осталось НИ ОДНОГО подтверждённого покрывающего паттерна. Использует
        ТОТ ЖЕ sub_id, что уже зарегистрирован в _callbacks/_sub_patterns/
        _sub_ids (потребитель мог сохранить его для release_subscription) — в
        отличие от subscribe(), который всегда генерирует новый локальный
        sub_id, поэтому здесь IPC-конверт собирается вручную.

        Args:
            sub_id: существующий локальный sub_id covered-подписки.
            pattern: её glob-паттерн.
            removed_pattern: паттерн, снятие которого вызвало осиротение (для лога).
        """
        self._covered_sub_ids.discard(sub_id)
        msg = {
            "type": "command",
            "sender": self._process_name,
            "targets": [self._server_target],
            "command": "state.subscribe",
            "data": {
                "pattern": pattern,
                "subscriber": self._process_name,
                # Covered-подписки создаются только при exclude_self=True (см.
                # docstring ensure_subscription) — то же консервативное допущение
                # сохраняется при ре-адопции.
                "exclude_sources": [self._process_name],
            },
        }
        self._send(msg)
        self._async_subscribe_count += 1
        self._re_adopt_count += 1
        self._record_metric("state_proxy.re_adopt")
        self._log_info(
            f"StateProxy '{self._process_name}': [re-adopt] '{pattern}' (sub_id={sub_id}) "
            f"осиротел после снятия покрывающего паттерна '{removed_pattern}' — отправлена "
            f"собственная async-подписка (всего re-adopt={self._re_adopt_count}, "
            f"async-подписок={self._async_subscribe_count})"
        )

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
        2. Устаревший пакет ("в полёте" во время предыдущего resync, MED-3,
           ревью 2026-07-11) — игнорируется целиком: revision конверта не
           продвигает состояние клиента дальше уже известного, применение
           таких дельт поверх более свежего resync-снимка регрессировало бы
           кэш. Без обновления кэша, без callbacks, без нового resync.
        3. Иначе — дельты пакета ВСЕГДА применяются к кэшу и доставляются в
           callbacks (инвариант (б), ревью 2026-07-11: пакет никогда не
           проглатывается из-за решения о запуске resync — раньше при
           обнаруженном разрыве дельты этого же пакета терялись целиком).
        4. Проверяется непрерывность revision по диапазону [first_revision,
           revision] пакета — при обнаруженном разрыве ДОПОЛНИТЕЛЬНО (не
           взамен шага 3) запускается resync как подстраховка для путей,
           которые мог задеть действительно потерянный пакет.

        Args:
            msg: IPC-сообщение с полем data.deltas.
        """
        deltas = self._deserialize_deltas(msg)
        if not deltas:
            return

        data = msg.get("data", {})
        envelope_revision = data.get("revision")

        if envelope_revision is not None and self._is_stale_envelope(envelope_revision):
            self._log_debug(
                f"StateProxy '{self._process_name}': устаревший пакет revision={envelope_revision} "
                f"(last={self._last_revision}) — игнорирую (в полёте до предыдущего resync)"
            )
            return

        self._update_cache(deltas)
        self._invoke_callbacks(deltas)

        if envelope_revision is not None:
            first_revision = data.get("first_revision", envelope_revision)
            self._advance_revision_and_maybe_resync(first_revision, envelope_revision)

    # -------------------------------------------------------------------
    # Watch-from-revision + resync (Ф4.9b, ADR-SS-014/015, пересмотрено 2026-07-11)
    # -------------------------------------------------------------------

    def _is_stale_envelope(self, envelope_revision: int) -> bool:
        """MED-3 (ревью 2026-07-11): пакет "в полёте" во время предыдущего resync.

        Сценарий: сервер отправил пакет P (revision=6), затем клиент по
        ДРУГОЙ причине обнаружил разрыв и ресинкнулся (снимок сервера уже на
        revision=9, _last_revision=9). Пакет P доставляется ПОСЛЕ ресинка
        (переупорядочение на IPC-уровне — очереди с приоритетами не
        гарантируют строгий порядок). Его revision=6 <= уже известного 9 —
        применение P поверх свежего снимка откатило бы кэш к устаревшим
        значениям.

        Args:
            envelope_revision: msg["data"]["revision"] (int).

        Returns:
            True — пакет устарел, применять/доставлять нельзя.
        """
        return self._last_revision is not None and envelope_revision <= self._last_revision

    def _advance_revision_and_maybe_resync(self, first_revision: int, envelope_revision: int) -> None:
        """Продвинуть _last_revision и, при обнаруженном разрыве, ДОПОЛНИТЕЛЬНО ресинкнуться.

        ВАЖНО: к моменту вызова этого метода дельты ТЕКУЩЕГО пакета уже
        применены к кэшу и доставлены в callbacks (см. on_state_changed,
        инвариант (б)) — resync здесь ТОЛЬКО подстраховка для путей, которые
        мог задеть действительно потерянный пакет, а не источник истины для
        уже обработанного пакета.

        Модель диапазона (HIGH-1, ревью 2026-07-11): пакет описывает
        revisions [first_revision .. envelope_revision]. Непрерывность —
        first_revision не больше _last_revision+1 (между тем, что мы уже
        видели, и тем, что несёт этот пакет, нет пропущенных revision).
        merge() на N листьев (TreeStore._merge_recursive) даёт ОДИН пакет
        с диапазоном [last+1 .. last+N] — воспринимается как непрерывный
        ЦЕЛИКОМ. Раньше сравнивался только max(revision) конверта, поэтому
        пакет из 2+ листьев (envelope=last+2) ложно распознавался как
        разрыв — хотя все промежуточные revision содержались В ЭТОМ ЖЕ
        пакете, и дельты (тогда) терялись целиком.

        Известное ограничение (ADR-SS-015, не устранено этим фиксом):
        revision — счётчик ВСЕГО дерева, не per-pattern. Мутации вне
        подписок этого proxy тоже двигают revision невидимо для него — это
        может вызывать resync, которого объективно не требовалось (лишний
        round-trip). Но (в отличие от старого поведения) это больше НЕ
        стоит потери текущего пакета — gap используется ТОЛЬКО как
        опциональный бэкстоп надёжности, никогда не ценой данных.

        _last_revision продвигается до envelope_revision НЕЗАВИСИМО от
        исхода resync (MED-4, ревью 2026-07-11): раньше неудачный resync
        навсегда замораживал _last_revision — каждый следующий пакет снова
        считался разрывом, callbacks блокировались перманентно. Теперь
        прогресс отслеживается по реально доставленным (и уже применённым)
        пакетам; resync — только попытка подтянуть то, что могло потеряться.

        Args:
            first_revision: msg["data"]["first_revision"] (fallback — envelope_revision
                для пакетов от отправителей без этого поля, обратная совместимость).
            envelope_revision: msg["data"]["revision"].
        """
        if self._last_revision is None:
            # Первый пакет с revision — база отсчёта, разрыва не бывает по определению.
            self._last_revision = envelope_revision
            return

        expected = self._last_revision + 1
        gap = first_revision > expected
        self._last_revision = envelope_revision

        if gap:
            self._log_warning(
                f"StateProxy '{self._process_name}': разрыв revision "
                f"(ожидалось {expected}, пакет начинается с {first_revision}) — "
                "запускаю resync (подстраховка; текущий пакет уже применён)"
            )
            patterns = list(dict.fromkeys(self._sub_patterns.values()))
            self._resync(patterns)

    #: Потолок журнала защищённых путей на одно окно ресинхронизации.
    #: Журнал — это РАЗНЫЕ пути (не дельты), поэтому потолок бьётся только при
    #: обходе очень широкого поддерева за одно окно (~5 с). Дойдя до него,
    #: гарантию «снимок не затрёт свежее» держать нечем — и мы предпочитаем
    #: НЕ применять снимок вовсе (см. _on_resync_response), а не применить его
    #: наполовину.
    _RESYNC_DIRTY_MAX = 10_000

    def _resync(self, patterns: list[str]) -> None:
        """Ресинк кэша: запросить свежий снапшот поддеревьев по patterns.

        Переиспользует существующий канал state.get_subtree (не заводит
        отдельную команду — ADR-SS-015): передаёт data.paths вместо data.path,
        сервер (handle_state_get_subtree) распознаёт это и строит снимок через
        TreeStore.snapshot(paths).

        ПОЧЕМУ НЕБЛОКИРУЮЩЕ (ADR-SS-022, 2026-08-23). Этот метод вызывается из
        ``on_state_changed``, то есть НА ПРИЁМНОМ ПОТОКЕ процесса: единственный
        ``message_processor`` синхронно диспатчит ``state.changed`` внутри
        ``router.receive()``. Блокирующий ``request()`` отсюда ждал ответа,
        который обязан был разобрать он сам, — то есть гарантированно досиживал
        до таймаута (5 с), и всё это время системная почта процесса не
        разбиралась. Замер на живом стенде 2026-08-23 (9 процессов): вытеснено
        93.7% дельт очереди ``{proc}_state`` (drop_oldest), «опоздавшая» почта
        раз в 5.06 с, ``fps`` доходил до подписчика через 16 минут. Причём петля
        самоусиливающаяся: реже читаешь → больше вытеснений → больше разрывов →
        больше пятисекундных простоев.

        Поэтому запрос уходит через ``router.request_async``: приёмный поток
        возвращается в цикл немедленно, а снимок применяет
        :meth:`_on_resync_response` — тем же приёмным потоком, когда ответ
        реально придёт. Отдельного потока НЕТ намеренно: весь кэш так и остаётся
        собственностью одного потока, лишних локов не появляется.

        ЧТО С ДЕЛЬТАМИ, ПРИШЕДШИМИ ВО ВРЕМЯ РЕСИНХРОНИЗАЦИИ. Они больше не ждут
        ответа: применяются к кэшу и доставляются в callbacks штатным путём
        (инвариант (б)) — раньше их держал заблокированный приёмный поток. Ценой
        этого снимок (сделанный сервером в момент S) может оказаться СТАРШЕ уже
        применённой дельты. Поэтому каждая дельта окна помечает свой путь в
        ``_resync_dirty`` вместе со своей revision, и при применении снимка
        путь с ``revision >= S`` не трогается: живой поток дельт всегда
        побеждает более старый снимок. Обратный случай (дельта старше снимка,
        ``revision < S``) — снимок побеждает, ради него ресинк и затевался.

        Цена названа явно, три штуки:
          1. дельта с ``revision == 0`` (отправитель без revision, default
             ``Delta.revision``) считается СТАРЫМ — снимок её перекроет;
          2. если сервер не вернул revision (не int), сравнивать не с чем —
             защищаются ВСЕ пути окна, снимок применяется только к остальным;
          3. если путей в окне больше ``_RESYNC_DIRTY_MAX``, снимок не
             применяется вовсе (``_resync_overflow_count``) — восстановление
             откладывается до следующего разрыва, но регресса кэша не будет.

        No-op при router=None или пустом patterns (нечего ресинкать). Второй
        вызов, пока ответ первого не пришёл, НЕ шлёт второго запроса: он только
        помечает ``_resync_again_pending`` — догоняющий заход будет ровно один.
        """
        if self._router is None or not patterns:
            return

        if self._resync_inflight_id is not None:
            # Ресинк уже в полёте. Параллельный второй запрос не ускорил бы
            # сходимость (снимок строится по тому же дереву), но удвоил бы
            # трафик и дал бы два снимка, применяемых в неизвестном порядке.
            self._resync_coalesced_count += 1
            self._resync_again_pending = True
            self._record_metric("state_proxy.resync_coalesced")
            self._log_debug(
                f"StateProxy '{self._process_name}': ресинк уже идёт "
                f"(id={self._resync_inflight_id}) — новый запрос не шлю, "
                f"догоняющий заход помечен (совмещено={self._resync_coalesced_count})"
            )
            return

        request_id = str(uuid.uuid4())
        msg = {
            "type": "command",
            "sender": self._process_name,
            "targets": [self._server_target],
            "command": "state.get_subtree",
            "data": {"paths": patterns, "request_id": request_id},
        }

        request_async = getattr(self._router, "request_async", None)
        if not callable(request_async):
            # Роутер без неблокирующего запроса (тестовые дубли IRouter, у
            # которых send() сам по себе request-reply) — прежний синхронный
            # путь. Приёмного потока у таких роутеров нет, блокировать нечего.
            self._resync_blocking_fallback(patterns, msg)
            return

        # Порядок важен: помечаем «идёт» ДО отправки. Отправка может провалиться
        # и позвать колбэк синхронно, ещё изнутри request_async — колбэк обязан
        # застать флаг взведённым, иначе снимет чужой (следующий) ресинк.
        self._resync_inflight_id = request_id
        self._resync_patterns = list(patterns)
        self._resync_dirty.clear()
        self._resync_dirty_deletes.clear()
        self._resync_dirty_overflow = False
        self._resync_again_pending = False
        self._resync_started_count += 1
        self._record_metric("state_proxy.resync_started")
        try:
            request_async(
                msg,
                on_response=self._on_resync_response,
                timeout=self._SYNC_REQUEST_TIMEOUT,
                correlation_id=request_id,
            )
        except Exception as exc:
            self._resync_inflight_id = None
            self._resync_patterns = []
            self._log_error(f"StateProxy '{self._process_name}': ресинк не отправлен: {exc}")

    def _resync_blocking_fallback(self, patterns: list[str], msg: dict) -> None:
        """Старый синхронный ресинк — для роутеров без ``request_async``.

        Такие роутеры (тестовые дубли ``InMemoryRouter``/``MockRouter``/
        ``_RelayRouter``, а также любой сторонний ``IRouter``) исполняют запрос
        прямо в вызове send()/request(), приёмного потока у них нет вовсе — и
        блокировать здесь нечего. Держится ради обратной совместимости
        контракта ``IRouter``: он не обязывает никого иметь ``request_async``.
        """
        response = self._send_sync(msg)
        if response is None or response.get("status") != "ok":
            self._resync_failed_count += 1
            self._log_warning(f"StateProxy '{self._process_name}': resync не удался: {response}")
            return

        snapshot = response.get("value", {})
        revision = response.get("revision")
        self._apply_resync_snapshot(patterns, snapshot if isinstance(snapshot, dict) else {})
        self._advance_revision_after_resync(revision)
        self._resync_completed_count += 1
        self._log_debug(f"StateProxy '{self._process_name}': resync выполнен, revision={revision}")

    def _on_resync_response(self, envelope: dict) -> None:
        """Применить снимок ресинхронизации. Зовётся ПРИЁМНЫМ потоком из receive().

        Ровно один вызов на один ресинк — гарантию держит RouterManager
        (``_take_pending`` снимает слот под локом): ответ, таймаут и провал
        отправки взаимоисключающи.

        Порядок операций здесь и есть ответ на вопрос «не теряются ли дельты
        окна»: к этому моменту они УЖЕ в кэше и уже доставлены подписчикам, а
        снимок кладётся поверх только там, где он новее (см. докстринг
        :meth:`_resync`). Ничего не откладывается «на потом» и не переигрывается.

        Args:
            envelope: конверт ответа RouterManager
                (``{"success": bool, "result": {...}}`` или ``{"success": False,
                "error": "timeout"}``).
        """
        patterns = self._resync_patterns
        dirty = dict(self._resync_dirty)
        dirty_deletes = dict(self._resync_dirty_deletes)
        overflow = self._resync_dirty_overflow
        again = self._resync_again_pending

        # Снимаем «идёт» ДО применения: следующий разрыв должен иметь право
        # запустить новый ресинк, а не совместиться с уже завершённым.
        self._resync_inflight_id = None
        self._resync_patterns = []
        self._resync_dirty = {}
        self._resync_dirty_deletes = {}
        self._resync_dirty_overflow = False
        self._resync_again_pending = False

        response = self._unwrap_envelope(envelope)
        if response is None or response.get("status") != "ok":
            # Ответа нет (таймаут/провал отправки/отказ сервера). Кэш не трогаем:
            # он и так живёт потоком дельт, а _last_revision продвигается по
            # реально применённым пакетам (MED-4) — «замораживания» не будет.
            self._resync_failed_count += 1
            self._record_metric("state_proxy.resync_failed")
            self._log_warning(
                f"StateProxy '{self._process_name}': resync не удался: {envelope} "
                f"(всего неудач={self._resync_failed_count}); кэш оставлен как есть, "
                "дельты продолжают применяться штатно"
            )
            return

        snapshot = response.get("value", {})
        revision = response.get("revision")

        if overflow:
            self._resync_overflow_count += 1
            self._record_metric("state_proxy.resync_overflow")
            self._log_warning(
                f"StateProxy '{self._process_name}': за окно ресинка изменено больше "
                f"{self._RESYNC_DIRTY_MAX} путей — снимок НЕ применён (иначе часть путей "
                f"откатилась бы к устаревшим значениям); восстановление отложено до "
                f"следующего разрыва (всего переполнений={self._resync_overflow_count})"
            )
        else:
            self._apply_resync_snapshot(
                patterns,
                snapshot if isinstance(snapshot, dict) else {},
                protected=self._make_resync_protector(dirty, dirty_deletes, revision),
            )
            self._resync_completed_count += 1

        self._advance_revision_after_resync(revision)
        self._log_debug(
            f"StateProxy '{self._process_name}': resync выполнен, revision={revision}, "
            f"защищено путей={len(dirty) + len(dirty_deletes)}"
        )

        if again:
            # Разрыв, случившийся пока снимок был в полёте: один догоняющий заход.
            self._log_debug(f"StateProxy '{self._process_name}': догоняющий ресинк после совмещённого разрыва")
            self._resync(patterns)

    def _advance_revision_after_resync(self, revision: object) -> None:
        """Продвинуть _last_revision по серверной revision снимка, НИКОГДА не назад.

        max(...) — resync не должен ОТКАТЫВАТЬ _last_revision (ревью
        2026-07-11): к моменту ответа он мог уйти вперёд за счёт пакетов,
        доставленных и применённых, пока запрос был в полёте (инвариант (б) —
        они не ждут resync). После перевода ресинка в неблокирующий режим это не
        редкий случай, а НОРМА: окно ожидания теперь целиком открыто для дельт.
        """
        if isinstance(revision, int):
            self._last_revision = max(self._last_revision, revision) if self._last_revision is not None else revision

    def _make_resync_protector(
        self,
        dirty: dict[str, int],
        dirty_deletes: dict[str, int],
        revision: object,
    ) -> Callable[[str], bool]:
        """Построить предикат «этот путь снимку трогать нельзя».

        Защищается путь, изменённый живой дельтой за окно ожидания, ЕСЛИ эта
        дельта не старше снимка (``delta.revision >= revision снимка``). Дельта
        старше — снимок новее, он и должен победить.

        Удаления защищают поддерево: ``TreeStore.delete`` шлёт ОДНУ дельту на
        корень, а кэш держит листья — без защиты префикса снимок вернул бы
        листья снятого писателя (тот же разбор, что в :meth:`_update_cache`).

        Если сервер не вернул revision (не int), сравнивать не с чем: защищаем
        ВСЕ пути окна. Это осознанный перекос в сторону «не откатить живое».
        """
        snapshot_revision = revision if isinstance(revision, int) else None
        self._resync_protected_paths_total += len(dirty) + len(dirty_deletes)

        def _protected(path: str) -> bool:
            rev = dirty.get(path)
            if rev is not None and (snapshot_revision is None or rev >= snapshot_revision):
                return True
            for root, del_rev in dirty_deletes.items():
                if snapshot_revision is not None and del_rev < snapshot_revision:
                    continue
                if path == root or path.startswith(root + "."):
                    return True
            return False

        return _protected

    def _record_resync_dirty(self, deltas: list[Delta]) -> None:
        """Пометить пути, изменённые дельтами, пока снимок ресинка в полёте.

        Зовётся из :meth:`_update_cache` — то есть на ЛЮБОМ пути применения
        дельт, включая GuiStateProxy с его собственным ``on_state_changed``
        (иначе защита работала бы только в базовом прокси, а забыть про неё в
        подклассе было бы нечем поймать).
        """
        for delta in deltas:
            target = self._resync_dirty_deletes if delta.new_value is MISSING else self._resync_dirty
            known = target.get(delta.path)
            if known is None:
                if len(self._resync_dirty) + len(self._resync_dirty_deletes) >= self._RESYNC_DIRTY_MAX:
                    self._resync_dirty_overflow = True
                    return
                target[delta.path] = delta.revision
            elif delta.revision > known:
                target[delta.path] = delta.revision

    def _apply_resync_snapshot(
        self,
        patterns: list[str],
        snapshot: dict,
        protected: Callable[[str], bool] | None = None,
    ) -> None:
        """Сойти кэш с серверным снимком для путей, попадающих под patterns.

        1. Удаляет из кэша все закэшированные пути, матчащие любой из patterns
           (устаревшие значения — в т.ч. пути, удалённые на сервере и потому
           отсутствующие в свежем снапшоте, должны исчезнуть из кэша).
        2. Заполняет кэш листовыми значениями снапшота по каждому pattern.

        Args:
            patterns: glob-паттерны (те же, что переданы в _resync()).
            snapshot: dict, полученный от TreeStore.snapshot(paths=patterns).
            protected: предикат «путь трогать нельзя» — пути, изменённые живыми
                дельтами свежее снимка (см. :meth:`_make_resync_protector`).
                None — снимок применяется целиком (синхронный fallback-путь, где
                окна для дельт нет по построению).
        """
        is_protected = protected if protected is not None else (lambda _path: False)
        pattern_segs_list = [split_pattern(p) for p in patterns]
        stale_keys = [
            path
            for path in self._cache
            if any(match_pattern(segs, tuple(path.split("."))) for segs in pattern_segs_list) and not is_protected(path)
        ]
        for key in stale_keys:
            del self._cache[key]

        for pattern in patterns:
            for path, value in iter_matches(snapshot, pattern):
                if not isinstance(value, dict) and not is_protected(path):
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
        self._covered_sub_ids.clear()
        self._confirmed_patterns.clear()
        # Ресинк в полёте больше некуда применять: подписок нет, кэш очищен.
        # Ответ, если придёт после shutdown, разберётся как «ресинк без окна»
        # (_resync_patterns пуст → снимок применять не к чему).
        self._resync_inflight_id = None
        self._resync_patterns = []
        self._resync_dirty.clear()
        self._resync_dirty_deletes.clear()
        self._resync_again_pending = False
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

    def _cache_put(self, path: str, value: Any) -> None:
        """Положить значение в кэш, РАЗВЕРНУВ словарь в листья.

        Инвариант «в кэше только листья» в этом классе уже существовал, но
        соблюдался лишь половиной кода: :meth:`_apply_resync_snapshot` словари
        пропускает явно (``not isinstance(value, dict)``), а приёмная сторона
        дельт клала ``delta.new_value`` сырым. Дельта СОЗДАНИЯ поддерева
        приходит со словарём целиком, поэтому нелистовая запись в кэше
        появлялась и жила там вечно.

        Чем это плохо (воспроизведено на живом стенде 2026-08-23, дефект
        наблюдался у DB-стока, разделяющего ту же модель кэша):

        * запись протухает — дальнейшие обновления идут полистовыми дельтами
          и словаря не касаются (в строках БД жили ``14.5`` в словаре и
          ``14.3`` в листе одновременно);
        * префикс-чистка по MISSING-дельте её не видит: удаление
          ``…plugins.capture`` снимает лист ``…plugins.capture.capture_fps``,
          но ПРЕДКА ``…plugins`` не трогает — числа ушедшего писателя
          переживают собственное снятие.

        Пустой словарь листьев не даёт вовсе и в кэш не кладётся: узел есть,
        значений нет.
        """
        if isinstance(value, dict):
            if not value:
                return
            for key, nested in value.items():
                self._cache_put(f"{path}.{key}", nested)
            return
        self._cache[path] = value

    def _update_cache(self, deltas: list[Delta]) -> None:
        """Обновить кэш на основе списка дельт.

        Правила:
        - delta.new_value is MISSING → удалить path И ВСЁ ПОДДЕРЕВО под ним
        - иначе → записать delta.new_value в кэш

        Почему поддерево, а не точечный ``pop(delta.path)``: кэш держит ЛИСТЬЯ
        (merge порождает по дельте на лист, ключ кэша — полный путь листа), а
        удаление узла приходит ОДНОЙ дельтой на КОРЕНЬ поддерева —
        :meth:`TreeStore.delete` снимает ровно один узел и возвращает одну
        ``Delta`` с ``new_value=MISSING`` на его пути (``core/tree_store.py``).
        Точного совпадения с ключами-листьями тогда не бывает никогда, и
        точечный ``pop`` — молчаливый no-op: кэш продолжает отдавать показания
        писателя, которого в дереве уже нет.

        Граница — точка-разделитель, как в ``TelemetryReadModel._purge_subtree``
        (``telemetry_read_model.py:256``): чистятся ``path`` и ключи с префиксом
        ``path + "."``, а не ``path`` как голая подстрока — иначе удаление
        ``...plugins.capture`` снесло бы и ``...plugins.capture2.fps``.

        Args:
            deltas: список Delta для обновления кэша.
        """
        if self._resync_inflight_id is not None:
            # Окно ресинхронизации открыто: запоминаем, что этот путь только что
            # изменился живой дельтой — снимок не должен его откатить (ADR-SS-022).
            self._record_resync_dirty(deltas)

        for delta in deltas:
            if delta.new_value is MISSING:
                # Удаление узла — вместе с поддеревом (см. докстринг).
                self._cache.pop(delta.path, None)
                dotted = delta.path + "."
                stale = [key for key in self._cache if key.startswith(dotted)]
                for key in stale:
                    del self._cache[key]
            else:
                self._cache_put(delta.path, delta.new_value)

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

    # Таймаут ожидания ответа для router.request() (ADR-SS-016) — совпадает
    # с дефолтом RouterManager.request(), чтобы поведение не расходилось.
    _SYNC_REQUEST_TIMEOUT = 5.0

    @staticmethod
    def _unwrap_envelope(envelope: object) -> dict | None:
        """Развернуть конверт ответа RouterManager в ответ ОБРАБОТЧИКА.

        Конверт ``reply_to_request``: ``{"success": bool, "result": <ответ
        handler'а>}``. Неуспех/не-dict → None («ответа нет»), это и есть
        fail-open политика вызывающих (см. :meth:`_send_sync`).

        Общий для синхронного (:meth:`_send_sync`) и асинхронного
        (:meth:`_on_resync_response`) путей — иначе два разбора одного конверта
        разъехались бы при первой же правке протокола.
        """
        if not isinstance(envelope, dict) or envelope.get("success") is False:
            return None
        result = envelope.get("result")
        return result if isinstance(result, dict) else envelope

    def _send_sync(self, msg: dict) -> dict | None:
        """Отправить IPC-сообщение синхронно и вернуть ОТВЕТ ОБРАБОТЧИКА.

        ADR-SS-016 (ревью Ф4.9, PLAUSIBLE-6, 2026-07-11): у реального
        RouterManager `send()` — fire-and-forget поверх канала (кладёт
        сообщение в очередь и сразу возвращает статус ДОСТАВКИ в очередь,
        например `{"status": "success", "channel": "ctrl"}`), а НЕ ответ
        обработчика на другом конце. Настоящий request/response с ожиданием
        ответа — отдельный метод `router.request()` (блокирует по
        correlation_id до прихода `type=="response"` или таймаута).

        Поэтому:
          - Если router поддерживает `request()` (реальный RouterManager) —
            используем его и разворачиваем `envelope["result"]` (конверт
            reply_to_request: `{"success": bool, "result": <ответ handler'а>}`).
          - Иначе (router — тестовый дубль, реализующий `send()` КАК
            request-reply напрямую: `InMemoryRouter`/`MockRouter`/
            `_RelayRouter`) — используем `send()` как раньше, обратная
            совместимость всего существующего test suite сохранена.

        Fail-open: таймаут/ошибка транспорта/некорректный ответ → None.
        Вызывающий код (`get`, `get_subtree`, `subscribe`, `_resync`) уже
        трактует None как "ответа нет" и не падает.

        Args:
            msg: IPC-сообщение для отправки.

        Returns:
            dict с ответом обработчика или None.
        """
        if self._router is None:
            return None

        request_fn = getattr(self._router, "request", None)
        if callable(request_fn):
            try:
                envelope = request_fn(msg, timeout=self._SYNC_REQUEST_TIMEOUT)
            except RouterReentrantRequestError:
                # НЕ fail-open: нарушение контракта — ошибка программиста, а не
                # отказ транспорта. Проглотить его здесь значит превратить
                # ГРОМКИЙ отказ роутера в тихий no-op: вызывающий получит None,
                # прочитает его как «ответа нет» и поедет дальше с пустым
                # снимком. Ровно это показала инъекция INJ-9 при починке 2026-08-23
                # (откат ухода resync с приёмного потока ПРИ живой проверке
                # контракта дал не простой, а молча отключённый resync).
                #
                # Логом здесь не обойтись, и это измерено, а не предположено:
                # за 22-минутный прогон на стенде StateProxy обязан был написать
                # ~260 предупреждений о таймаутах, а в 60 файлах логов нет НИ ОДНОГО
                # упоминания 'StateProxy' (при том что WARNING других источников
                # есть в 17 файлах). Пока эта немота не разобрана, единственный
                # способ сделать отказ заметным — дать исключению пройти:
                # диспетчер роутера ловит его и пишет СВОИМ логгером, который
                # в логах виден.
                raise
            except Exception as exc:
                self._log_error(f"StateProxy '{self._process_name}': ошибка request() '{msg.get('command')}': {exc}")
                return None
            unwrapped = self._unwrap_envelope(envelope)
            if unwrapped is None:
                self._log_warning(
                    f"StateProxy '{self._process_name}': request() '{msg.get('command')}' не получил ответа: {envelope}"
                )
            return unwrapped

        try:
            return self._router.send(msg)
        except Exception as exc:
            self._log_error(
                f"StateProxy '{self._process_name}': ошибка синхронной отправки '{msg.get('command')}': {exc}"
            )
            return None
