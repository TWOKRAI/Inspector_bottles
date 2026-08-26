"""ProcessModulePlugin + PluginContext — ядро plugin-системы.

Единый интерфейс для всех плагинов — от мощных (webcam: SHM, workers,
ring buffer, middleware) до простых (color_mask: вход → cv2 → выход).

State machine (от GStreamer):
    IDLE → READY → RUNNING → STOPPED
           ↑          ↓
           ←── PAUSED ←

PluginContext даёт доступ ко всему что есть в ProcessModule,
плагин использует только то что ему нужно.
"""

from __future__ import annotations

import functools
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from typing import TYPE_CHECKING, Any, Callable, ClassVar

from ..managers.observability_flight import FLIGHT_RECORDER_ATTR, NO_RECORDER_KNOBS, note_flight_disabled
from ..managers.observability_wiring import (
    CARRIER_FAILURE_KEY,
    DOCUMENT_SINK_ATTR,
    EVENT_SELECTOR_ATTR,
    carrier_failures,
    note_document_refused,
    note_event_refused,
    note_document_without_sink,
    note_metric_without_plane,
)
from .interfaces import IProcessServices
from .manifest import PLUGIN_API_VERSION

if TYPE_CHECKING:
    from ..health import HealthReporter
    from .metrics import PluginMetrics


def for_each(func):
    """Сахар: per-item функция -> process(items) -> list[dict].

    Применяется к методу process плагина.
    Возврат декорируемой функции:
      dict       -> 1:1
      list[dict] -> 1:N (fan-out)
      None       -> фильтрация (item отбрасывается)
    """

    @functools.wraps(func)
    def wrapper(self, items: list[dict]) -> list[dict]:
        result = []
        for item in items:
            out = func(self, item)
            if out is None:
                continue
            if isinstance(out, list):
                result.extend(out)
            else:
                result.append(out)
        return result

    return wrapper


class PluginState(str, Enum):
    """Состояние плагина (от GStreamer element states)."""

    IDLE = "idle"  # Зарегистрирован, не инициализирован
    READY = "ready"  # configure() выполнен, ресурсы выделены
    RUNNING = "running"  # start() выполнен, данные текут
    PAUSED = "paused"  # Приостановлен, ресурсы удерживаются
    STOPPED = "stopped"  # shutdown() выполнен, ресурсы освобождены


class PluginContext:
    """Фасад над ProcessModule — всё что нужно плагину, без прямой связи с кишками.

    Создаётся GenericProcess'ом и передаётся в каждый плагин.
    Для каждого плагина создаётся копия с plugin-specific config.
    """

    def __init__(
        self,
        services: IProcessServices,
        config: dict[str, Any] | None = None,
        io: Any | None = None,
        registers: Any | None = None,
        plugin_name: str | None = None,
    ) -> None:
        self.services = services
        self.process_name = services.name
        self.config = config or {}
        # Ф2.1: имя источника для штампа записей. У базового ctx его нет —
        # штампуется имя процесса; per-plugin копия из with_config несёт своё.
        self.plugin_name = plugin_name

        # Менеджеры через Protocol (плагин использует только то, что ему нужно)
        self.worker_manager = getattr(services, "worker_manager", None)
        self.command_manager = getattr(services, "command_manager", None)
        self.router_manager = getattr(services, "router_manager", None)
        self.memory_manager = getattr(services, "memory_manager", None)

        # IPC facade (передаётся отдельно — ProcessIO app-specific, не часть Protocol)
        self.io = io

        # Registers (Phase 5.9) — RegistersManager | None
        # Плагин читает self._reg = ctx.registers.get_register("plugin_name")
        self.registers = registers

        # StateProxy (Phase 8) — из services
        self.state_proxy = getattr(services, "state_proxy", None)

        # Логирование и IPC — публичные методы Protocol.
        # Ф2.1: если контекст принадлежит конкретному плагину — записи уходят
        # под его именем, а не под именем процесса. Штамп ставится здесь, а не
        # на call-site: плагины зовут ctx.log_info(msg) в сотнях мест, и
        # правка call-sites не входит в задачу по построению.
        # A2 (Б-2): ВСЯ пятёрка, а не log_info/log_error. Плагин, звавший
        # `ctx.log_warning` в ветке штатной деградации (camera_service: «hub
        # недоступен»), получал AttributeError и ронял старт захвата — при том
        # что докстринг той ветки обещал её не роняющей. Метод терялся ровно
        # здесь: протокол его объявлял, ObservableMixin имел, фасад — нет.
        #
        # Явная пятёрка, а не `__getattr__`-проксирование: проксирование делает
        # ЛЮБОЕ имя «существующим», то есть превращает опечатку в молчаливый
        # no-op, и перестаёт быть обязательством, которое можно проверить.
        self.log_debug: Callable[[str], None] = self._stamped(services.log_debug)
        self.log_info: Callable[[str], None] = self._stamped(services.log_info)
        self.log_warning: Callable[[str], None] = self._stamped(services.log_warning)
        self.log_error: Callable[[str], None] = self._stamped(services.log_error)
        self.log_critical: Callable[[str], None] = self._stamped(services.log_critical)
        self.send_message: Callable = getattr(services, "send_message", None)  # type: ignore[assignment]
        self.receive_message: Callable = getattr(services, "receive_message", None)  # type: ignore[assignment]

        # Этап 6, 1.1: штамп источника у метрик — тот же довод, что у ``module=``
        # в логах. Без него две метрики ``frames_processed`` из разных плагинов
        # одного процесса сливаются в ОДНУ серию, и разошедшиеся числа выглядят
        # как одно правдоподобное — класс «процессный счётчик не по ключу».
        # Словарь считается ОДИН раз здесь, а не на каждом вызове: путь горячий.
        # ``StatsManager._merged_tags`` собирает новый dict и этот не мутирует —
        # общий экземпляр безопасен (сверено по коду, не по обещанию).
        self._stats_tags: dict[str, str] | None = {"plugin": plugin_name} if plugin_name else None

    def _stamped(self, log_fn: Callable[..., None]) -> Callable[..., None]:
        """Обернуть log-функцию процесса штампом имени плагина (Ф2.1).

        Без имени плагина возвращает исходную функцию — лишней обёртки на
        горячем пути не появляется. ``functools.partial`` вместо lambda:
        сохраняет пикл-совместимость там, где сам ``log_fn`` пиклится.

        ``module=`` идёт keyword'ом, а ``ObservableMixin._log_*`` ставит свой
        штамп через ``setdefault`` — поэтому имя плагина выигрывает у имени
        процесса, а явный ``module=`` на call-site выигрывает у обоих.
        """
        if not self.plugin_name:
            return log_fn
        return functools.partial(log_fn, module=self.plugin_name)

    def with_config(
        self,
        plugin_config: dict[str, Any],
        registers: Any | None = None,
        plugin_name: str | None = None,
    ) -> PluginContext:
        """Создать копию контекста с plugin-specific конфигом.

        ``plugin_name`` — имя источника для штампа записей (Ф2.1).
        """
        new = PluginContext(
            services=self.services,
            config=plugin_config,
            io=self.io,
            registers=registers,
            plugin_name=plugin_name,
        )
        # state_proxy ставится оркестратором ПОСЛЕ __init__ (процесс хранит его как
        # services._state_proxy — приватный атрибут, недоступный через публичный
        # services.state_proxy, который читает __init__). Без явного проброса копия
        # теряет proxy → per-plugin ctx.state_proxy=None, и плагины не видят дерево
        # состояний (latent gap: затрагивал capture/color_mask/telemetry_sink).
        new.state_proxy = self.state_proxy
        return new

    @property
    def health(self) -> "HealthReporter":
        """Фасад наблюдаемости отказов процесса (Ф2 Task 2.1).

        ``ctx.health.report_error(exc, context=..., throttle=...)`` — учесть
        проглоченную/обработанную ошибку; ``set_status(...)`` / ``degraded(...)`` —
        явная деградация. Публикуется в state-дерево через heartbeat процесса
        (``processes.<name>.health.*`` — см. ``..health.schema``).

        **Чем это отличается от ``ctx.log_error`` (ADR-PM-030, задача C2).**
        Разъёмы разведены по НАМЕРЕНИЮ, и разница наблюдаема в файлах:

        * ``ctx.log_error("строка")`` — диагностическая строка, плоскость логов
          (``system.log``/``messages.log``). Инцидентом она не становится;
        * ``ctx.health.report_error(exc)`` — ИНЦИДЕНТ: плоскость ошибок
          (``errors.log``/``critical.log``) **плюс** дросселированная строка в
          журнал **плюс** счётчик health и подряд-счётчик breaker.

        До C2 второе было названием без обязательства: прогон
        ``backend_ctl/probes/probe_c2_error_route.py`` показал, что
        ``report_error`` уходила в ``system.log``, а плоскость ошибок не видела
        от плагинов ничего. Дорога туда теперь есть, и её сторожит тест на
        МАРШРУТ (``tests/test_error_route.py``), а не на имя метода.

        Один :class:`HealthState` на процесс (агрегат уровня процесса); reporter
        подставляет имя плагина как context по умолчанию. Кэшируется на ctx, чтобы
        не пересоздавать при каждом обращении из горячего пути обработки.
        """
        reporter = getattr(self, "_health_reporter", None)
        if reporter is None:
            from ..health import HealthReporter, get_or_create_health_state

            state = get_or_create_health_state(self.services)
            reporter = HealthReporter(state, source=getattr(self, "_plugin_name", "") or "")
            self._health_reporter = reporter
        return reporter

    # ------------------------------------------------------------------
    # Ф8.7 — плоскость документов: дорога приложения в долговечное хранилище
    # ------------------------------------------------------------------

    def write_document(
        self,
        kind: str,
        summary: str = "",
        /,
        *,
        source: str | None = None,
        ts: float | None = None,
        **fields: Any,
    ) -> bool:
        """Записать документ — запись о РЕШЕНИИ, а не о происходившем.

        Вердикт о качестве изделия живёт годами, диагностика — дни (файлы
        ротируются по 6.9: 7 суток / 200 МБ). Поэтому у документа своё
        хранилище со своим сроком, и попадание туда НЕ зависит от severity:
        правило допуска здесь структурное — свой приёмник, а не фильтр по
        уровню, который надо не забыть настроить (ADR-CRM-013, ADR-PM-028).

        Плоскость у процесса ОДНА: сток сшивает ``wire_document_sink`` и
        публикует на процессе, аудит смен наблюдаемости пишет в тот же
        экземпляр. Заведи приложение свой стор — писателей на файл стало бы
        вдвое больше, а «один писатель на процесс» перестало бы быть правдой.

        Args:
            kind: род документа (``"verdict"``, ``"audit"``, …). Задаёт срок
                хранения: уборка берёт его из ``retention_sec[kind]``, а род,
                которого в конфиге нет, не удаляется никогда.
            summary: человекочитаемая суть — то, что видно в списке без
                раскрытия payload.
            source: кто породил документ. По умолчанию имя плагина, а при его
                отсутствии — имя процесса: документ без «где» отвечает на
                «что решено», но не на «кем».
            ts: момент события, epoch-секунды. По умолчанию — сейчас. Параметр,
                а не глобальный вызов: тесту иначе пришлось бы патчить ``time``
                для всего процесса.
            **fields: прикладная часть, уезжает в ``payload`` как JSON.

        Returns:
            ``True`` — документ записан. ``False`` — плоскость не настроена
            (``observability.documents`` в конфиге нет) ЛИБО запись отказала.
            Два случая различает вызывающий: у ненастроенной плоскости отказов
            не бывает, а у настроенной каждый отказ уже посчитан стоком
            (``dropped``) и назван здесь строкой журнала.

        Note:
            Конверт (``kind``/``ts``/``source``/``summary``) кладётся ПОСЛЕ
            ``**fields``: прикладное поле с таким же именем не имеет права
            увести документ в чужой род — иначе срок хранения оказался бы
            функцией случайного совпадения имён.

            ``kind`` и ``summary`` — **позиционные** (``/``) именно ради этого.
            Будь они обычными параметрами, вызов ``write_document(KIND, s,
            **payload)`` с ключом ``kind`` в нагрузке падал бы TypeError'ом
            «got multiple values», то есть вердикт терялся бы с исключением
            прямо на линии — хуже подмены, от которой защита и ставилась
            (найдено собственным тестом конверта). Позиционные — и такой ключ
            спокойно уезжает в payload, а род остаётся тем, что попросили.
            ``source``/``ts`` оставлены именованными сознательно: одноимённый
            ключ нагрузки означает ровно их и правильно связывается с ними.

            **Цена — на вызывающем.** ``append`` идёт синхронно в SQLite:
            замер под конкуренцией шести процессов — медиана 3.6 мс, p95 82 мс,
            **max 928 мс**. Это бюджет РЕДКОГО события (отбраковка, смена
            настройки), а не кадра: на 25–60 FPS бюджет кадра 16–40 мс, и
            документ на каждый кадр остановил бы линию. Клиент обязан звать
            это на событии, а не на такте.
        """
        who = source if source is not None else (self.plugin_name or self.process_name or "")
        sink = getattr(self.services, DOCUMENT_SINK_ATTR, None)
        append = getattr(sink, "append", None)
        if not callable(append):
            # C3 (major-10): плоскость не объявлена — законное состояние, но не
            # БЕЗМОЛВНОЕ. Прежде здесь стоял голый `return False`: вердикт
            # исчезал без счётчика и без строки, тогда как у записей тот же
            # случай назван четвёртым классом потери
            # (`records_without_channels`). Голос — однократный, число — всегда.
            note_document_without_sink(self.services, str(kind), str(who))
            return False

        try:
            # Сборка конверта — ВНУТРИ try вместе с записью: приведение ``ts``
            # к float делается над значением, пришедшим от приложения, и мусор
            # в нём обязан стоить документа, а не линии.
            document = {
                **fields,
                "kind": str(kind),
                "ts": time.time() if ts is None else float(ts),
                "source": who,
                "summary": str(summary),
            }
            if append(document):
                return True
            # C3: отказ СТАТУСОМ был так же нем, как отсутствие плоскости.
            # Сток свой отказ считает (`DocumentStore.dropped`), но до C3 этот
            # счётчик не читал никто — потеря существовала и была недоступна
            # там, где о ней спрашивают.
            note_document_refused(self.services, str(kind), str(who))
            return False
        except Exception as exc:  # noqa: BLE001 — сбой хранилища не роняет линию
            # Но и не молчит: потерянный вердикт без следа — ровно тот класс
            # «проглоченный сбой», ради которого плоскость и заводилась.
            self.log_error(f"[documents] документ рода {kind!r} не записан: {exc!r}")
            note_document_refused(self.services, str(kind), str(who))
            return False

    # ------------------------------------------------------------------
    # Ф4 (задача 4.1) — широкая запись о единице работы
    # ------------------------------------------------------------------

    def write_event(
        self,
        kind: str,
        summary: str = "",
        /,
        *,
        unit: Any = None,
        decisive: bool = False,
        **fields: Any,
    ) -> bool:
        """Записать ОДНУ широкую запись о единице работы (изделии, кадре).

        Сегодня ответ на «почему изделие N забраковано» собирается по россыпи
        записей: вердикт в одном месте, счётчики в другом, тайминги в третьем.
        Широкая запись — весь контекст единицы В ОДНОЙ строке плоскости логов,
        находимой поиском по ``trace_id``.

        **Носителя своего нет** (РТ-4): это ``log_info`` процесса, то есть
        ``LogScope.BUSINESS`` + ``INFO`` — ровно то, чем широкая запись и должна
        быть. Отдельный порт записи означал бы второй слой ради имени, а
        документ-на-единицу (второй кандидат) стоил бы ``append`` в SQLite:
        медиана 3.6 мс, max 928 мс — бюджет редкого события, не потока.

        Args:
            kind: род единицы (``"inspection"``, ``"verdict"``). Ключ отбора и
                ключ счётчиков: лесенка ``first_n``/``every_mth`` считает ВНУТРИ
                рода.
            summary: человекочитаемая суть — то, что видно в строке без разбора
                полей.
            unit: сама единица работы (item кадра) — из неё берутся ``trace_id``
                и спаны. Не dict → полей не будет, но записи это не стоит.
            decisive: фронт решения. Мимо отбора ВСЕГДА: прорядить вердикт
                значило бы потерять то, ради чего запись заводилась.
            **fields: прикладная часть — уезжает в ``extra`` записи структурно.

        Returns:
            ``True`` — запись отдана плоскости логов. ``False`` — не отдана:
            прорежена отбором ЛИБО носитель отказал. Форма ответа одна на оба
            случая намеренно (тот же довод, что у ``write_document``): клиент и
            так обязан различать «записано» и «нет», а различить причины он всё
            равно не может — их различает readback
            (``introspect.observability -> events``: ``skipped`` против голоса об
            отказе).

        Note:
            **``trace_id`` едет в ТЕКСТЕ, а не только в полях.** Полнотекстовый
            индекс стора построен по ``message``/``module``/``process`` и НЕ
            смотрит в ``extra`` (тот же довод, что у ``snapshot_message``).
            Положи мы след только структурно — запись нашлась бы фильтром по виду
            и никогда по следу, то есть ровно на тот вопрос, ради которого она
            едет в стор, ответа бы не было. Формат текста ПОСТОЯНЕН
            (``event <род>: <суть> trace=<след>``) в том числе когда следа нет:
            переменная форма сломала бы поиск по образцу.

            **Конверт кладётся ПОСЛЕ ``**fields``** — дословно правило
            ``write_document``: прикладное поле с именем ``event``/``trace_id``/
            ``spans`` не имеет права увести запись в чужой род. ``kind`` и
            ``summary`` позиционные (``/``) по той же причине, что там: будь они
            обычными параметрами, вызов ``write_event(KIND, s, **payload)`` с
            ключом ``kind`` в нагрузке падал бы ``TypeError``'ом прямо на линии —
            хуже подмены, от которой защита и ставилась.

            **Прикладное поле с именем параметра НОСИТЕЛЯ** — третий, более
            глубокий случай того же класса: позиционность фасада от него не
            спасает, потому что имя принадлежит чужой сигнатуре. Имён ровно
            четыре, и они делятся по ДОРОГЕ отказа (сверено на реальном
            ``LoggerManager`` строками с диска, ревью 4.1):

            * ``message`` / ``msg`` — параметр ``_log_info``; ``TypeError``
              долетает сюда, ловится и считается;
            * ``scope`` / ``level`` — параметр ``LoggerCore.log``; исключение
              остаётся ВНУТРИ ``ObservableMixin._call_manager``, поэтому исход
              сверяется счётчиком (:func:`carrier_failures`), а не только
              ``except``. До этой сверки два имени из четырёх давали ``True``
              при нуле строк на диске.

            Любое из четырёх стоит ЗАПИСИ, но не линии: ``False``, счётчик
            ``events.refused`` и строка журнала один раз на процесс.

            ``module`` в этот список НЕ входит и раньше входил ошибочно: он не
            отказывает, а тихо уводил ШТАМП ИСТОЧНИКА (колонка, по которой ищет
            FTS). Теперь он часть конверта, и правило для него — общее правило
            конверта: прикладное значение **вытесняется**, ровно как у
            ``event``/``trace_id``/``spans``. Не «уезжает в extra под своим
            именем» — так было написано в первой редакции этого докстринга, и
            ревью 4.1 показало прогоном, что код делает другое:
            ``write_event(..., module="line_7")`` кладёт в запись
            ``module="robot_control"``, а ``"line_7"`` не сохраняется нигде.
            Второго ключа под вытесненное значение не заводится: конверт —
            белый список из четырёх имён, и мешок «а вот сюда мы складываем
            чужое» сделал бы его правилом с исключением.

            **Спаны — из ``unit["trace"]`` и только при включённом
            ``MULTIPROCESS_FRAME_TRACE``.** Второго механизма замера не
            заводится. Выключенный флаг НАЗВАН в самой записи (``spans: "off"``),
            а не выражен отсутствием поля: пустой список означал бы «мерили, не
            нашли», и отличить одно от другого читателю было бы нечем.
        """
        selector = getattr(self.services, EVENT_SELECTOR_ATTR, None)
        select = getattr(selector, "select", None)
        if callable(select):
            if not select(str(kind), decisive):
                return False
        elif not decisive:
            # Селектора нет (сшивки не было). Поведение НАЗВАНО и совпадает с
            # дефолтом настроенного селектора `first_n=0, every_mth=0`: фронты
            # пишутся, поток нет. Второго исполнения у «выключено» быть не должно
            # — иначе «поток молчит» означало бы разное на соседних процессах.
            return False

        trace_id = ""
        spans: Any = "off"
        if isinstance(unit, dict):
            trace_id = str(unit.get("trace_id") or "")
        # Импорт ленивый и ПОСЛЕ отбора: `plugins.base` не импортирует `generic`
        # на уровне модуля (C6 рычаг 2 — база плагина не знает про inspection-
        # домен), а прорежённая запись не обязана платить даже за поиск в
        # sys.modules.
        from ..generic import frame_trace

        if frame_trace.enabled():
            trace = unit.get("trace") if isinstance(unit, dict) else None
            spans = list(trace) if isinstance(trace, list) else []

        payload = {**fields, "event": str(kind), "trace_id": trace_id, "spans": spans}
        # Штамп источника — ТОЖЕ конверт, и попал сюда после ревью 4.1. Прежде
        # его защищал только `_stamped` (partial с `module=`), а keyword на
        # call-site партиал перебивает без ошибки: запись уезжала под чужим
        # именем, `write_event` возвращал True, счётчик молчал. Колонка `module`
        # индексируется FTS наравне с текстом — то есть подмена бьёт ровно по
        # той дороге, ради которой `trace_id` и кладётся в текст.
        # Пустой штамп → ключ СНИМАЕТСЯ, а не подставляется: тогда действует
        # умолчание носителя (`ObservableMixin` ставит имя менеджера), и
        # прикладное поле всё равно не может его увести.
        who = self.plugin_name or self.process_name or ""
        if who:
            payload["module"] = who
        else:
            payload.pop("module", None)

        # Исход у носителя сверяется ДВУМЯ способами, и это не два
        # предохранителя на одно место: у отказов две разные дороги наружу.
        # Исключение долетает сюда только если имя столкнулось с параметром
        # `_log_info` (`message`/`msg`); столкновение с параметром
        # `LoggerCore.log` (`scope`/`level`) остаётся ВНУТРИ `_call_manager`,
        # который его ловит и считает у себя. Счётчик снимается только на
        # записях, ПРОШЕДШИХ отбор, — они редки по построению.
        before = carrier_failures(self.services)
        try:
            self.log_info(f"event {kind}: {summary} trace={trace_id}", **payload)
        except Exception as exc:  # noqa: BLE001 — широкая запись не роняет линию
            note_event_refused(self.services, str(kind), f"носитель бросил {exc!r}")
            return False
        if before is not None and carrier_failures(self.services) != before:
            note_event_refused(
                self.services,
                str(kind),
                f"носитель посчитал отказ пары {CARRIER_FAILURE_KEY} у себя (исключение не долетает)",
            )
            return False
        return True

    # ------------------------------------------------------------------
    # Ф5 (задача 5.1) — дамп кольца записей по требованию
    # ------------------------------------------------------------------

    def flight_dump(self, reason: str = "", /, **fields: Any) -> bool:
        """Выгрузить кольцо последних записей процесса в файл — «что было вокруг».

        Отвечает на вопрос, на который не отвечает ни одна отдельная запись:
        «что происходило в процессе перед этим моментом». Кольцо — уже
        существующий ``MemoryChannel`` логгера (приёмник ``type: memory``);
        новое здесь только выгрузка и её триггер.

        **Это кольцо ЗАПИСЕЙ, а не пикселей.** В дампе строки плоскости логов
        этого процесса — включая широкие записи ``write_event``, — и ничего
        больше. Изображения кадров едут своими механизмами (copy_out, датасет).
        Соседние механизмы репозитория с тем же именем (``backend_ctl record_*``,
        ``telemetry_readmodel.export_history``) кольцуют ТЕЛЕМЕТРИЮ снаружи
        процесса — это другое (ADR-PM-037).

        **Звать ПОСЛЕ записей, которые обязаны в дамп попасть** (Р5.1-11).
        Порядок несущий и его никто не проверит за вызывающего: кольцо снимается
        в момент вызова, и широкая запись, сделанная СТРОКОЙ НИЖЕ, в этот дамп не
        попадёт. У инспектора это выглядит так: ``write_event(decisive=True)`` →
        ``write_document`` → ``flight_dump``.

        Args:
            reason: зачем сделан дамп (``"reject"``, ``"breaker"``). Едет и в имя
                файла (усечённая и очищенная под ФС), и в шапку целиком.
                **Позиционный** (``/``) — дословно как ``kind`` у
                ``write_document``/``write_event`` и по той же причине: прикладной
                ключ ``reason`` в нагрузке не имеет права ни увести конверт, ни
                уронить линию ``TypeError``'ом «got multiple values».
            **fields: шапка дампа — прежде всего ``trace_id`` единицы. Без него
                дамп и вердикт связывались бы догадкой по времени. Конверт
                кладётся ПОСЛЕ них: прикладное поле с именем ``kind``/``ts``/
                ``process``/``ring`` вытесняется, ровно как у соседних фасадов.

        Returns:
            ``True`` — файл записан. ``False`` — один из трёх названных отказов:
            рекордер выключен (ручка ``observability.flight.enabled``), кольцо
            недоступно (не объявлено / не ``type: memory`` / не смаршрутизировано),
            запись файла отказала. Ни один из них не тишина — у каждого свой
            счётчик в ``introspect.observability -> flight`` и голос один раз на
            процесс. Отказ дампа линию не роняет и решения не меняет (Р5.1-14):
            вердикт к этому моменту уже вынесен и уедет своей дорогой.
        """
        recorder = getattr(self.services, FLIGHT_RECORDER_ATTR, None)
        dump = getattr(recorder, "dump", None)
        if not callable(dump):
            # Рекордера нет — сшивки не было. Отвечаем ТЕМ ЖЕ отказом, что и
            # выключенный рекордер, и это Р5.1-5 в исполнении: у «выключено»
            # одно состояние с одним адресом. Второй текст здесь означал бы, что
            # оператор чинит наличие механизма вместо ручки.
            note_flight_disabled(self.services, str(reason), NO_RECORDER_KNOBS)
            return False
        return dump(
            self.services,
            str(reason),
            fields,
            self.plugin_name or self.process_name or "",
        )

    # ------------------------------------------------------------------
    # Этап 6, задача 1.1 — плоскость stats: бизнес-число тем же жестом, что лог
    # ------------------------------------------------------------------

    def _stats_call(self, method: str, name: str, value: Any, tags: dict | None) -> None:
        """Общая дорога всех четырёх метрик: штамп, порт, голос при его отсутствии.

        Одно место, а не четыре копии, ровно по той причине, по которой
        ``SubPluginContext.from_parent`` перечисляет дороги списком: три копии
        перечисления в этом файле уже расходились (Н-6, A2/Б-2).

        **Ф5, задача 5.2 (шаг 1): четвёрка фасада едет в ПОРТ, не в
        ``self.services.stats_manager`` напрямую.** ``StatsManager`` перестал
        быть входом данных (см. его докстринги, задача 5.3) — числа
        доставляются ему ЧЕРЕЗ порт (CRM-tap), и писать мимо порта означало бы
        второй писатель чисел с этого call-site, ровно то, что фаза хоронит.
        ``create=False``: числа не трогают хранилище УРОВНЕЙ (``PluginLevels``),
        которое резолвер заводит по этому флагу — заводить его ради метрики
        было бы посторонним побочным эффектом на чужом шве.

        Исключение наружу не выпускается ни при каком исходе: метрика — не то,
        ради чего останавливают линию. Но и не молчит — отказ считается и
        называется, потому что возврата у метрики нет (см. ``record_metric``).
        """
        port = self._observation_port(create=False)
        fn = getattr(port, method, None) if port is not None else None
        if not callable(fn):
            note_metric_without_plane(self.services, str(name), self.plugin_name or self.process_name or "")
            return
        if self._stats_tags is not None:
            # Явный тег call-site выигрывает у штампа — та же лесенка, что у
            # логов (``module=`` на call-site бьёт имя плагина, оно бьёт имя
            # процесса). Аллокации нет, пока штампа нет или тегов нет.
            tags = self._stats_tags if tags is None else {**self._stats_tags, **tags}
        try:
            fn(name, value, tags)
        except Exception as exc:  # noqa: BLE001 — сбой учёта не роняет линию
            self.log_error(f"[stats] метрика {name!r} не записана: {exc!r}")

    def record_metric(self, name: str, value: Any = 1, tags: dict | None = None) -> None:
        """Прибавить ``value`` к счётчику (counter) ``name``.

        Сигнатура — дословно ``StatsManager.record_metric``, включая дефолт
        ``value=1``. До задачи S-4 здесь стояло предупреждение: у
        ``ObservabilityHub.record_metric`` тот же метод означал **gauge**
        (перезапись), и эта дорога в частности всегда писала в РЕАЛЬНЫЙ
        ``StatsManager`` (``self.services.stats_manager``), а не в hub, —
        расхождение было конкретным и адресным. S-4 выровняла смысл у
        источника: теперь оба объекта, что могут оказаться за духк-тайп
        слотом ``"stats"`` (hub или менеджер), трактуют ``record_metric``
        одинаково — counter. Различать, кто за слотом, больше не нужно.

        Тег ``plugin`` подставляется автоматически по имени плагина; свой тег
        с тем же ключом выигрывает.
        """
        self._stats_call("record_metric", name, value, tags)

    def gauge(self, name: str, value: float, tags: dict | None = None) -> None:
        """Записать текущее значение — перезаписывает предыдущее в окне.

        Для «сколько СЕЙЧАС, чтобы показать в GUI» существует и другая дорога —
        уровни дерева состояния (``declare_metric``, self-publish по тику).
        Здесь — та же величина, но с агрегатом за окно и историей в сторе.
        """
        self._stats_call("gauge", name, value, tags)

    def record_timing(self, name: str, duration: float, tags: dict | None = None) -> None:
        """Записать длительность. **Единица — СЕКУНДЫ.**

        Дословно как ``StatsManager.record_timing``; миллисекунды здесь не
        упадут тестом — агрегат соберётся, но окажется в тысячу раз не там.
        Замер — ``time.perf_counter()`` разностью, как в спанах кадра.
        """
        self._stats_call("record_timing", name, duration, tags)

    def histogram(self, name: str, value: float, tags: dict | None = None) -> None:
        """Записать наблюдение в распределение значений."""
        self._stats_call("histogram", name, value, tags)

    # ------------------------------------------------------------------
    # Task 3.5 — уровни дерева состояния: «сколько СЕЙЧАС» под гейтом
    # ------------------------------------------------------------------

    def _metric_writer(self) -> str:
        """Под чьим ИМЕНЕМ едут уровни этого контекста: плагин, иначе процесс.

        Это сегмент ПУТИ (``state.plugins.<писатель>.<имя>``), а не претензия на
        имя метрики: с Ф1 «порт наблюдений» владения именем нет вовсе, и
        одинаковое имя у двух плагинов — два разных листа.

        ОДНО место на три дороги — :meth:`declare_metric`, :meth:`publish_metric`
        и :meth:`_retract_metrics`. Выражение писалось бы одинаково во всех трёх,
        и разойдись они хоть в одном звене — публикация уехала бы в одно
        поддерево, а снятие чистило другое, то есть уровень остановленного
        плагина остался бы жить. Ровно тот класс, на котором этот файл уже
        обжигался трижды (урок Н-6, перечисление дорог
        ``SubPluginContext.from_parent``).
        """
        return self.plugin_name or self.process_name or "plugin"

    def _observation_port(self, create: bool = False) -> Any:
        """Порт наблюдений процесса — дорога контекста к плоскости уровней (Ф3).

        ОДНО место на три дороги (объявление, публикация, снятие) по тому же
        доводу, что у :meth:`_metric_writer`: разойдись они, публикация уехала бы
        в один порт, а снятие чистило бы другой.

        **Ленивость обязана пережить Ф3, и это named-фолбэк, а не костыль.**
        ``observation_port`` отдаёт менеджер из слота ``observation``, а при его
        отсутствии — вид на то же самое хранилище, заведённое прежней
        ``get_or_create_plugin_levels``. Отказаться от второй ступени нельзя не
        из вежливости к старому коду: плагин публикует уровни из ``configure()``,
        то есть РАНЬШЕ ``start()`` — раньше, чем у процесса вообще созданы
        менеджеры. Требуй эта дорога зарегистрированного слота, и первые
        публикации каждого плагина исчезали бы молча.

        Импорт ЛЕНИВЫЙ — тем же жестом и по той же причине, что у соседей ниже:
        ``plugins.base`` импортируется РАНЬШЕ heartbeat'а, и тянуть его наверх
        значило бы менять порядок загрузки ради трёх строк.

        Args:
            create: завести хранилище значений, если его ещё нет. ``True``
                только у публикации: объявлению и снятию хранилище на пустом
                месте не нужно. Флаг доезжает до конца дороги — со ступени 1
                возвращается менеджер, и создаёт (или не создаёт) уже он, своим
                ``levels(create=…)``. До правки ревью 2026-08-25 он создавал
                безусловно, и ``create=False`` соблюдался ровно там, где слот не
                зарегистрирован.
        """
        from ...statistics_module.observation.observation_manager import observation_port

        return observation_port(self.services, create=create)

    def declare_metric(self, name: str) -> str:
        """Внести УРОВЕНЬ в каталог имён телеметрии (ADR-PM-038 + Ф1).

        Объявление — **каталожная запись, а не право на имя**: по каталогу
        publisher-гейт резолвит правила конфига и по нему GUI строит авто-строки
        уровней. Публиковать можно и БЕЗ объявления — незнакомое гейту имя едет
        под дефолтным правилом конфига (``TelemetryPublishConfig.resolve``
        тотальна), и никакого голоса «сначала объяви» больше нет. Звать рядом с
        кодом, который уровень СЧИТАЕТ, обычно в ``configure``.

        До Ф1 это было именно право: сборщик сверял объявленного владельца имени
        с публикатором и отбрасывал лист несовпавшего, а второе объявление того же
        имени было ``ValueError``. Арбитраж удалён целиком — уровень едет в
        поддерево своего писателя (``state.plugins.<писатель>.<имя>``), одинаковое
        имя у двух плагинов даёт два РАЗНЫХ листа, и спорить не о чем. Повторное
        объявление того же имени — идемпотентный no-op.

        **Не путать с** ``record_metric``/``gauge``: те пишут в плоскость stats —
        агрегат за окно и историю в сторе. Здесь дерево состояния: одно текущее
        число на имя, перезапись, никакой истории. Имена соседние, плоскости
        разные — см. ADR-PM-038.

        Args:
            name: имя уровня = ЛИСТ пути публикации
                (``processes.<процесс>.state.plugins.<писатель>.<name>``) и ключ,
                которым уровень адресует ``telemetry.publish.metrics`` — гейт
                матчит по имени листа, а не по полному пути.

        Returns:
            То же ``name`` — объявление пишется одной строкой рядом с полем.

        Raises:
            ValueError: имя содержит ТОЧКУ (см. ниже). Столкновение имён отказом
                больше не является.

        **Точка в имени — отказ, а не резидуал** (ревью Н3, 2026-08-17). Имя
        уровня склеивается в путь дерева, а ``TreeStore._merge_recursive``
        резолвит точку ДВУМЯ разными способами в зависимости от того, существует
        ли уже узел ``state``: на первом тике ключ ложится дословно
        (``state["a.b.c"]``), со второго — дифф отдаёт per-leaf дельту с путём
        ``…state.a.b.c``, и она резолвится как ВЛОЖЕННЫЙ путь. Две ветки
        встречаются в одном узле, и остаётся вечно-мёртвый лист-двойник,
        замороженный на значении первого тика, без единого голоса:

            state = {'a.b.c': 1.0, 'fps': 8.1, 'a': {'b': {'c': 2.0}}}
                     ^^^^^^^^^^^^ заморожен на первом тике

        До объединения трёх merge в один это был безобидный резидуал (уровни
        ехали прямо в ``processes.<p>.state``, и первая ветка не встречалась).
        Объединение сделало обе ветки достижимыми, то есть двойника добавила
        ИМЕННО эта задача — значит она его и закрывает. Отказ, а не голос:
        у точечного имени уровня нет правильного прочтения, а тихое
        переименование за автора было бы догадкой о его намерении.

        Плоскость stats точечные имена принимает и дальше (``capture.fps``) —
        там имя не становится путём дерева. Ограничение только здесь.
        """
        if "." in str(name):
            raise ValueError(
                f"имя уровня {name!r} содержит точку. Уровень становится путём дерева "
                f"(processes.<процесс>.state.plugins.<писатель>.<имя>), а точка в нём резолвится "
                f"по-разному "
                f"до и после появления узла state — остаётся мёртвый лист-двойник. "
                f"Возьми имя без точек (например {str(name).replace('.', '_')!r}); "
                f"точечные имена законны в плоскости stats (ctx.gauge/record_metric)"
            )

        # Ф3: объявление идёт ЧЕРЕЗ ПОРТ, как и публикация, — чтобы у контекста
        # не осталось дороги к плоскости уровней в обход слота. Действие обеих
        # веток дословно одно (каталог объявлений процессный и общий), поэтому
        # ``create=False``: заводить хранилище значений ради объявления ИМЕНИ
        # незачем, и сегодняшнее «объявил, но ещё ничего не опубликовал» не
        # должно менять наблюдаемое состояние процесса.
        writer = self._metric_writer()
        port = self._observation_port()
        if port is not None:
            return port.for_plugin(writer).declare(name)

        from ...observability_declarations import declare_metric as _declare

        return _declare(name, owner=writer)

    def publish_metric(self, name: str, value: Any) -> None:
        """Отдать ТЕКУЩЕЕ значение уровня ``name`` (ADR-PM-038).

        Значение кладётся в хранилище процесса В ПОДДЕРЕВО СВОЕГО ПИСАТЕЛЯ и
        уезжает в дерево СБОРЩИКОМ ТИКА
        (``processes.<процесс>.state.plugins.<писатель>.<name>``) — под
        publisher-гейтом и наравне с ``fps``/``latency_ms``; тот же сборщик отдаёт
        его опросом (``introspect.telemetry`` → ``levels``). Прямой
        ``state_proxy.merge`` из плагина делал ровно обратное: ехал мимо гейта,
        мимо тика и мимо опроса — на живом стенде 2026-08-16 гейт ``camera_0`` был
        закрыт на ``fps``, а путь ``state.fps`` всё равно получил 35 дельт за 41.1 с.

        **Чужого имени больше не бывает** (Ф1 «порт наблюдений»). Писатель —
        сегмент пути, а не претендент на имя: опубликуй два плагина ``fps``, и в
        дереве окажутся ``plugins.a.fps`` и ``plugins.b.fps``, каждый со своим
        числом. До Ф1 спор за один лист разрешала сверка с объявленным владельцем,
        а до неё — транспорт, у которого для этой роли нет ни семантики, ни
        голоса. Теперь спора нет по построению.

        Звать на СВОЁМ такте, а не на кадре: запись дешёвая (одна вставка в dict
        под локом), но публикует не она, а тик процесса — эмиссия чаще тика ничего
        не добавляет. У ``CapturePlugin`` это ветка пересчёта fps, раз в секунду.

        Отключаемость: у процесса без телеметрии значение просто никто не
        прочитает, а у сервисов, не принимающих атрибут (иммутабельный дубль),
        вызов — названный no-op со счётом и голосом. Исключения не бросает ни при
        какой конфигурации: уровень не имеет права ронять линию. Возврата нет —
        дословно как у четвёрки stats.

        Args:
            name: имя уровня — лист в поддереве этого писателя. Объявление
                (:meth:`declare_metric`) не обязательно: необъявленное имя едет
                под дефолтным правилом гейта, молча и легально. ТОЧКА —
                единственное исключение, и проверяются ОБА сегмента пути (имя
                уровня и имя плагина-писателя): лист не публикуется, голос один
                раз на пару (см. комментарий в теле и :meth:`declare_metric`).
            value: текущее значение. Числовое округляется сборщиком до 1 знака
                (та же цена, что у ``fps``); нечисловое едет как есть.
        """
        from ..heartbeat.telemetry import PLUGIN_LEVELS_ATTR

        # Точка в СЕГМЕНТЕ ПУТИ — отказ, и проверяются ОБА сегмента: имя листа и
        # имя писателя. Ф1 сделала достижимыми обе дыры сразу.
        #
        # Имя листа. Раньше guard'а на публикации не требовалось: необъявленное имя
        # до дерева не доходило, его отсеивал арбитр владения, а объявить точечное
        # имя не давал :meth:`declare_metric`. Ф1 сняла и арбитра, и требование
        # объявления — и точечное имя поехало.
        #
        # Имя писателя. До Ф1 оно вообще не было частью пути; теперь это сегмент
        # ``state.plugins.<писатель>.<имя>``, и плагин, названный ``my.plugin``,
        # получает ровно тот же двойник — этажом выше.
        #
        # Оба воспроизведены на дубле ``TreeStore._merge_recursive`` (тот же резолв,
        # что у настоящего стора): тик 1 кладёт точечный ключ ЛИТЕРАЛОМ (узла ещё
        # нет), тик 2 — вложенным путём, и остаётся вечно-мёртвый лист-двойник,
        # замороженный на значении первого тика::
        #
        #     {'plugins': {'my.plugin': {'fps': 1.0}, 'my': {'plugin': {'fps': 2.0}}}}
        #
        # НЕ исключение: уровень не имеет права ронять линию (контракт метода) —
        # в отличие от :meth:`declare_metric`, где то же самое отвергается громко.
        # Голос — один раз на то, О ЧЁМ он, а не на вызов: публикация идёт на такте
        # плагина, и жалоба на каждом такте — поток, к которому перестают
        # прислушиваться. Ключ дедупа поэтому НЕ пара (писатель, имя): для точки в
        # ИМЕНИ ПИСАТЕЛЯ текст жалобы имени листа не называет вовсе, и пара давала
        # N байт-в-байт одинаковых предупреждений на N метрик одного писателя
        # (измерено ревью Ф1: писатель ``a.b`` с пятью метриками → пять одинаковых
        # WARNING). Ключ — виновник: писатель, когда точка у него; пара, когда
        # точка в имени листа (там текст называет имя, и жалобы РАЗНЫЕ).
        writer = self._metric_writer()
        if "." in str(name) or "." in str(writer):
            key = (str(writer), str(name)) if "." in str(name) else (str(writer), None)
            warned = getattr(self, "_dotted_path_segments_warned", None)
            if warned is None:
                warned = set()
                self._dotted_path_segments_warned = warned
            if key not in warned:
                warned.add(key)
                culprit = "имя уровня" if "." in str(name) else "имя плагина-писателя"
                bad = name if "." in str(name) else writer
                self.log_warning(
                    f"[levels] {culprit} {bad!r} содержит точку — уровень не публикуется. "
                    f"Путь листа собирается как processes.<процесс>.state.plugins.<писатель>."
                    f"<имя>, и точка в сегменте резолвится по-разному до и после появления "
                    f"узла: остаётся мёртвый лист-двойник. Возьми {culprit} без точек "
                    f"(например {str(bad).replace('.', '_')!r}); точечные имена законны в "
                    f"плоскости stats (ctx.gauge/record_metric)"
                )
            return

        # Ф3: публикация идёт ЧЕРЕЗ ПОРТ — слот ``observation``, а при его
        # отсутствии прежняя ленивая ``get_or_create_plugin_levels`` (см.
        # :meth:`_observation_port`). Точка назначения от маршрута не зависит:
        # менеджер в слоте обслуживает ТО ЖЕ хранилище процесса, а не своё, —
        # иначе значения, отданные до появления менеджера, стали бы невидимы
        # после его регистрации.
        port = self._observation_port(create=True)
        if port is None:
            # Голос ОДИН раз: вызов идёт на такте плагина, и жалоба на каждом
            # такте — поток, к которому перестают прислушиваться (тот же довод,
            # что у ``note_metric_without_plane``). Своего счётчика этот случай
            # не заводит: у stats он нужен, потому что «плоскости нет» —
            # штатная конфигурация, а сервисы, не принимающие атрибут, штатной
            # конфигурацией не бывают (иммутабельный дубль в тесте).
            if not getattr(self, "_levels_without_store_warned", False):
                self._levels_without_store_warned = True
                self.log_warning(
                    f"[levels] уровень {name!r} отдавать некуда: сервисы процесса не принимают "
                    f"порт {PLUGIN_LEVELS_ATTR!r} — дальше по этому плагину молчим"
                )
            return
        port.for_plugin(writer).publish(name, value)

    def _retract_metrics(self) -> int:
        """Снять все уровни, опубликованные этим владельцем. Возвращает их число.

        Зовётся ФРЕЙМВОРКОМ на остановке плагина
        (:meth:`ProcessModulePlugin._do_shutdown`), а не плагином — Р3.5-14.
        Свойство «уровень мёртвого владельца исчезает в момент смерти» не имеет
        права держаться на памяти автора плагина: забудут ровно один раз и молча,
        а симптом («захват остановлен, а частота идёт») будут искать в камере.
        Прецедент — ``throttle.prune`` при ``state.delete``.

        Приватный, а не публичный: снимать чужие уровни плагину незачем, а свои
        за него снимает жизненный цикл. Публичная ручка здесь была бы приглашением
        завести второй, ручной способ делать то же самое.

        Хранилища нет (процесс без телеметрии, иммутабельный дубль сервисов) →
        ``0``: снимать нечего, и это не сбой. Голоса здесь нет намеренно —
        отсутствие хранилища уже названо один раз в :meth:`publish_metric`, а
        второй голос на том же факте звучал бы на КАЖДОЙ остановке плагина.
        """
        # Ф3: снятие идёт ЧЕРЕЗ ПОРТ, той же дорогой, что публикация и
        # объявление (:meth:`_observation_port`). Оставь эту дорогу на сыром
        # ``getattr`` — и она читала бы ДРУГОЙ источник, чем публикация, ровно в
        # том случае, ради которого порт и заводится: снятие чистило бы
        # хранилище, в которое никто не писал, а уровни остановленного плагина
        # продолжали бы ехать.
        #
        # ``create=False``: снимать в хранилище, которого нет, нечего, и заводить
        # его на остановке плагина было бы работой ради пустого узла.
        port = self._observation_port()
        if port is None:
            return 0
        return int(port.for_plugin(self._metric_writer()).retract())


# Заглушки плоскости stats для SubPluginContext без родителя (этап 6, 1.1).
#
# ЧЕТЫРЕ функции, а не одна общая. Первая редакция ставила одну
# (``_noop_stat(name, value=1, tags=None)``) с доводом «сигнатуры совпадают по
# форме» — и довод был неверен: у ``StatsManager`` третий параметр таймингов
# зовётся ``duration``, а у gauge/histogram значение ОБЯЗАТЕЛЬНО и дефолта не
# имеет. Плагин, звавший ``sub_ctx.record_timing("frame", duration=0.016)``
# ровно по эталонной сигнатуре, получал::
#
#     TypeError: _noop_stat() got an unexpected keyword argument 'duration'
#
# То есть заглушка, поставленная РАДИ безопасности вызова без родителя, сама
# роняла линию на именованном вызове. Найдено независимым тестером: тест автора
# звал заглушку позиционно и был зелён — тот самый случай, когда автор проверяет
# согласие с собственной моделью.
#
# ``*args``-заглушкой это не лечится: она принимает любое имя и тем самым
# перестаёт быть обязательством, которое сторожит оракул сигнатур (тот же довод,
# по которому у пятёрки ``log_*`` нет ``__getattr__``-проксирования).


def _noop_counter(name: str, value: Any = 1, tags: dict | None = None) -> None:
    """Счётчик в никуда. Молчит намеренно, в отличие от настоящего фасада: у
    вложенного контекста БЕЗ родителя нет и сервисов, то есть нет ни счётчика,
    ни логгера, куда сказать. Родитель пробрасывает свои дороги через
    ``SubPluginContext.from_parent`` — и тогда работает голос процесса."""


def _noop_gauge(name: str, value: float, tags: dict | None = None) -> None:
    """Текущее значение в никуда — сигнатура ``StatsManager.gauge`` дословно."""


def _noop_timing(name: str, duration: float, tags: dict | None = None) -> None:
    """Длительность в никуда — параметр зовётся ``duration``, как у менеджера."""


def _noop_histogram(name: str, value: float, tags: dict | None = None) -> None:
    """Наблюдение в никуда — сигнатура ``StatsManager.histogram`` дословно."""


def _noop_declare_metric(name: str) -> str:
    """Объявление в никуда для SubPluginContext без родителя (Task 3.5).

    Сигнатура — **дословно** ``PluginContext.declare_metric``, включая возврат
    того же имени: объявление пишется одной строкой рядом с полем
    (``self._level = ctx.declare_metric("...")``), и заглушка, вернувшая ``None``,
    превратила бы эту строку в тихую потерю имени.

    Своего реестра у вложенного контекста нет и быть не должно: каталог —
    ресурс процесса, а sub-плагин живёт внутри чужого. Родитель пробрасывает
    свою дорогу через :meth:`SubPluginContext.from_parent`.
    """
    return name


def _noop_publish_metric(name: str, value: Any) -> None:
    """Уровень в никуда для SubPluginContext без родителя (Task 3.5).

    Сигнатура — **дословно** ``PluginContext.publish_metric``: оба параметра
    обязательны, имени ``value`` заглушка не переименовывает. Урок четырёх
    заглушек 1.1: общая заглушка «по форме» роняла ``TypeError`` на именованном
    вызове по эталонной сигнатуре, то есть страховка от падения сама и была
    падением.

    Молчит намеренно, как ``_noop_counter``: у вложенного контекста без родителя
    нет ни хранилища, ни логгера, куда об этом сказать.
    """


def _noop_log(msg: str) -> None:
    """No-op fallback для логирования в SubPluginContext."""


def _noop_document(kind: str, summary: str = "", **fields: Any) -> bool:
    """Fallback плоскости документов для SubPluginContext без родителя (Ф8.7).

    Возвращает ``False`` — ровно то же, что вернул бы настоящий контекст на
    процессе без плоскости. Форма ответа одна на оба случая намеренно: клиент
    и так обязан различать «записано» и «нет», а вторая форма отказа
    заставила бы его знать, в каком контексте он живёт.

    Вложенный контекст своей плоскости не имеет и иметь не должен: сток —
    ресурс процесса, а sub-плагин живёт внутри чужого. Родитель, у которого
    вложенный плагин выносит вердикт, пробрасывает свою дорогу явно::

        SubPluginContext(..., write_document=self._ctx.write_document)
    """
    return False


def _noop_event(
    kind: str,
    summary: str = "",
    /,
    *,
    unit: Any = None,
    decisive: bool = False,
    **fields: Any,
) -> bool:
    """Широкая запись в никуда для SubPluginContext без родителя (Ф4, 4.1).

    Сигнатура — **дословно** ``PluginContext.write_event``, включая косую черту
    позиционных и оба именованных параметра. Урок четырёх заглушек 1.1 стоил
    ровно этого: общая заглушка «по форме» роняла ``TypeError`` на именованном
    вызове по эталонной сигнатуре, то есть страховка от падения сама и была
    падением. ``*args``-заглушкой это не лечится: она принимает любое имя и
    перестаёт быть обязательством, которое сторожит оракул сигнатур.

    Возвращает ``False`` — то же, что вернул бы настоящий контекст, у которого
    запись не поехала. Своего отбора у вложенного контекста нет и быть не должно:
    селектор — ресурс процесса, а sub-плагин живёт внутри чужого. Родитель
    пробрасывает свою дорогу через :meth:`SubPluginContext.from_parent`.
    """
    return False


def _noop_flight(reason: str = "", /, **fields: Any) -> bool:
    """Дамп в никуда для SubPluginContext без родителя (Ф5, 5.1).

    Сигнатура — **дословно** ``PluginContext.flight_dump``, включая косую черту
    позиционных и дефолт ``reason``. Урок четырёх заглушек 1.1 и урок 4.1-И8
    вместе: общая заглушка «по форме» роняла ``TypeError`` на именованном вызове
    по эталонной сигнатуре, а позиционно-only параметр, объявленный обычным,
    не падает — он молча уезжает в ``**fields``, и причина дампа становится его
    же полем. ``*args``-заглушкой это не лечится: она принимает любое имя и
    перестаёт быть обязательством, которое сторожит оракул сигнатур.

    Возвращает ``False`` — то же, что вернул бы настоящий контекст при
    выключённом рекордере. Своего рекордера у вложенного контекста нет и быть не
    должно: кольцо и каталог — ресурсы процесса, а sub-плагин живёт внутри
    чужого. Родитель пробрасывает свою дорогу через
    :meth:`SubPluginContext.from_parent`.
    """
    return False


def _standalone_health() -> Any:
    """Fallback-reporter для SubPluginContext без родителя (волна C, Ф2 Task 2.5).

    Sub-плагины зовут ``ctx.health.report_error(...)`` наравне с обычными —
    без поля health это AttributeError на error-пути. Дефолт — автономный
    log-only HealthState (не публикуется, счётчик локальный); родительский
    плагин пробрасывает свой reporter через ``SubPluginContext(health=...)``.
    """
    from ..health import HealthReporter, HealthState

    return HealthReporter(HealthState(log_only=True), source="sub_plugin")


@dataclass
class SubPluginContext:
    """Облегчённый контекст для вложенных плагинов (chain_executor, worker_pool).

    Совместим с PluginContext по duck-typing — плагины используют
    ctx.config, всю пятёрку ctx.log_*, ctx.registers, ctx.command_manager,
    ctx.health, ctx.write_document, ctx.write_event, ctx.flight_dump, четвёрку
    stats (ctx.record_metric / gauge / record_timing / histogram) и пару уровней
    (ctx.declare_metric / ctx.publish_metric).

    Заменяет unittest.mock.MagicMock в production-коде.

    Для логирования через LoggerManager фреймворка — передайте log_info/log_error
    из родительского PluginContext::

        sub_ctx = SubPluginContext(
            config=sub_config,
            log_info=self._ctx.log_info,
            log_error=self._ctx.log_error,
        )
    """

    process_name: str = "sub_plugin"
    config: dict[str, Any] = field(default_factory=dict)
    registers: Any = None
    # A2 (Б-2), повторно — задача 4.2 (Н-6): ВСЯ пятёрка, а не log_info/log_error.
    # Тот же дефект, что уже чинили в `PluginContext`, жил здесь ещё год: вложенный
    # плагин, звавший `ctx.log_warning` в ветке штатной деградации, получал
    # `AttributeError` и падал — при том что протокол метод объявлял, а родительский
    # контекст его имел. Дефект, починенный на одной развилке из двух, воскресает на
    # соседней; список судится контракт-тестом, читающим протокол, а не рукописной копией.
    log_debug: Callable[[str], None] = _noop_log
    log_info: Callable[[str], None] = _noop_log
    log_warning: Callable[[str], None] = _noop_log
    log_error: Callable[[str], None] = _noop_log
    log_critical: Callable[[str], None] = _noop_log
    command_manager: Any = None
    worker_manager: Any = None
    router_manager: Any = None
    memory_manager: Any = None
    # StateProxy (Phase 8) — для публикации состояния через реактивное дерево
    # None по умолчанию для обратной совместимости
    state_proxy: Any = None
    # Health-фасад (Ф2): дефолт — автономный log-only reporter; родитель
    # пробрасывает свой ctx.health, чтобы ошибки sub-плагинов кормили процесс.
    health: Any = field(default_factory=_standalone_health)
    # Плоскость документов (Ф8.7): дефолт — отказ, потому что своего стока у
    # вложенного контекста нет. Родитель пробрасывает свой ctx.write_document.
    write_document: Callable[..., bool] = _noop_document
    # Широкая запись (Ф4, 4.1): СРАЗУ, а не «потом, когда понадобится» — тот же
    # урок Н-6. Вложенный плагин, вынесший решение по своей единице, звал бы
    # ctx.write_event и получал AttributeError, как когда-то ctx.log_warning.
    write_event: Callable[..., bool] = _noop_event
    # Дамп кольца (Ф5, 5.1): СРАЗУ, а не «потом, когда понадобится» — тот же
    # урок Н-6, что у соседей выше. Вложенный плагин, поймавший аварию своей
    # единицы, звал бы ctx.flight_dump и получал AttributeError.
    flight_dump: Callable[..., bool] = _noop_flight
    # Плоскость stats (этап 6, 1.1): ВСЯ четвёрка сразу, а не record_metric.
    # Урок Н-6 дословно: дефект, починенный на одной развилке из двух,
    # воскресает на соседней — вложенный плагин, звавший ctx.histogram, получил
    # бы AttributeError ровно так же, как когда-то ctx.log_warning.
    # Заглушка у каждой дороги СВОЯ: сигнатуры дословны StatsManager, включая
    # имя `duration` у таймингов и обязательное значение у gauge/histogram.
    record_metric: Callable[..., None] = _noop_counter
    gauge: Callable[..., None] = _noop_gauge
    record_timing: Callable[..., None] = _noop_timing
    histogram: Callable[..., None] = _noop_histogram
    # Уровни дерева состояния (Task 3.5): ОБЕ дороги сразу и в этой же правке —
    # тот же урок Н-6, что у соседей. Объявление без отдачи (или наоборот) дало бы
    # вложенному плагину половину механизма: он объявил бы имя и получил
    # AttributeError на публикации — ровно как когда-то на ctx.log_warning.
    declare_metric: Callable[..., str] = _noop_declare_metric
    publish_metric: Callable[..., None] = _noop_publish_metric

    @classmethod
    def from_parent(cls, parent: Any, **overrides: Any) -> "SubPluginContext":
        """Собрать вложенный контекст, пробросив ВСЕ дороги родителя.

        Задача 4.2 (Н-6). Пятёрка ``log_*`` у вложенного контекста появилась, но
        родители на трёх живых вызовах пробрасывали два метода из пяти — и
        ``log_warning`` вложенного плагина стал бы уходить в no-op вместо
        родительского логгера. Это тот же дефект, только тише: было падение с
        ``AttributeError``, стала бы бесшумная потеря записи, которую никто не ищет.

        Проброс списком, а не перечислением на каждом вызове: список дорог растёт
        (пятёрка, ``health``, ``write_document``, четвёрка stats — этап 6, 1.1,
        ``write_event`` — Ф4, 4.1, ``flight_dump`` — Ф5, 5.1,
        ``declare_metric``/``publish_metric`` — Task 3.5),
        и каждый новый обязан появиться в ОДНОМ месте. Три копии этого перечисления
        уже расходились — так и родился Н-6.

        Args:
            parent: родительский :class:`PluginContext` (или любой контекст с теми же
                дорогами — проверяется наличием, а не типом).
            **overrides: что задать явно, прежде всего ``config`` вложенного плагина.
        """
        forwarded: dict[str, Any] = {}
        for road in (
            "log_debug",
            "log_info",
            "log_warning",
            "log_error",
            "log_critical",
            "health",
            "write_document",
            # Ф4, 4.1 — широкая запись добавлена ЗДЕСЬ же, в единственном
            # перечислении дорог.
            "write_event",
            # Ф5, 5.1 — дамп кольца, там же и по тому же правилу.
            "flight_dump",
            # Этап 6, 1.1 — четвёрка stats добавлена ЗДЕСЬ, в единственном
            # перечислении дорог, ровно как обещал докстринг выше.
            "record_metric",
            "gauge",
            "record_timing",
            "histogram",
            # Task 3.5 — уровни дерева состояния, ЗДЕСЬ же и по тому же правилу:
            # список дорог живёт в ОДНОМ месте (Н-6).
            "declare_metric",
            "publish_metric",
        ):
            value = getattr(parent, road, None)
            if value is not None:
                forwarded[road] = value
        for road in (
            "registers",
            "command_manager",
            "worker_manager",
            "router_manager",
            "memory_manager",
            "state_proxy",
        ):
            value = getattr(parent, road, None)
            if value is not None:
                forwarded[road] = value
        forwarded.update(overrides)
        return cls(**forwarded)


class ProcessModulePlugin(ABC):
    """Единица поведения, подключаемая к GenericProcess.

    Единый интерфейс для всех плагинов:
    - source (webcam, hikvision, file_source, simulator)
    - processing (color_mask, blur, threshold, edge_detect)
    - output (renderer, database, robot)

    State machine (от GStreamer):
        IDLE → READY → RUNNING → STOPPED
               ↑          ↓
               ←── PAUSED ←

    GenericProcess управляет state transitions:
    - _init_application_threads(): IDLE → READY → RUNNING
    - pause():                     RUNNING → PAUSED
    - resume():                    PAUSED → RUNNING
    - shutdown():                  * → STOPPED

    Контракт портов (от GStreamer caps + UE pins):
        inputs  — что плагин ожидает на входе
        outputs — что плагин отдаёт на выходе

    Команды — {имя_команды: имя_метода}
        Автоматически регистрируются в CommandManager процесса.

    Статический манифест (Ф4 Task 4.4, см. ``plugins/manifest.py``):
        VERSION      — semver плагина (не версия контракта). Дефолт "0.0.0".
        API_VERSION  — semver контракта плагин↔фреймворк. Дефолт — текущий
                        ``PLUGIN_API_VERSION``. Boot mismatch по major → WARNING
                        (не отказ, см. ``PluginOrchestrator.boot()``).
        REQUIRES     — декларация зависимостей, проверяется на boot ДО
                        configure(): "manager:<атрибут ctx>" (напр.
                        "manager:worker_manager"), "service:<имя>" (менеджер на
                        ctx.services, напр. "service:sql_manager"), "shm".
                        Недостающая зависимость → громкая ошибка с именем
                        плагина вместо позднего немого AttributeError.
    """

    name: str = ""
    # Канон — plugins.manifest.PluginCategory (source/processing/render/io/sink/
    # hub/control/filter/calibration/runtime/utility). Легаси-строки (rendering/
    # output и любые другие) канонизируются PluginRegistry.register() через
    # CATEGORY_LEGACY_ALIASES; неканоничное значение — громкий WARNING, не отказ.
    category: str = ""

    # --- Манифест плагина (Ф4 Task 4.4) — статически читаемые метаданные ---
    VERSION: ClassVar[str] = "0.0.0"
    API_VERSION: ClassVar[str] = PLUGIN_API_VERSION
    REQUIRES: ClassVar[tuple[str, ...]] = ()

    # Контракт портов — переопределяется в подклассах
    inputs: list = []  # list[Port]
    outputs: list = []  # list[Port]

    # Команды — {command_name: method_name}
    # Автоматически регистрируются в CommandManager при configure
    commands: dict[str, str] = {}

    # Thread-safety контракт (Q8):
    # False (default) — sequential, safe by default.
    # True — разрешает параллельный вызов process() (для stateless плагинов).
    thread_safe: ClassVar[bool] = False

    # C6 рычаг 2: frame-trace обёртка process/produce больше НЕ ставится в
    # __init_subclass__ (база плагина не импортирует generic.frame_trace на этапе
    # объявления класса — снята связь фундамент-плагина → inspection-домен). Установку
    # делает PluginOrchestrator.boot() через frame_trace.install_tracing() на бутe.

    def __init__(self) -> None:
        self.state: PluginState = PluginState.IDLE
        self.metrics: PluginMetrics | None = None
        # Имя процесса-узла для frame-trace (ставит PluginOrchestrator.boot).
        self._trace_node: str = ""
        # Bypass-флаг: если False — PluginRunner НЕ вызывает process(), кадр идёт
        # насквозь без обработки (live-тумблер в инспекторе ноды). Источники (produce)
        # bypass не поддерживают (нечего пропускать). См. PluginRunner.call_process.
        self.enabled: bool = True

    # --- Data pipeline контракт (Phase 5) ---

    @property
    def is_source(self) -> bool:
        """True если плагин — источник данных (category == 'source')."""
        return self.category == "source"

    @classmethod
    def register_schema(cls) -> list:
        """Register-классы плагина (list[type[SchemaBase]]).

        Источники (по приоритету):
          1. ``config_class().register_bindings`` (если config_class переопределён);
          2. **fallback** ``register_class`` на самом плагине — канонический и самый
             частый способ объявить регистр. Благодаря этому fallback любой плагин с
             ``register_class = X`` автоматически получает RegistersManager и приёмник
             ``register_update`` (live field-write из GUI) БЕЗ boilerplate-override
             ``config_class``. Без него (была дыра) плагины вида blob_detector/line_filter
             молча теряли live-редактирование («No handler for key 'register_update'»).
          3. Иначе — пустой список (graceful degradation).

        Returns:
            Список SchemaBase-классов (не инстансов).
        """
        config_cls = cls.config_class()
        if config_cls is not None and hasattr(config_cls, "register_bindings"):
            bindings = list(config_cls.register_bindings)
            if bindings:
                return bindings
        rc = getattr(cls, "register_class", None)
        if rc is not None:
            return [rc]
        return []

    @classmethod
    def config_class(cls) -> type | None:
        """PluginConfig-класс этого плагина (lazy discovery через PluginRegistry).

        Override если автоматический discovery не работает.
        """
        return None

    def _init_register(self, ctx: PluginContext, register_cls: type | None = None) -> Any:
        """Инициализировать register: managed (GUI) → локальный fallback → YAML overrides.

        Порядок:
          1. Если ctx.registers есть — берёт managed register (GUI видит и меняет)
          2. Если нет — создаёт локальный экземпляр register_cls (defaults)
          3. Применяет YAML overrides из ctx.config (inline-значения из topology)

        Args:
            ctx: PluginContext с config и registers.
            register_cls: Класс регистра. Если None — берёт из self.register_class.

        Returns:
            Инстанс регистра (managed или локальный).

        Raises:
            ValueError: если register_cls не задан ни явно, ни через self.register_class.

        Пример использования::

            class MyPlugin(ProcessModulePlugin):
                register_class = MyRegisters

                def configure(self, ctx):
                    self._ctx = ctx
                    self._reg = self._init_register(ctx)
        """
        cls = register_cls or getattr(self, "register_class", None)
        if cls is None:
            raise ValueError(
                f"Plugin '{self.name}': register_class не задан. "
                f"Укажите register_class на классе или передайте register_cls аргументом."
            )

        # 1. Managed register (GUI видит)
        reg = None
        if ctx.registers is not None:
            managed = ctx.registers.get_register(self.name)
            # Проверяем что managed — реальный SchemaBase, а не mock
            if managed is not None and hasattr(type(managed), "model_fields"):
                reg = managed

        # 2. Fallback: локальный экземпляр
        if reg is None:
            reg = cls()

        # 3. YAML overrides из config (ctx.config всегда плоский — нормализация
        #    формата pdef живёт в PluginOrchestrator._extract_plugin_config).
        for field_name in type(reg).model_fields:
            if field_name in ctx.config:
                setattr(reg, field_name, ctx.config[field_name])

        return reg

    def process(self, items: list[dict]) -> list[dict]:
        """Обработка items. Override в processing/output-плагинах.

        Default: pass-through (return items).
        items — список {"frame": ndarray, ...metadata}.
        Чистая обработка: без IPC, без SHM, без PluginContext.

        Покрывает все семантики:
          1:1   resize, grayscale, negative, ...
          1:N   region_split
          N:1   stitcher
          N:0   фильтрация (return [])
          batch frame_counter, FPS log
        """
        return items

    def produce(self) -> list[dict]:
        """Генерация items. Override в source-плагинах.

        Default: raise NotImplementedError.
        """
        raise NotImplementedError(f"Plugin '{self.name}' does not implement produce()")

    @abstractmethod
    def configure(self, ctx: PluginContext) -> None:
        """Объявить ресурсы: SHM, middleware, обработчики сообщений.

        Transition: IDLE → READY.
        Команды из self.commands регистрируются автоматически (GenericProcess).
        """

    def start(self, ctx: PluginContext) -> None:
        """Запуск после configure всех плагинов. Создание воркеров.

        Transition: READY → RUNNING.
        Default: no-op. Override при необходимости (воркеры, фоновые задачи).
        """

    def pause(self, ctx: PluginContext) -> None:
        """Приостановка. Default: no-op.

        Transition: RUNNING → PAUSED.
        """

    def resume(self, ctx: PluginContext) -> None:
        """Возобновление. Default: no-op.

        Transition: PAUSED → RUNNING.
        """

    def configure_managers(self, ctx: PluginContext) -> None:
        """Ранняя инициализация менеджеров ДО основного lifecycle. Default: no-op.

        Вызывается из GenericProcess._init_custom_managers() — до configure().
        Используется плагинами, которым нужно создать framework-менеджеры
        (SQLManager, кастомный RouterManager и т.д.) до того, как другие
        плагины начнут configure().

        Не путать с configure() — тот для SHM, middleware, воркеров.
        """

    def shutdown(self, ctx: PluginContext) -> None:
        """Очистка ресурсов. Default: no-op.

        Transition: * → STOPPED.
        """

    # --- State transitions (вызываются GenericProcess) ---

    def _do_configure(self, ctx: PluginContext) -> None:
        """IDLE → READY: configure + авторегистрация команд + метрики."""
        if self.state != PluginState.IDLE:
            ctx.log_error(f"Plugin '{self.name}': configure() в состоянии {self.state}, ожидается IDLE")
            return

        # Инициализация метрик
        from .metrics import PluginMetrics

        self.metrics = PluginMetrics(self.name)

        with self.metrics.measure("configure"):
            self.configure(ctx)
            self._auto_register_commands(ctx)

        self.state = PluginState.READY

    def _do_start(self, ctx: PluginContext) -> None:
        """READY → RUNNING."""
        if self.state != PluginState.READY:
            ctx.log_error(f"Plugin '{self.name}': start() в состоянии {self.state}, ожидается READY")
            return

        if self.metrics:
            with self.metrics.measure("start"):
                self.start(ctx)
        else:
            self.start(ctx)

        self.state = PluginState.RUNNING

    def _do_pause(self, ctx: PluginContext) -> None:
        """RUNNING → PAUSED."""
        if self.state != PluginState.RUNNING:
            return
        self.pause(ctx)
        self.state = PluginState.PAUSED

    def _do_resume(self, ctx: PluginContext) -> None:
        """PAUSED → RUNNING."""
        if self.state != PluginState.PAUSED:
            return
        self.resume(ctx)
        self.state = PluginState.RUNNING

    def _do_shutdown(self, ctx: PluginContext) -> None:
        """* → STOPPED.

        После пользовательского ``shutdown`` снимает уровни, которые этот плагин
        публиковал (Р3.5-14): свежесть держится жизненным циклом, а не штампом
        времени на каждом листе. ПОСЛЕ, а не до, — плагин вправе отдать последнее
        значение в собственном ``shutdown`` (``CapturePlugin`` так и делает,
        обнуляя частоту на остановке захвата), и снятие до него оставило бы это
        значение висеть навсегда.

        Сосед по процессу не задет: снимается ровно то, что опубликовано ЭТИМ
        владельцем (:meth:`PluginContext._retract_metrics`).

        **Снятие в ``finally``, и это не стилистика (ревью Н2, 2026-08-17).**
        Первая редакция ставила снятие ПОСЛЕ незавёрнутого ``self.shutdown(ctx)``.
        Плагин, чей ``shutdown`` бросил (``RuntimeError('камера не отпустила
        устройство')``), оставлял уровни в хранилище НАВСЕГДА: ``STOPPED`` не
        наступал, оркестратор бросок логировал и шёл дальше
        (``generic/plugin_orchestrator.py``), а тики продолжали публиковать
        мёртвое значение. То есть симптом «камера остановлена, а частота идёт»
        воскресал ровно на отказной дороге — там, где диагностика нужнее всего.
        Воспроизведено: три тика с ``{'state': {'boom_level': 7.7}}`` после
        броска.
        """
        if self.state == PluginState.STOPPED:
            return

        try:
            if self.metrics:
                with self.metrics.measure("shutdown"):
                    self.shutdown(ctx)
            else:
                self.shutdown(ctx)
        finally:
            # Снятие уровней не имеет права ни помешать остановке, ни
            # проглотить бросок пользовательского shutdown: исключение уходит
            # наружу как раньше (STOPPED не наступит), но уровни сняты. Сбой
            # самого снятия называется, а не глотается.
            try:
                ctx._retract_metrics()
            except Exception as exc:  # noqa: BLE001 — телеметрия не блокирует остановку
                ctx.log_warning(f"Plugin '{self.name}': уровни не сняты при остановке: {exc!r}")

        self.state = PluginState.STOPPED

    def _auto_register_commands(self, ctx: PluginContext) -> None:
        """Автоматически зарегистрировать команды плагина в CommandManager.

        commands = {"set_hsv_range": "set_range"} → ищет метод self.set_range,
        регистрирует как команду "set_hsv_range" в CommandManager.

        Плюс: если плагин имеет register_class и не определил свою команду
        "set_config", автоматически регистрируется generic cmd_set_config —
        bridge.on_field_set → set_config → setattr(self._reg, field, value).
        """
        if not ctx.command_manager:
            return

        for cmd_name, method_name in self.commands.items():
            method = getattr(self, method_name, None)
            if method is None:
                ctx.log_error(f"Plugin '{self.name}': команда '{cmd_name}' → метод '{method_name}' не найден")
                continue

            ctx.command_manager.register_command(cmd_name, method)

        # Generic set_config — поднимает boilerplate из плагинов с register_class.
        # Регистрируется только если у плагина есть register_class и команда
        # set_config не была переопределена явно в self.commands.
        has_register = getattr(self, "register_class", None) is not None
        explicit_set_config = "set_config" in self.commands
        if has_register and not explicit_set_config:
            # set_config — ПРОЦЕССНАЯ команда: CommandManager один на процесс, а
            # плагинов с register_class — несколько. Достаточно зарегистрировать
            # ОДИН раз (первым плагином); остальные пропускают, иначе dispatcher
            # шумит 'set_config already exists' на каждый следующий плагин.
            # Живые правки полей адресуются по регистрам (register_name == plugin_name),
            # а не через эту команду, поэтому единственного handler'а достаточно.
            get_info = getattr(ctx.command_manager, "get_command_info", None)
            already = bool(get_info("set_config")) if callable(get_info) else False
            if not already:
                ctx.command_manager.register_command("set_config", self.cmd_set_config)

    def cmd_set_config(self, data: dict) -> dict:
        """Generic handler для bridge.on_field_set → applied dict из GUI.

        Применяет {field: value} к self._reg через setattr. Поля без
        соответствующего атрибута игнорируются (graceful skip с логом).

        Плагин может переопределить, добавив "set_config" в self.commands —
        тогда этот generic не регистрируется (см. _auto_register_commands).

        Returns:
            {"status": "ok", "applied": {...}, "skipped": [...]}
        """
        reg = getattr(self, "_reg", None)
        if reg is None:
            return {"status": "error", "error": "_reg not initialized"}

        applied: dict[str, Any] = {}
        skipped: list[str] = []
        for field_name, value in data.items():
            if hasattr(reg, field_name):
                setattr(reg, field_name, value)
                applied[field_name] = value
            else:
                skipped.append(field_name)

        ctx = getattr(self, "_ctx", None)
        if ctx is not None and hasattr(ctx, "log_info"):
            ctx.log_info(f"[{self.name} set_config] applied={applied}" + (f" skipped={skipped}" if skipped else ""))

        result: dict[str, Any] = {"status": "ok", "applied": applied}
        if skipped:
            result["skipped"] = skipped
        return result
