# -*- coding: utf-8 -*-
"""Порт наблюдений процесса: ``ObservationManager`` — четвёртый канонический слот.

Ф3 плана «порт наблюдений», задача 3.1. Механика уровней
(``state.plugins.<писатель>.<имя>`` — «сколько СЕЙЧАС», перезапись, без истории)
получает менеджера на общей базе трёх братьев и становится доступной ЛЮБОМУ
компоненту процесса через слот ``observation``, ровно как logger/stats/error.

**Что здесь НЕ происходит: хранилище не переезжает и не переписывается.**
Значения по-прежнему лежат в :class:`~...process_module.heartbeat.telemetry.PluginLevels`
(Ф1 — ключ первого уровня писатель; Ф2 — ведомость ушедших), и порт его
ОБОРАЧИВАЕТ. Переезд самого хранилища в этот модуль — отдельная работа с
отдельной ценой: у него семь читателей (тик heartbeat, опрос, три дороги
``PluginContext``, два набора тестов), и смешивать «завести слот» с «переложить
хранилище» значило бы делать невозможным ответ на вопрос, что именно сломалось.
Названная цена ЭТОГО решения: файл из ``statistics_module`` тянет
``process_module`` — направление зависимости, обратное общему
(``process_module`` тянет ``statistics_module`` ради ``StatsManager``). Кольцо
разорвано ленивым импортом (:func:`_telemetry`), а не архитектурой; закрывается
переездом хранилища сюда, когда он будет отдельной задачей (ADR-SM-012).

**Часы у heartbeat, правда у порта.** Публикация в дерево остаётся у
``ProcessHeartbeat``: он решает КОГДА (тик, publisher-гейт) и шлёт ОДИН merge за
тик (Р3.5-12). Порт отвечает на «что сейчас в хранилище» — три вопроса тика
(:meth:`ObservationPort.level_names`, :meth:`ObservationPort.collect_subtree`,
:meth:`ObservationPort.departed_writers`) и подтверждение доставки снятия
(:meth:`ObservationPort.note_delete_delivered`). До Ф3 heartbeat доставал
состояние сам — ``getattr(services, PLUGIN_LEVELS_ATTR)`` в трёх местах, с
дублированной duck-typed проверкой в каждом; теперь эта константа в heartbeat не
упоминается вовсе.

**Два класса, и второй — не украшение.** :class:`ObservationPort` — механизм
(вид на хранилище); :class:`ObservationManager` — тот же механизм плюс
жизненный цикл ``ChannelRoutingManager`` и место в слоте. Разделены потому, что
у heartbeat обязана быть ОДНА дорога к уровням, а слот бывает не зарегистрирован
(процесс, поднятый не через ``ProcessManagers.register_all``: тестовые дубли,
ранние стадии старта). Строить ради такого случая настоящего
``ChannelRoutingManager`` на каждом тике — цена ни за что; ронять или молчать —
регресс (сегодня heartbeat в этом случае читает уровни и публикует их).
:func:`observation_port` возвращает менеджер из слота, а при его отсутствии —
короткоживущий вид на то же самое хранилище.
"""

from __future__ import annotations

import threading
from typing import Any, Dict, Iterable, Optional, Tuple

from ...channel_routing_module import ChannelRoutingManager
from ...observability_declarations import declare_metric as _declare_metric

__all__ = [
    "OBSERVATION_SLOT",
    "ObservationManager",
    "ObservationPort",
    "PluginObservationHandle",
    "observation_port",
]

#: Имя канонического слота ``ObservableMixin`` — четвёртого рядом с
#: ``logger``/``stats``/``error``.
#:
#: Константа, а не литерал по месту: имя слота читают ТРИ разных файла в двух
#: модулях (``process_managers.register_all``, ``plugins/base.py``,
#: ``process_heartbeat.py`` — через :func:`observation_port`), и разъехавшийся
#: литерал дал бы «порт зарегистрирован, но никто его не находит» — отказ,
#: который выглядит как штатный фолбэк и потому не виден ни по одному голосу.
OBSERVATION_SLOT = "observation"


def _telemetry():
    """Модуль хранилища уровней. Импорт ЛЕНИВЫЙ, и это про порядок, не про стиль.

    ``process_module`` импортирует ``statistics_module`` (``StatsManager`` в
    ``ProcessManagers.create_all``), а этому файлу нужен ``process_module``
    (хранилище, которое он оборачивает). Импорт на уровне модуля сделал бы
    порядок загрузки значимым: кто первым — тот и получает частично
    инициализированный пакет. Тот же жест и по той же причине уже стоит в
    ``PluginContext.publish_metric`` и в трёх местах ``ProcessHeartbeat``.

    Цена названа: словарь ``sys.modules`` на вызов. Вызовов — до четырёх на тик
    процесса (порядка секунды), то есть цена ниже разрешения часов Windows.
    """
    from ...process_module.heartbeat import telemetry

    return telemetry


class PluginObservationHandle:
    """Хендл писателя: identity привязана к объекту, а не ездит аргументом.

    Образец — ``ProcessHandle`` у ``SharedResourcesManager``: имя адресата
    называется ОДИН раз, при получении хендла, и дальше не повторяется на каждом
    вызове. ``port.for_plugin("capture").publish("fps", 30.0)`` вместо
    ``port.publish("fps", 30.0, writer="capture")``.

    Почему это не сахар. Писатель — СЕГМЕНТ ПУТИ
    (``state.plugins.<писатель>.<имя>``, Ф1 «владение = путь»), и три дороги
    ``PluginContext`` — объявление, публикация, снятие — обязаны назвать один и
    тот же сегмент. Разойдись они хоть в одном звене, публикация уехала бы в
    одно поддерево, а снятие чистило другое: уровень остановленного плагина
    остался бы жить, а симптом («захват остановлен, а частота идёт») искали бы в
    камере. Хендл делает расхождение невыразимым — сегмент берётся из одного
    поля.

    ``for_worker(...)`` здесь НЕТ намеренно: план называет его заделом, а не
    задачей, и у него сегодня нет ни одного вызывающего. Пустой метод-обещание
    был бы контрактом, за который никто не отвечает.
    """

    __slots__ = ("_port", "_writer")

    def __init__(self, port: "ObservationPort", writer: str) -> None:
        self._port = port
        self._writer = str(writer)

    @property
    def writer(self) -> str:
        """Сегмент пути, под которым едут уровни этого хендла."""
        return self._writer

    def publish(self, name: str, value: Any) -> None:
        """Отдать текущее значение уровня ``name`` от этого писателя."""
        self._port.publish(name, value, self._writer)

    def declare(self, name: str) -> str:
        """Внести имя уровня в каталог телеметрии от этого писателя."""
        return self._port.declare(name, self._writer)

    def retract(self) -> int:
        """Снять всё, что опубликовал этот писатель. Возвращает число снятых."""
        return self._port.retract(self._writer)

    def __repr__(self) -> str:  # pragma: no cover — диагностика
        return f"PluginObservationHandle(writer={self._writer!r})"


class ObservationPort:
    """Вид на хранилище уровней процесса — механизм без жизненного цикла.

    Держит ОДНУ ссылку на :class:`PluginLevels` и переводит вопросы читателей
    (тик heartbeat, опрос, будущая секция ``introspect.observability``) в вызовы
    хранилища. Своего состояния уровней здесь нет ни байта: заведи порт
    собственную копию — и «сколько сейчас» стало бы двумя разными ответами,
    расходящимися тем тише, чем реже смотрят.

    **Исключения наружу не глушатся.** Порт — не место для решения «телеметрия
    не критична для такта»: это решение публикатора, у него есть и лог, и
    контекст такта, и оно там уже принято (три ``try/except`` в
    ``ProcessHeartbeat`` с голосом в debug). Второй, молчаливый предохранитель
    здесь означал бы, что отказ хранилища не увидит никто.
    """

    __slots__ = ("_levels",)

    def __init__(self, levels: Any) -> None:
        """
        Args:
            levels: хранилище :class:`PluginLevels`, которое обслуживает порт.
        """
        self._levels = levels

    # ------------------------------------------------------------------
    # Хранилище
    # ------------------------------------------------------------------

    def levels(self) -> Any:
        """Хранилище, которое обслуживает этот порт.

        **Единственный шов, через который ходят все девять дорог ниже** — и
        единственное, что переопределяет :class:`ObservationManager` (ему
        хранилище выдаёт держатель, а не конструктор). Позови любая из них
        ``self._levels`` напрямую — и override перестал бы действовать ровно на
        ней одной; первая редакция так и сделала, и приёмка покраснела на
        ``AttributeError: 'NoneType' object has no attribute 'publish'``.
        """
        return self._levels

    # ------------------------------------------------------------------
    # Чтение — вопросы тика и опроса
    # ------------------------------------------------------------------

    def level_names(self) -> set:
        """Имена листьев ВСЕХ писателей — кандидаты publisher-гейта на тике.

        Отдельный вопрос от :meth:`collect_subtree`, потому что задаётся РАНЬШЕ:
        гейт решает «поедет ли имя» до того, как значения собраны, и каталог
        объявлений на этот вопрос не отвечает (необъявленное имя обязано ехать
        под дефолтным правилом конфига).
        """
        return set(self.levels().names())

    def collect_subtree(self, allowed_metrics: Optional[Iterable[str]] = None) -> Dict[str, Any]:
        """Поддерево ``{"plugins": {писатель: {имя: значение}}}`` для секции ``state``.

        Общий шов push и poll — тот же сборщик, что и до Ф3
        (``build_plugin_levels``), а не вторая копия проекции: разойдись они,
        «опрос отдаёт то же, что push» стало бы ложью, которую видно только на
        стенде (ADR-PM-035).

        Args:
            allowed_metrics: разрешённые на этом тике ИМЕНА ЛИСТЬЕВ; ``None`` →
                все (так зовёт опрос — гейт про публикацию, а не про то, что
                процесс знает о себе).

        Returns:
            Пустой dict, если хранилище пусто или всё придержал гейт.
        """
        return _telemetry().build_plugin_levels(self.levels().publications(), allowed_metrics)

    def publications(self) -> Dict[str, Dict[str, Any]]:
        """Сырой снимок ``писатель → {имя → значение}`` (двухуровневая копия)."""
        return self.levels().publications()

    def departed_writers(self) -> Tuple[str, ...]:
        """Писатели, чьё поддерево ещё положено утверждать удалённым (Ф2)."""
        return tuple(self.levels().departed_writers())

    def note_delete_delivered(self, writer: str) -> None:
        """Списать одно утверждение удаления поддерева ``writer``."""
        self.levels().note_delete_delivered(writer)

    # ------------------------------------------------------------------
    # Запись — дороги PluginContext
    # ------------------------------------------------------------------

    def publish(self, name: str, value: Any, writer: str) -> None:
        """Запомнить текущее значение уровня ``name`` от писателя ``writer``."""
        self.levels().publish(name, value, writer)

    def retract(self, writer: str) -> int:
        """Снять всё, что опубликовал ``writer``. Возвращает число снятых записей."""
        return int(self.levels().retract(writer))

    def declare(self, name: str, writer: str) -> str:
        """Внести имя уровня в каталог телеметрии от имени ``writer``.

        Каталог — процессный и общий для обеих плоскостей объявлений
        (``observability_declarations``), а не собственность порта: по нему
        publisher-гейт резолвит правила конфига, и второй каталог означал бы
        второй ответ на «какие имена бывают». Порт здесь ИМЕНОВАННАЯ ДОРОГА, а
        не хранилище: он даёт объявлению тот же слот, что и публикации, чтобы у
        ``PluginContext`` не осталось дороги в обход порта.
        """
        return _declare_metric(name, owner=str(writer))

    # ------------------------------------------------------------------
    # Хендл
    # ------------------------------------------------------------------

    def for_plugin(self, writer: str) -> PluginObservationHandle:
        """Хендл писателя ``writer`` — см. :class:`PluginObservationHandle`."""
        return PluginObservationHandle(self, writer)

    def __repr__(self) -> str:  # pragma: no cover — диагностика
        return f"ObservationPort(levels={self._levels!r})"


class ObservationManager(ChannelRoutingManager, ObservationPort):
    """Порт наблюдений как менеджер процесса — слот ``observation``.

    Наследник ``ChannelRoutingManager`` по образцу ``StatsManager``
    (ADR-SM-001), а не прямой наследник ``BaseManager``: общая база трёх братьев
    даёт реестр каналов, учёт потерь и ``reconfigure`` — то самое хозяйство, в
    которое задача 3.2 понесёт записи уровней (kind=observation), и заводить его
    заново значило бы получить четвёртую плоскость с собственным счётом потерь.

    Жизненный цикл — базовый, без единого override: ``initialize`` (буфера нет →
    просто ``is_initialized = True``) и ``shutdown`` (flush по пустому буферу,
    закрытие пустого реестра каналов). Переопределять их сейчас было бы
    переписыванием базы своими словами.

    **Хранилище не создаётся в конструкторе и не кэшируется.**
    :meth:`levels` резолвит его на КАЖДОМ обращении через
    ``get_or_create_plugin_levels(self.process)`` — ту же функцию, которой
    пользуется ленивый фолбэк ``PluginContext``. Два следствия, оба нужны:

    * **одна правда.** Атрибут ``services.plugin_levels`` остаётся единственным
      держателем состояния; закэшируй порт ссылку в ``__init__`` — и подмена
      атрибута (её делают три существующих набора тестов) дала бы два
      расходящихся ответа на «сколько сейчас», причём молча;
    * **создание не приезжает раньше публикации.** Менеджер рождается в
      ``ProcessManagers.create_all`` у КАЖДОГО процесса, включая те, у которых
      плагинов нет вовсе. Создай он хранилище в конструкторе — у таких процессов
      появился бы пустой ``plugin_levels``, а «атрибута нет» перестало бы
      отличаться от «атрибут пуст».

    **Известное расхождение, названное, а не заговорённое.** Менеджер,
    построенный с ``process=None`` и всё же положенный в слот чужих сервисов,
    обслуживает СВОЁ хранилище — публикации через порт увидит порт (и heartbeat,
    который читает через порт), но не увидит прямой
    ``get_or_create_plugin_levels(services)``. В сборке это не достижимо
    (``_create_observation_manager`` всегда передаёт процесс), поэтому отказом не
    оформлено; сторожится авторским hazard-тестом, чтобы расхождение осталось
    описанным поведением, а не сюрпризом.
    """

    def __init__(
        self,
        manager_name: str = "ObservationManager",
        config: Optional[Any] = None,
        process: Optional[Any] = None,
        managers: Optional[Dict[str, Any]] = None,
        **kwargs: Any,
    ) -> None:
        """
        Args:
            manager_name: имя менеджера (в сборке — ``observation_<процесс>``).
            config: конфиг CRM. Своей секции у порта пока нет — уровни живут
                своим гейтом (``telemetry.publish``), а каналы появятся в 3.2.
            process: сервисы процесса — держатель хранилища уровней.
            managers: словарь для ``ObservableMixin`` (в сборке — logger).
        """
        ChannelRoutingManager.__init__(
            self,
            manager_name=manager_name,
            config=config,
            managers=managers or {},
            process=process,
            **kwargs,
        )
        # Локальное хранилище — на случай, когда держателя нет вовсе
        # (``process=None``) или он не принимает атрибут (иммутабельный дубль,
        # ``__slots__``). Создаётся не здесь, а в :meth:`levels` по первому
        # запросу: у процесса без плагинов оно так и не понадобится.
        ObservationPort.__init__(self, None)
        self._levels_lock = threading.Lock()

    # ``__slots__`` у ObservationPort — а у менеджера обычный ``__dict__``
    # (его даёт ChannelRoutingManager), поэтому ``_levels`` кладётся в него.

    def levels(self) -> Any:
        """Хранилище уровней процесса — резолвится на каждом обращении.

        Порядок: держатель (``self.process``) → его атрибут ``plugin_levels``
        (создаётся лениво той же функцией, что и у фолбэка) → локальное
        хранилище порта, если держателя нет или он атрибут не принял.

        Лок стоит только на ветке локального хранилища, и не «на всякий случай»:
        два потока, спросившие уровни впервые одновременно, создали бы ДВА
        ``PluginLevels``, и публикации разъехались бы по ним — половина значений
        исчезла бы без единого голоса. Воспроизведено авторским hazard-тестом
        (класс про одновременный первый доступ), а не выведено рассуждением.

        Ветка держателя своим локом НЕ накрыта, и это названный потолок, а не
        недосмотр: там ровно та же гонка живёт ВНУТРИ
        ``get_or_create_plugin_levels`` (два потока, оба не нашедшие атрибут,
        оба зовут ``setattr``, и проигравший уносит свой экземпляр с собой).
        Она существует с Ф1, порт её не вносит и не может закрыть отсюда — лок
        вокруг чужого ``setattr`` не помешал бы третьему вызывающему,
        обращающемуся к функции напрямую. Закрывается там же, где живёт.
        """
        host = self.process
        if host is not None:
            store = _telemetry().get_or_create_plugin_levels(host)
            if store is not None:
                return store
        with self._levels_lock:
            if self._levels is None:
                self._levels = _telemetry().PluginLevels()
            return self._levels

    # Чтение/запись наследуются от ObservationPort целиком — они обращаются к
    # хранилищу ТОЛЬКО через ``self.levels()``, поэтому override одного метода
    # переводит на резолв все девять дорог сразу.

    def __repr__(self) -> str:  # pragma: no cover — диагностика
        return f"ObservationManager(manager_name={self.manager_name!r})"


def observation_port(services: Any, *, create: bool = False) -> Optional[ObservationPort]:
    """Порт наблюдений процесса — ЕДИНСТВЕННАЯ дорога читателей к уровням.

    Резолв в три ступени:

    1. слот ``observation`` в реестре ``ObservableMixin`` — боевая дорога после
       ``ProcessManagers.register_all``;
    2. существующее хранилище ``services.plugin_levels`` — короткоживущий вид
       для процесса, поднятого не через ``register_all`` (тестовые дубли, ранние
       стадии старта). Незарегистрированный слот, как и до Ф3, не роняет
       вызывающего и не отменяет уровни;
    3. ``None`` — уровней у этого процесса нет и (при ``create=False``) заводить
       их незачем.

    **``create`` — это ИМЕНОВАННЫЙ ФОЛБЭК, а не костыль, и он обязан пережить
    Ф3.** Публикация плагина идёт из ``configure()``, то есть РАНЬШЕ ``start()``
    — раньше, чем у процесса вообще появились менеджеры. Читатель (тик
    heartbeat) зовёт с ``create=False``: у процесса без единой публикации
    создавать хранилище на каждом тике незачем, а «атрибута нет» перестало бы
    отличаться от «атрибут пуст». Писатель (``PluginContext``) зовёт с
    ``create=True``: ему хранилище нужно именно сейчас.

    **Две ступени распознаются РАЗНЫМИ проверками, и это не разнобой.** Слот —
    ПО ПРОТОКОЛУ (есть вызываемый ``collect_subtree``), довод тот же, что у
    ``ObservableMixin._manager_has_method``: в слоте может оказаться duck-typed
    порт, а посторонний объект под именем ``observation`` не должен уводить
    читателя в тихий отказ — он проваливается на ступень 2, к настоящему
    хранилищу. Атрибут — по ``isinstance``, дословно как в
    ``get_or_create_plugin_levels``: у атрибута процесса уже есть владелец с
    принятым решением о том, что считать хранилищем, и вторая, более мягкая
    проверка того же атрибута означала бы два ответа на один вопрос.

    Args:
        services: сервисы процесса (``ProcessModule`` или его дубль).
        create: завести хранилище, если его ещё нет.

    Returns:
        Порт либо ``None``. ``None`` = названный no-op у вызывающего, а не
        исключение: уровень не имеет права ронять линию.
    """
    if services is None:
        return None

    get_manager = getattr(services, "get_manager", None)
    if callable(get_manager):
        manager = get_manager(OBSERVATION_SLOT)
        if manager is not None and callable(getattr(manager, "collect_subtree", None)):
            return manager

    telemetry = _telemetry()
    if create:
        store = telemetry.get_or_create_plugin_levels(services)
    else:
        store = getattr(services, telemetry.PLUGIN_LEVELS_ATTR, None)
        if not isinstance(store, telemetry.PluginLevels):
            store = None
    return None if store is None else ObservationPort(store)
