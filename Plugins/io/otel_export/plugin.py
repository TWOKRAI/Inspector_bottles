# -*- coding: utf-8 -*-
"""`OtelExportPlugin` — хост экспортёра OTLP: приём хвоста, отметка, отправка (Task 2.1/2.2/2.4).

Side-effect плагин (нет `inputs`/`outputs`) в обычном `GenericProcessApp`, по
форме — как `telemetry_sink`. Что он делает: объявляет брокеру намерение
подписаться на хвост наблюдаемости ВСЕХ процессов, принимает пачки записей,
ставит им отметку приёма, отбрасывает числовую плоскость, приводит записи к
модели OTel, считает восемь величин в двух плоскостях и отдаёт их **очереди
дренажа**, чей фоновый поток отправляет пачки в приёмник OTLP.

**Отправка АСИНХРОННА с Task 2.4, и очередь взята готовая.** Между хендлером и
сетью стоит `BatchDrainWorker`
(`channel_routing_module/observability/batch_drain.py`) — тот же класс, которым
плоскость истории развязала эмитента и SQLite. Своей очереди здесь нет и быть не
должно: два буфера на одном пути дают два разных ответа на вопрос «сколько
записей ждёт», и расходятся они молча. Роли: приём кладёт запись
(`worker.write`), сток пачки — :meth:`_export_batch` поверх `OtlpHttpExporter`,
вытеснение — `drop_oldest` со счётчиком `dropped_overflow`, дедлайн дожатия —
`worker.flush(timeout)`.

**Останов дожимает ОГРАНИЧЕННО, и ограничивает не SDK.** Task 2.2 не дожимала
вовсе (вердикт CTO: синхронная отправка жила 23-42 с против бюджета останова
5 с и убивала процесс внутри retry-цикла SDK). Task 2.4 дожатие возвращает,
потому что дедлайн наконец есть чем держать: `BatchDrainWorker.flush(timeout)`
честен и против ЗАВИСШЕГО стока — работу делает поток дренажа, а вызывающий
только ждёт прогресса до дедлайна. Число берётся из конфига
(`flush_timeout_ms`, дефолт 3 с), а не из литерала в механизме, и исход
произносится числами: `otel flush: N дожато, M потеряно`.

**Что здесь может сломаться, учитывая, как оно устроено.**

1. *Хендлер живёт на ПРИЁМНОМ потоке процесса.* Пока он работает, почта
   процесса не разбирается. Отсюда запрет внутри него: ни сети, ни ожидания на
   локах, ни `sleep`. Цена приёма — постановка в кольцевой буфер, и ровно это
   свойство проверяет приёмочный тест Task 2.4 зависшим стоком. Единственный лок
   в хендлере — вокруг инкремента счётчиков,
   он неконкурентен по построению (поток один) и нужен ровно на случай, когда
   построение окажется неверным. Что поток действительно один — не проза, а
   показание: :meth:`_cmd_status` отдаёт `handler_threads`, и появление ВТОРОГО
   идентификатора — голос окном (Р-11, находка Н-6 ревью Ф1). Второй поток портит
   не счётчик, а ПУЛ `Resource`, который потокобезопасным быть не обещал.
2. *Отсутствие SDK и пустой `endpoint` не имеют права уронить процесс* (Р-14).
   `PluginOrchestrator.boot()` бросок из `configure()` ловит, но платой было бы
   одно `log_error` и плагин, молча оставшийся в `IDLE`, — причина уехала бы в
   журнал строкой и нигде больше. Поэтому оба отказа ловятся здесь: состояние
   `error`, причина текстом, и она читается командой `otel_export.status`.
3. *Синхронный `RouterManager.request()` из `start()` бесполезен.* Приёмного
   цикла ещё нет (шаг 6 против шага 7 `ProcessModule.initialize`), и запрос
   вернул бы `{"error": "timeout", "reason": "no_receive_pump"}` через 0.5 с. Та
   же дорога стоила `telemetry_sink` 10.03 с простоя старта. Намерение уходит
   через :meth:`RouterManager.request_async` (Р-16), а подтверждение приезжает
   колбэком — уже на приёмном потоке, то есть колбэк обязан быть коротким и не
   имеет права звать блокирующий `request()`.
4. *Колбэк брокера может приехать ПОСЛЕ останова.* Слот `request_async` живёт до
   ответа или таймаута, а `shutdown()` его не отменяет. Поэтому у колбэка первым
   делом стоит проверка `_stopped`: повторная попытка подписки из мёртвого
   плагина восстановила бы хвост, которого никто уже не читает.
5. *Счётчики в ДВУХ плоскостях, и это не дубль* (Р-7). `record_metric` берёт
   точечное имя и адресует `history_query(metric="otel_export.received")`;
   `declare_metric`/`publish_metric` — это УРОВЕНЬ дерева состояния, точку в
   имени он отвергает `ValueError` (ADR-PM-038), и только он виден в
   `introspect.telemetry -> levels`. Дословный перенос строки плана уронил бы
   плагин на старте.
6. *У счётчика `dropped_overflow` ровно одно обещание — «не поместилось».*
   Собственный `BatchDrainWorker.counters()` складывает под именем вызывающего
   ДВА факта — вытеснение переполнением и отказ записи после `close()` (так
   написано в его докстринге дословно). Числу это безразлично, читателю нет:
   запись, пришедшая после останова, инфлировала бы «переполнение», которого не
   было. Поэтому плоскость счётчиков плагина растёт от `get_info()["dropped"]`
   (это ТОЛЬКО вытеснения канала), а «после закрытия» видно отдельным ключом в
   `otel_export.status -> queue`. Ровно этот класс путаницы стоил соседней
   полосе числа «подавлено», за которым не стояло ни одного вызова.
"""

from __future__ import annotations

import threading
import time
from collections.abc import Mapping
from dataclasses import replace
from types import SimpleNamespace
from typing import Any

from pydantic import ValidationError

from multiprocess_framework.modules.channel_routing_module.observability.batch_drain import (
    BatchDrainWorker,
)
from multiprocess_framework.modules.channel_routing_module.observability.record_display import (
    stamp_observed,
)
from multiprocess_framework.modules.logger_module.core.windowed_voice import log_windowed
from multiprocess_framework.modules.message_module.builders.command_envelopes import (
    build_command_message,
)
from multiprocess_framework.modules.process_module.plugins import (
    PluginContext,
    ProcessModulePlugin,
    register_plugin,
)

from Services.otel_export.config import OtelExportConfig, format_validation_error
from Services.otel_export.exporter import OtlpHttpExporter, sdk_available
from Services.otel_export.interfaces import FlushOutcome
from Services.otel_export.mapping import DisplayRecordMapper, coerce_attributes, split_exportable
from Services.otel_export.resources import PooledResourceResolver

from .registers import OtelExportRegisters

__all__ = ["MAX_ATTEMPTS", "METRIC_PREFIX", "OtelExportPlugin"]


#: Ключ входящего сообщения хвоста. Тот же, что слушает GUI
#: (`multiprocess_prototype/frontend/process.py`) — экспортёр такой же
#: подписчик, а не привилегированный.
RECORD_MESSAGE_KEY = "observability.record"

#: Команды брокера подписок. Живут на оркестраторе (`ProcessManager`), имена —
#: из `command_contracts.ObservabilityTailBrokerParams`.
SUBSCRIBE_COMMAND = "observability.tail.subscribe_all"
UNSUBSCRIBE_COMMAND = "observability.tail.unsubscribe_all"

#: Адресат намерения. Имя ПРОЦЕССА (`targets`), не канал Router — см.
#: `ROUTING_GLOSSARY.md`.
BROKER_TARGET = "ProcessManager"

#: Сколько раз объявляется намерение, прежде чем плагин признаёт себя
#: деградировавшим. Дисциплина `tail_activator` GUI: повтор конечен, потому что
#: бесконечный повтор к недоступному брокеру — это не устойчивость, а тихий
#: поток запросов, который никто не считает.
MAX_ATTEMPTS = 3

#: Таймаут слота ответа брокера. Дефолт `request_async` (5 с) назван явно: число,
#: от которого зависит наблюдаемое поведение, не должно приезжать из чужого
#: дефолта молча.
SUBSCRIBE_TIMEOUT_SEC = 5.0

#: Окно голоса для повторяющихся жалоб хендлера (битый конверт, второй поток).
#: Секунды.
VOICE_WINDOW_SEC = 60.0

#: Префикс имён в ЧИСЛОВОЙ плоскости. В плоскости уровней те же имена идут БЕЗ
#: него: там имя становится сегментом пути дерева, а писателя в путь уже
#: подставил фреймворк (`state.plugins.otel_export.<имя>`) — префикс дал бы
#: `otel_export` дважды, да ещё и точкой, которую `declare_metric` отвергает.
METRIC_PREFIX = "otel_export."

#: Словарь счётчиков (Services/otel_export/README.md -> Counters). Кортеж, а не
#: список: набор фиксирован тождеством потерь Task 3.4, и дописывать его на ходу
#: значило бы менять тождество молча.
COUNTER_NAMES = (
    "received",
    "exported",
    "skipped_numbers",
    "mapper_rejected",
    "attr_coerced",
    "dropped_overflow",
    "export_failed",
    "resource_evicted",
)

#: Состояния плагина. СВОИ, а не `PluginState` фреймворка (Р-13): у того пять
#: значений (`idle/ready/running/paused/stopped`) и нет ни `error`, ни
#: `degraded` — то есть «поднялся, но экспортировать не может» в его словаре не
#: выразимо вовсе.
STATE_READY = "ready"
STATE_DEGRADED = "degraded"
STATE_ERROR = "error"


#: Имя очереди дренажа. Едет в ключ окна голоса (`batch_drain.<имя>.overflow`) и
#: в имя потока (`batch-drain-<имя>`) — по нему очередь экспортёра отличается в
#: `introspect` от очереди плоскости истории, которая устроена так же.
QUEUE_NAME = "otel_export"


class _OtelDrainWorker(BatchDrainWorker):
    """Очередь дренажа с голосом переполнения ПО ФРОНТУ, а не по каждой записи.

    **Зачем понадобилось трогать голос, а не взять класс как есть.** База зовёт
    `log_windowed` на КАЖДУЮ вытесненную запись; сама строка при этом выходит
    одна (окно душит остальные), но вызовов ровно столько, сколько вытеснений.
    Замер на этом же классе: ёмкость 2048, подано 3000 записей — **952 вызова
    голосовой машинерии на одну долетевшую строку**, и все 952 — в потоке
    ЭМИТЕНТА. У плоскости истории эмитент — любой поток, и цена размазана; здесь
    эмитент один и известен: это ПРИЁМНЫЙ поток процесса, где вся конструкция
    построена ради того, чтобы не платить за запись ничем, кроме постановки в
    буфер. Шторм вытеснений — ровно тот режим, когда почта процесса и так
    перегружена.

    Поэтому голос здесь **по фронту**: первое вытеснение эпизода звучит, а
    дальше очередь молчит, пока не опустеет ниже потолка. `log_windowed`
    остаётся вторым, политическим предохранителем — окно процесса никто не
    отменял.

    Отдельная польза, названная честно: приёмочный тест Task 2.4 считает ВЫЗОВЫ
    `log_windowed`, а не долетевшие строки, и на базовом классе видел бы 952 там,
    где строка одна. Правка сделана не ради теста — довод про приёмный поток
    выше стоит сам по себе, — но совпадение стоит назвать, а не умолчать.

    Флаг живёт без лока намеренно: пишет его один поток (приёмный), а цена
    ошибки — лишний или недостающий ВЫЗОВ голоса, который всё равно судит окно.
    Лок ради этого на горячем пути был бы дороже дефекта, который он лечит.
    """

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self._overflow_voiced = False

    def write(self, record: Any) -> Any:
        result = super().write(record)
        # Проверка глубины стоит ЗА флагом: `depth` берёт лок канала, и звать его
        # на каждой записи значило бы вернуть на горячий путь ту самую цену,
        # ради снятия которой класс и переопределён. Пока эпизод не объявлен,
        # второе условие не вычисляется вовсе.
        if self._overflow_voiced and self.depth < self.capacity:
            self._overflow_voiced = False
        return result

    def _voice_overflow(self) -> None:
        if self._overflow_voiced:
            return
        self._overflow_voiced = True
        super()._voice_overflow()


class OtelExportSubscribeError(RuntimeError):
    """Намерение подписаться на хвост не подтверждено за `MAX_ATTEMPTS` попыток.

    Свой тип, а не голый `RuntimeError`: инцидент едет в плоскость ошибок с
    трассой, и род исключения там — единственное, чем этот отказ отличается от
    любого другого в том же процессе.
    """


@register_plugin(
    "otel_export",
    category="output",
    description="Экспорт хвоста наблюдаемости в приёмник OTLP (OpenTelemetry Logs)",
)
class OtelExportPlugin(ProcessModulePlugin):
    """Подписка на хвост наблюдаемости -> отметка приёма -> модель OTel -> счётчики."""

    name = "otel_export"
    category = "output"

    #: Данные приходят подпиской на хвост, а не портами топологии — как у
    #: `telemetry_sink`. Пустые списки объявлены явно: у базы они тоже пустые, но
    #: критерий приёмки проверяет именно объявление.
    inputs: list = []
    outputs: list = []

    register_class = OtelExportRegisters

    #: Имена регистрируются ДОСЛОВНО (`_auto_register_commands` префикса не
    #: добавляет), поэтому префикс `otel_export.` пишется здесь руками — иначе
    #: `status` столкнулся бы с одноимённой командой соседа по процессу.
    commands = {
        "otel_export.status": "_cmd_status",
        "otel_export.flush": "_cmd_flush",
    }

    # ------------------------------------------------------------------ #
    # Жизненный цикл
    # ------------------------------------------------------------------ #

    def __init__(self) -> None:
        """Всё состояние — ЗДЕСЬ, а не в `configure()`. Правка ревью Н-1.

        **Что здесь может сломаться, и уже ломалось.** Первая редакция заводила
        состояние в `configure()`, и любой отказ ДО этой точки оставлял объект
        полупостроенным: `_cmd_status` читать нечего (команды к тому же не
        зарегистрированы — `_auto_register_commands` идёт после `configure`), а
        `shutdown()` падал вторым отказом `'OtelExportPlugin' object has no
        attribute '_subscribed'`, маскируя первый. Воспроизведено ревьюером на
        пяти конфигах и мной встречно: `{'endpoint': ''}`, `level='TRACE'`,
        литеральный секрет в `headers`, `max_queue_size` 2 и 0 — бросали все
        пять. Конструктор без аргументов отказать не может по построению, и
        только поэтому состояние, которое читают команды и останов, обязано
        жить в нём.

        Лок здесь безопасен: экземпляр строится ВНУТРИ процесса
        (`PluginOrchestrator._load_plugin` импортирует класс по dotted-path и
        зовёт `cls()`), через границу процессов не пиклится, и `_thread.lock`
        никуда не едет.
        """
        super().__init__()
        self._ctx: PluginContext | None = None
        self._reg: Any = None
        self._counters: dict[str, int] = dict.fromkeys(COUNTER_NAMES, 0)
        self._counters_lock = threading.Lock()
        #: Идентификаторы потоков, на которых исполнялся хендлер приёма (Р-11).
        #: dict, а не set: запись `d[k] = True` — одна операция байт-кода, и
        #: конкурентный доступ к ней не теряет ключей даже без лока, а лок в
        #: хендлере хочется держать ровно вокруг счётчиков.
        self._handler_threads: dict[int, bool] = {}
        #: Очередь дренажа. Строится в `configure()` вместе с конфигом (её
        #: потолки — оттуда), поэтому здесь `None`: до конфига ёмкости не
        #: существует, а очередь «на дефолтах» приняла бы записи в размер,
        #: которого оператор не заказывал.
        self._queue: BatchDrainWorker | None = None
        #: Сколько вытеснений очереди УЖЕ перенесено в счётчики плагина. Как и у
        #: пула Resource: канал считает нарастающим итогом, `record_metric` —
        #: counter, и отдать абсолют значило бы сложить его само с собой.
        self._queue_dropped_seen = 0
        #: Причина последнего ОТКАЗА доставки. Живёт здесь, потому что отправка
        #: ушла в поток дренажа: команда `flush` больше не видит исход
        #: собственными глазами и без этого поля отвечала бы «failed» без слов.
        #: Успех её стирает — иначе старая причина пережила бы починку.
        self._last_export_reason = ""
        self._stopped = False
        self._subscribed = False
        self._subscribe_attempts = 0
        self._resolver_evicted_seen = 0
        self._state = STATE_READY
        self._reason = ""
        self._sdk = ""
        self._cfg: OtelExportConfig | None = None
        self._mapper: DisplayRecordMapper | None = None
        self._resolver: PooledResourceResolver | None = None
        self._exporter: Any = None
        self._voice: Any = None

    def configure(self, ctx: PluginContext) -> None:
        """READY: регистры -> конфиг -> SDK -> маппер и пул. Не бросает (Р-14).

        **Что здесь может сломаться.** Оркестратор бросок из `configure()` ловит
        (`plugin_orchestrator.py`), процесс поднимется, но плагин останется в
        `IDLE`, а причина уедет одной строкой `log_error` — то есть команды
        `otel_export.status` не будет вовсе, и спросить «почему не экспортирует»
        будет не у кого. Голос — один разъём на ветку (ADR-PM-030): здесь
        `log_error`, а `health.report_error` — на исчерпании попыток подписки, в
        другой ветке.

        **Отказать умеют ДВЕ точки, а не одна, и вторая неочевидна (ревью Н-1).**
        `_init_register` применяет значения фрагмента топологии по одному через
        `setattr` при `validate_assignment=True` (`base.py:1422`), то есть
        валидатор схемы срабатывает ПРЯМО ТАМ — раньше, чем плагин соберёт
        `OtelExportConfig`. Первая редакция ловила только вторую точку, и
        покрытым оказался единственный случай, который и так работал: ключа во
        фрагменте НЕТ вовсе (тогда `setattr` не зовётся). Любое невалидное
        ЗНАЧЕНИЕ — пустая строка, `level='TRACE'`, литеральный секрет,
        `max_queue_size` ниже батча — бросало.

        Счётчики живут в `__init__` и здесь НЕ пересоздаются: повторный
        `configure()` не имеет права молча обнулить накопленные числа —
        обнулённый счётчик неотличим от «ничего не происходило».
        """
        self._ctx = ctx
        # Приёмник голоса для log_windowed: тот зовёт у логгера метод ПО ИМЕНИ
        # УРОВНЯ (`emit_voice`: getattr(logger, "warning")), а у контекста методы
        # зовутся `log_warning`. Тонкий переходник вместо своей копии окна.
        # Ставится ПЕРВЫМ вместе с ctx: `_fail` ниже уже нуждается в голосе.
        #
        # `error` в переходнике ОБЯЗАТЕЛЕН, и его отсутствие было тихим (Р-25).
        # `emit_voice` не находит метод уровня, пробует запасной `getattr(target,
        # "log")` — у `SimpleNamespace` нет и его — и строка ТЕРЯЕТСЯ, а
        # `log_windowed` при этом возвращает True («голос прозвучал»). Замер:
        # переходник без `error` -> вернул True, строк долетело 0; с `error` ->
        # True и 1. То есть возврат функции сторожем быть не может, сторожить
        # обязано ДОЛЕТЕВШУЮ строку.
        self._voice = SimpleNamespace(warning=ctx.log_warning, info=ctx.log_info, error=ctx.log_error)

        # Каталог уровней объявляется ДО разбора конфига: объявление — каталожная
        # запись, и она осмысленна даже у плагина, который дальше уйдёт в `error`
        # (иначе GUI не построит строк, и «счётчиков нет» будет неотличимо от
        # «плагина нет»). Имена БЕЗ точки и БЕЗ префикса — см. METRIC_PREFIX.
        for counter in COUNTER_NAMES:
            ctx.declare_metric(counter)

        # format_validation_error, а не str(exc): pydantic 2.13 печатает входное
        # значение целиком, и отвергнутый (то есть чаще всего настоящий)
        # заголовок авторизации уехал бы в system.log. Второй предохранитель —
        # `hide_input_in_errors` на самой схеме: он закрывает и ЭТУ дорогу, где
        # исключение приходит из чужого `setattr`, а не из нашего конструктора.
        try:
            self._reg = self._init_register(ctx)
            self._cfg = OtelExportConfig(**self._reg.model_dump())
        except ValidationError as exc:
            self._fail(f"конфиг отвергнут: {format_validation_error(exc)}")
            return

        available, detail = sdk_available()
        self._sdk = detail
        if not available:
            self._fail(f"OpenTelemetry SDK недоступен: {detail}")
            return

        self._mapper = DisplayRecordMapper()
        self._resolver = PooledResourceResolver(
            resource_pool_size=self._cfg.resource_pool_size,
            service_namespace=self._cfg.service_namespace,
        )
        # Экспортёр строится ЗДЕСЬ, а объект SDK внутри него — лениво, при первой
        # непустой отправке. Разница существенна: конструктор здесь ничего не
        # открывает и упасть не может (Р-18), поэтому `configure()` не обзаводится
        # третьей точкой отказа, а сокет к коллектору не появляется у процесса,
        # который за всю жизнь так ничего и не отправит.
        self._exporter = OtlpHttpExporter(self._cfg)
        # Очередь строится ПОСЛЕ экспортёра, но потока не заводит: `BatchDrainWorker`
        # поднимает его на ПЕРВОЙ записи. Процесс, за жизнь не принявший ни одной
        # записи, не платит потоком — та же дисциплина, что у ленивого объекта SDK.
        #
        # Стоком отдан МЕТОД, а не `self._exporter.export`: связанный метод
        # экспортёра зафиксировал бы объект навсегда, а `_export_batch` достаёт его
        # при каждом вызове — и в состоянии, где экспортёра нет, отвечает честно.
        self._queue = _OtelDrainWorker(
            self._export_batch,
            self._cfg.max_queue_size,
            counter_name="dropped_overflow",
            batch_size=self._cfg.max_export_batch_size,
            # Такт дренажа — тот же `schedule_delay_ms`, каким его знает оператор
            # (в SDK он ушёл бы в `BatchLogRecordProcessor`). Ни одного нового
            # литерала-потолка внутри механизма: все три числа видны в readback().
            flush_interval_sec=self._cfg.schedule_delay_ms / 1000.0,
            name=QUEUE_NAME,
        )
        ctx.log_info(
            f"otel_export: конфиг принят, endpoint={self._cfg.endpoint}, level={self._cfg.level}, SDK {detail}"
        )

    def start(self, ctx: PluginContext) -> None:
        """RUNNING: хендлер приёма, затем намерение брокеру.

        **Порядок обязателен.** Хендлер регистрируется ДО объявления намерения:
        брокер разворачивает подписку немедленно, и первая пачка может приехать
        раньше, чем вернётся подтверждение. Обратный порядок терял бы её молча —
        `RouterManager` на незарегистрированный ключ просто не находит адресата.

        В состоянии `error` не делается ни того, ни другого (Р-14): подписка без
        экспортёра — это трафик хвоста, оплаченный впустую, и запись, которая
        никуда не поедет, ещё и получит отметку приёма, будто её увидели.
        """
        if self._state == STATE_ERROR:
            ctx.log_warning(
                f"otel_export: старт в состоянии error ({self._reason}) — "
                "хендлер приёма не регистрируется, намерение брокеру не объявляется"
            )
            return

        ctx.router_manager.register_message_handler(RECORD_MESSAGE_KEY, self._on_records)
        self._announce_intent(1)

    def shutdown(self, ctx: PluginContext) -> None:
        """STOPPED: снять намерение, дожать ОГРАНИЧЕННО, назвать исход числами.

        **Что здесь может сломаться.** `_stopped` ставится ПЕРВЫМ действием, до
        чего бы то ни было: слот `request_async`, заведённый в `start()`, останов
        не отменяет, и опоздавший колбэк отказа завёл бы новую попытку подписки
        от имени уже остановленного плагина. Флаг — единственное, что отличает
        «ответ приехал вовремя» от «приехал в мёртвый объект».

        Снятие намерения идёт fire-and-forget той же дорогой, что объявление:
        ответа здесь ждать не на чем — процесс останавливается, и приёмный цикл
        уйдёт раньше, чем брокер успеет ответить.

        **Дожатие здесь ОГРАНИЧЕННОЕ, и ограничивает его очередь, а не SDK.**
        Task 2.2 не дожимала вовсе — вердикт CTO, и вот замер, на котором он
        стоял (коллектор не поднят):

            flush#1 24.36 с (failed=20) · flush#3 22.85 с (failed=4)
            launcher.shutdown() 5.17 с
              -> spawner: ProcessManager did not stop in 5.0s, terminating...
              -> строк «otel_export: остановлен» в журнале: 0
              -> последняя строка SDK: "retrying in 1.15s", финального отказа нет

        Бюджет останова у фреймворка — **5 с** (`process_registry.stop_all`,
        `spawner.stop_timeout`), а синхронная отправка живёт 23-42 с: процесс
        убивают внутри retry-цикла SDK, финальный снимок счётчиков не пишется, и
        последняя пачка выпадает из тождества потерь целиком — то есть механизм,
        заведённый ради видимости потерь, сам их прячет. Контроль с ЖИВЫМ
        коллектором: `shutdown()` 5.12 с, строка «остановлен» есть, запись
        доехала.

        Тогда ограничить дожатие было нечем: `export_timeout_sec` — дедлайн
        расписания ретраев, а не потолок вызова (замер: при 3000 мс вызов длился
        4.08 с, при 30 с на чёрную дыру — 42.08 с). **Task 2.4 нашла, чем:**
        дедлайн держит `BatchDrainWorker.flush(timeout)`, и он честен против
        зависшего стока по построению — работу делает поток дренажа, а
        останавливающий поток только ждёт прогресса и уходит по своему времени.
        Число — `flush_timeout_ms` из конфига (3 с), с запасом к бюджету
        фреймворка 5 с: после плагина останов ещё снимает намерение и гасит
        логгер, и забрав весь бюджет, плагин вернул бы ровно тот исход, ради
        которого дожатие отменяли.

        Что не дожали за дедлайн — потеря, и она произносится числами:
        `otel flush: N дожато, M потеряно` (литерал из `LogExporter.force_flush`,
        по нему стенд читает исход останова). Вторая строка,
        «otel_export: остановлен …», остаётся и обязана доезжать ВСЕГДА: по ней
        отличают штатный останов от процесса, убитого внутри чужого цикла.

        Порядок обязателен: дожатие идёт ДО строки итога — иначе строка называла
        бы числа, которые ещё не окончательны.
        """
        self._stopped = True

        if self._subscribed or self._subscribe_attempts:
            self._request_broker(
                UNSUBSCRIBE_COMMAND,
                {"subscriber": ctx.process_name},
                self._on_unsubscribe_answer,
            )

        outcome = self._drain_on_stop()
        # Уровень по факту: недожатое — не рутина. Строка одна на обе ветки,
        # чтобы стенд искал один литерал, а не два.
        flush_line = f"otel flush: {outcome.flushed} дожато, {outcome.lost} потеряно"
        if outcome.lost:
            ctx.log_warning(flush_line)
        else:
            ctx.log_info(flush_line)

        with self._counters_lock:
            snapshot = dict(self._counters)
        lost = outcome.lost
        message = (
            f"otel_export: остановлен, state={self._state}, "
            f"потеряно вместе с процессом (не дожато за {self._flush_timeout_sec():.1f} с) {lost}, "
            f"счётчики {snapshot}"
        )
        # Уровень выбирается по факту, а не по месту: потеря — не рутина, и INFO
        # уравнял бы её с обычным остановом. Разъём на ветке один в обоих случаях.
        if lost:
            ctx.log_warning(message)
        else:
            ctx.log_info(message)

    # ------------------------------------------------------------------ #
    # Намерение брокеру
    # ------------------------------------------------------------------ #

    def _announce_intent(self, attempt: int) -> None:
        """Объявить брокеру намерение подписаться на хвост всех процессов.

        **Что здесь может сломаться.** Дорога — `request_async`, и это решение
        Р-16, а не вкус: подтверждение брокера СУЩЕСТВУЕТ как наблюдаемый факт
        (команда зарегистрирована на PM обычной, без `manages_own_reply`, а
        `_dispatch_command` зовёт `reply_to_request` для любого билета с
        correlation-id), и `ctx.send_message` его бы просто выбросил. Синхронный
        `request()` здесь запрещён отдельно — приёмного цикла в момент `start()`
        ещё нет.

        `level` кладётся в намерение всегда: без него брокер подставит дефолт
        процесса (ERROR), и хвост станет ERROR-only по построению — то есть
        экспорт «работал» бы, показывая одну запись из сотни.
        """
        self._subscribe_attempts = attempt
        self._request_broker(
            SUBSCRIBE_COMMAND,
            {
                # Имя ПРОЦЕССА, а не константа и не имя плагина: пуши брокер
                # адресует процессу, и захардкоженный литерал увёл бы хвост
                # чужому адресату (или в никуда) молча.
                "subscriber": self._ctx.process_name,
                "level": self._cfg.level if self._cfg is not None else None,
            },
            lambda answer: self._on_subscribe_answer(attempt, answer),
        )

    def _request_broker(self, command: str, args: dict[str, Any], on_response: Any) -> None:
        """Отправить билет брокеру и подставить колбэк. Одно место на три вызова."""
        message = build_command_message(
            BROKER_TARGET,
            command,
            args,
            sender=self._ctx.process_name,
        )
        self._ctx.router_manager.request_async(
            message,
            on_response,
            timeout=SUBSCRIBE_TIMEOUT_SEC,
        )

    def _on_subscribe_answer(self, attempt: int, answer: Any) -> None:
        """Разобрать ответ брокера: подтверждение, повтор или исчерпание.

        **Что здесь может сломаться.** Колбэк зовётся на ПРИЁМНОМ потоке внутри
        `receive()` и ровно один раз — арбитраж `_take_pending` под локом сводит
        ответ, таймаут и синхронный отказ отправки в один вызов. Значит все три
        триггера повтора приходят СЮДА, и различать их по форме ответа не нужно:
        неуспех есть неуспех. Зато нужна короткость — пока этот метод работает,
        почта процесса не разбирается, поэтому здесь нет ничего, кроме проверки
        и следующей отправки.

        Повтор идёт прямо из колбэка (глубина рекурсии ограничена
        `MAX_ATTEMPTS`). Ждать между попытками нечем: `sleep` на приёмном потоке
        запрещён, а таймера у плагина нет — и заводить его ради трёх попыток
        значило бы завести поток ради ожидания.
        """
        if self._stopped:
            return
        if _answer_is_success(answer):
            self._subscribed = True
            self._ctx.log_info(
                f"otel_export: намерение подтверждено брокером с попытки {attempt}, "
                f"подписчик {self._ctx.process_name}, уровень {self._cfg.level if self._cfg else '?'}"
            )
            return

        if attempt >= MAX_ATTEMPTS:
            self._state = STATE_DEGRADED
            self._reason = f"брокер не подтвердил намерение после {MAX_ATTEMPTS} попыток: {answer!r}"
            # Один разъём на ветку: report_error И ЕСТЬ голос ERROR — он кладёт
            # факт в плоскость ошибок и пишет строку в журнал одним вызовом
            # (ADR-PM-030). Отдельный log_error рядом был бы вторым разъёмом на
            # том же пути исполнения и красным у AST-стража.
            # Исключение — ПОЗИЦИОННО первым аргументом: во фреймворке параметр
            # зовётся `exc`, и вызов `report_error(error=...)` сломался бы.
            self._ctx.health.report_error(
                OtelExportSubscribeError(self._reason),
                context="otel_export.subscribe_all",
            )
            return

        self._announce_intent(attempt + 1)

    def _on_unsubscribe_answer(self, answer: Any) -> None:
        """Ответ на снятие намерения. Повтора нет: процесс уже останавливается."""
        if _answer_is_success(answer):
            return
        self._ctx.log_warning(f"otel_export: снятие намерения не подтверждено: {answer!r}")

    # ------------------------------------------------------------------ #
    # Приём записей
    # ------------------------------------------------------------------ #

    def _on_records(self, message: Any) -> None:
        """Хендлер `observability.record`: отметка, фильтр, модель, счётчики.

        **Что здесь может сломаться.** Метод исполняется на ПРИЁМНОМ потоке
        процесса — пока он работает, почта не разбирается. Поэтому внутри нет ни
        сети, ни ожиданий, а отправка наружу отложена до Task 2.2/2.4 намеренно.

        **Где на самом деле уходит время — замерено, а не оценено** (правка ревью
        Н-4; прежняя редакция уверенно называла самой дорогой сборку `Resource`,
        и это было неверно). cProfile, пачка 3000 log-записей, три прогона.
        Абсолюты за прогон плывут (70.0 / 87.6 / 117.7 мс — на этой машине шум
        больше разницы между вторым и третьим местом), поэтому смысл несут ДОЛИ,
        и они устойчивы:

        * `to_otlp` — **48-50%** пути (маппер, включая разбор `extra.context`);
        * `_resolve_resource` — 22-24% (из них `PooledResourceResolver.resolve`
          13-14%, остальное — доставание `extra.context` из записи);
        * `dataclasses.replace` — 21% (пересборка frozen+slots записи);
        * `coerce_attributes` 4%, `split_exportable` и `stamp_observed` по 1-2%.

        То есть маппер дороже пула примерно в **2.1 раза**, а не наоборот.
        `_bump` в профиле нулевой не потому, что бесплатен, а потому что зовётся
        РАЗ НА ПАЧКУ, а не на запись — это и есть довод в пользу батчевого счёта.

        Порядок шагов не переставим. `stamp_observed` идёт ПЕРВЫМ: отметка должна
        стоять у записи, даже если её потом отбросит фильтр, — иначе «числовых
        было 500» и «хвост встал» перестанут различаться по задержке. Счётчик
        `received` считает ВСЁ, что приехало, до любой фильтрации, иначе тождество
        потерь Task 3.4 не сойдётся.

        `split_exportable` и `to_otlp` — два независимых сторожа числовой
        плоскости, и их расхождение — не дубль, а факт: запись `kind=log` с
        `severity=number` первый пропускает, второй отвергает. Такой отказ
        считается `mapper_rejected`, а НЕ `skipped_numbers` (Р-8): смешать их
        значило бы спрятать расхождение сторожей за общим числом.
        """
        self._handler_threads[threading.get_ident()] = True
        if len(self._handler_threads) > 1:
            # Не тишина и не строка на каждый приём (Р-11): пул Resource
            # потокобезопасным быть не обещал, а порча пула наблюдается не
            # счётчиком, а вот этим — числом разных идентификаторов.
            log_windowed(
                "otel_export.handler_threads",
                VOICE_WINDOW_SEC,
                "warning",
                "otel_export: хендлер приёма исполнялся более чем на одном потоке — "
                "пул Resource потокобезопасным не объявлен",
                logger=self._voice,
                threads=sorted(self._handler_threads),
            )

        records = self._extract_records(message)
        if not records:
            return

        stamp_observed(records, time.time())
        self._bump("received", len(records))

        to_send, skipped_by_kind = split_exportable(records)
        for kind, count in skipped_by_kind.items():
            # Разбивка по роду — тегом числовой плоскости: «пропущено 500» без
            # рода не отвечает на вопрос, чей это поток.
            self._bump("skipped_numbers", count, {"kind": kind or "<без рода>"})

        rejected = 0
        coerced_total = 0
        for record in to_send:
            mapped = self._mapper.to_otlp(record) if self._mapper is not None else None
            if mapped is None:
                rejected += 1
                continue
            attributes, coerced = coerce_attributes(mapped.attributes)
            coerced_total += coerced
            resource = self._resolve_resource(record)
            self._enqueue(replace(mapped, attributes=attributes, resource=resource))

        if rejected:
            self._bump("mapper_rejected", rejected)
        if coerced_total:
            self._bump("attr_coerced", coerced_total)
        self._sync_resource_evictions()

    def _extract_records(self, message: Any) -> list[dict]:
        """Нормализовать конверт в список записей. Форма — как у GUI-приёмника.

        **Что здесь может сломаться.** Форм входа две (`data.records` — пачка из
        дренажа, `data.record` — одиночная запись от tap'а на ошибке), и обе
        приходят на один ключ. Разобрать только первую значило бы терять ровно
        ошибки — то есть самое ценное, что есть в хвосте.

        Не-словарные элементы отбрасываются ДО `stamp_observed`: `split_exportable`
        зовёт у записи `.get`, и строка в списке уронила бы приёмный поток
        процесса. Отброшенное не идёт в `received` (это не запись) и не молчит —
        голос окном, потому что битый конверт бывает потоком, а не событием.
        """
        data = message.get("data") if isinstance(message, Mapping) else None
        if not isinstance(data, Mapping):
            return []

        raw = data.get("records")
        if raw is None:
            single = data.get("record")
            candidates = [single] if single is not None else []
        elif isinstance(raw, list):
            candidates = raw
        elif isinstance(raw, Mapping):
            # Одна запись, положенная под ключ пачки. Принимаем, но называем.
            candidates = [raw]
        else:
            candidates = []

        records = [item for item in candidates if isinstance(item, dict)]
        if len(records) != len(candidates) or (raw is not None and not isinstance(raw, list)):
            log_windowed(
                "otel_export.malformed_envelope",
                VOICE_WINDOW_SEC,
                "warning",
                "otel_export: конверт observability.record разобран не целиком",
                logger=self._voice,
                accepted=len(records),
                offered=len(candidates),
                records_type=type(raw).__name__,
            )
        return records

    def _resolve_resource(self, record: Mapping[str, Any]) -> Any:
        """Собрать `Resource` источника из `extra.context` записи.

        Контекст берётся ЗДЕСЬ, а не у маппера: маппер — чистая функция и о пуле
        не знает (`MappedRecord.resource` он оставляет `None` намеренно). Форма
        `extra` неоднородна — у числовых родов он плоский, — но сюда доезжают
        только не-числовые: их `extra` вложенный.
        """
        extra = record.get("extra")
        context = extra.get("context") if isinstance(extra, Mapping) else None
        if not isinstance(context, Mapping):
            context = {}
        return self._resolver.resolve(context) if self._resolver is not None else None

    def _enqueue(self, mapped: Any) -> None:
        """Отдать отображённую запись очереди дренажа. Цена — постановка в буфер.

        **Что здесь может сломаться.** Соблазн — держать рядом с очередью ещё и
        свой список «на всякий случай»: тогда на вопрос «сколько записей ждёт»
        появляются два ответа, они расходятся на первом же вытеснении, и
        расходятся молча. Поэтому буфер ровно один, и он чужой — готовый
        `BatchDrainWorker` с потолком `max_queue_size`, вытеснением `drop_oldest`
        и счётчиком: `drop_oldest` без счётчика — тихая потеря, ровно тот класс,
        ради которого заведено тождество Task 3.4.

        Очередь закрыта (останов уже прошёл) или не построена (состояние `error`)
        — запись не молчит: очередь считает её своей корзиной «после закрытия», а
        плагин говорит это окном. В `dropped_overflow` она НЕ идёт: тот счётчик
        обещает «не поместилось», и смешать с ним «пришло после останова» значило
        бы сделать число ложью, не сказав об этом ни строчки.
        """
        queue = self._queue
        if queue is None:
            return
        result = queue.write(mapped)
        if isinstance(result, Mapping) and result.get("closed"):
            log_windowed(
                "otel_export.write_after_close",
                VOICE_WINDOW_SEC,
                "warning",
                "otel_export: запись пришла после останова очереди и не отправлена",
                logger=self._voice,
            )

    # ------------------------------------------------------------------ #
    # Отправка (Task 2.4 — фоновая пачка, дожатие по команде и на останове)
    # ------------------------------------------------------------------ #

    def _export_batch(self, batch: list[Any]) -> int:
        """Сток очереди: отправить пачку, посчитать исход, произнести отказ.

        **Кто сюда приходит.** Поток дренажа очереди, и он у стока ЕДИНСТВЕННЫЙ
        (обещание `BatchDrainWorker`). Отсюда право ждать сеть сколько угодно: на
        приёмный поток процесса эта задержка больше не переносится.

        Возвращаемое число — контракт очереди: «сколько записей принято стоком».
        Разницу с длиной пачки очередь зачтёт в свою корзину потерь, поэтому
        врать здесь нельзя ни в одну сторону — `accepted` берётся из исхода
        экспортёра, а не из «вызов вернулся».

        **Что здесь может сломаться.** Три ловушки, и все три тихие.

        1. *Исход берётся из ВОЗВРАЩЁННОГО значения.* Отказы SDK уходят в
           stdlib-`logging`, у корневого логгера процесса хендлеров нет — при
           закрытом коллекторе экспортёр молчал бы, а счётчик показывал ноль
           потерь. Поэтому считается `outcome.failed`, а не «было ли исключение».
        2. *Голос — ОДИН на пачку, а не один на запись.* Иначе недоступный
           коллектор превращает 512 записей в 512 строк, и журнал становится
           непригоден ровно в тот момент, когда он нужен. `interval=None` — это и
           есть «окно из политики процесса» (Р-23); литеральное число здесь
           запрещено, потому что оно увело бы окно экспортёра из-под общей
           политики молча.
        3. *Переменная часть — в `ctx`, а не в тексте.* Ключ дросселя постоянен, и
           endpoint с числом внутри `msg` разошлись бы с ним: одна и та же
           жалоба с разными числами читалась бы как разные события.
        """
        exporter = self._exporter
        if exporter is None:
            # Экспортёра нет (состояние `error`) — пачка не принята НИ ОДНОЙ
            # записью, и очередь зачтёт её потерей. Молча вернуть длину значило
            # бы отчитаться об отправке, которой не было.
            return 0
        outcome = exporter.export(batch)

        if outcome.accepted:
            self._bump("exported", outcome.accepted)
        if not outcome.failed:
            self._last_export_reason = ""
        if outcome.failed:
            self._last_export_reason = outcome.reason
            self._bump("export_failed", outcome.failed)
            log_windowed(
                key="otel_export.export_failed",
                interval=None,
                level="error",
                msg="otel_export: записи не доставлены приёмнику OTLP",
                logger=self._voice,
                endpoint=self._cfg.endpoint if self._cfg is not None else "?",
                failed=outcome.failed,
                reason=outcome.reason,
            )
        return outcome.accepted

    def _flush_timeout_sec(self) -> float:
        """Дедлайн дожатия в СЕКУНДАХ. Одно место деления на 1000 — `readback()`."""
        if self._cfg is None:
            return 0.0
        return float(self._cfg.readback()["flush_timeout_sec"])

    def _flush_queue(self, timeout: float) -> FlushOutcome:
        """Дожать очередь до дедлайна и вернуть исход ДЕЛЬТОЙ этого дожатия.

        **Почему дельта, а не то, что отдаёт очередь.** `BatchDrainWorker.totals()`
        — накопленные итоги за жизнь экземпляра (так написано в его докстринге),
        и отдать их наружу как исход дожатия значило бы каждый раз называть числа
        всей жизни процесса: второе дожатие подряд отчиталось бы об отправке того,
        что уехало первым. Читателю команды и строки останова нужен ответ на
        вопрос «что сделал ЭТОТ вызов».

        Дельта берётся по счётчикам ОЧЕРЕДИ, а не плагина: в них уже сведены обе
        корзины (сток не принял / не дожали до дедлайна), а плагин считает только
        то, до чего экспортёр доехал.
        """
        queue = self._queue
        if queue is None:
            return FlushOutcome(flushed=0, lost=0)
        written_before, lost_before = queue.totals()
        queue.flush(timeout)
        written_after, lost_after = queue.totals()
        return FlushOutcome(flushed=written_after - written_before, lost=lost_after - lost_before)

    def _drain_on_stop(self) -> FlushOutcome:
        """Останов: дожать и ЗАКРЫТЬ очередь, уложившись в общий дедлайн.

        **Дедлайн один на оба шага, и это существенно.** `flush(t)` ждёт прогресса
        до `t`, `close(t)` join'ит поток ещё до `t` — сложенные наивно, они дают
        удвоенный бюджет, а бюджет останова у фреймворка один (5 с) и делится
        между всеми участниками. Поэтому второму шагу достаётся ОСТАТОК, и на
        зависшем стоке это честный ноль: `join(0)` возвращается сразу, а записи,
        оставшиеся у потока в руках, очередь объявляет потерянными сама.

        `close()` обязателен и идемпотентен: он закрывает приём — только после
        него запись, приехавшая с опозданием, попадает в корзину «после
        закрытия», а не в «переполнение».
        """
        queue = self._queue
        if queue is None:
            return FlushOutcome(flushed=0, lost=0)

        budget = self._flush_timeout_sec()
        deadline = time.monotonic() + budget
        written_before, lost_before = queue.totals()
        queue.flush(budget)
        queue.close(max(0.0, deadline - time.monotonic()))
        written_after, lost_after = queue.totals()
        self._sync_queue_counters()
        return FlushOutcome(flushed=written_after - written_before, lost=lost_after - lost_before)

    def _sync_queue_counters(self) -> None:
        """Перенести вытеснения очереди в счётчики плагина ДЕЛЬТОЙ, не значением.

        Берётся `get_info()["dropped"]` — счётчик КАНАЛА, то есть ровно
        «не поместилось». Соседний `counters()[counter_name]` для этого не
        годится: он по собственному докстрингу складывает вытеснение с отказом
        записи после `close()`, и `dropped_overflow` начал бы расти от записи,
        для которой в очереди было сколько угодно места.
        """
        queue = self._queue
        if queue is None:
            return
        dropped = int(queue.get_info().get("dropped", 0))
        delta = dropped - self._queue_dropped_seen
        if delta > 0:
            self._queue_dropped_seen = dropped
            self._bump("dropped_overflow", delta)

    def _sync_resource_evictions(self) -> None:
        """Перенести вытеснения пула в числовую плоскость ДЕЛЬТОЙ, не значением.

        `PooledResourceResolver.evicted` — счётчик за всё время жизни резолвера,
        а `record_metric` — counter (прибавляет). Отдать сюда абсолютное значение
        значило бы сложить его само с собой на каждой пачке: 1, 3, 6, 10…
        """
        if self._resolver is None:
            return
        delta = self._resolver.evicted - self._resolver_evicted_seen
        if delta > 0:
            self._resolver_evicted_seen = self._resolver.evicted
            self._bump("resource_evicted", delta)

    # ------------------------------------------------------------------ #
    # Счёт
    # ------------------------------------------------------------------ #

    def _bump(self, name: str, value: int = 1, tags: dict | None = None) -> None:
        """Прибавить `value` к счётчику `name` в ОБЕИХ плоскостях (Р-7).

        **Что здесь может сломаться.** `self._counters[name] += value` — это
        чтение, сложение и запись тремя операциями байт-кода, и переключение
        потока между ними теряет инкремент. Хендлер по построению однопоточен, но
        построение — это обещание, а лок — его проверка; неконкурентный лок стоит
        десятки наносекунд, а потерянный инкремент не виден вообще ничем.

        Лок держится ТОЛЬКО вокруг словаря: `record_metric` и `publish_metric`
        уходят в чужие механизмы (порт наблюдений, хранилище уровней) со своими
        локами, и удержание нашего на время чужого вызова — готовый порядок
        захвата двух локов, то есть заготовка дедлока.

        Плоскости две и обе обязательны: `record_metric` (точечное имя) читается
        `history_query`, `publish_metric` (имя без точки) — единственное, что
        видно в `introspect.telemetry -> levels`. Уровень публикуется НАКОПЛЕННЫМ
        значением, а не приращением: уровень отвечает на вопрос «сколько сейчас».
        """
        with self._counters_lock:
            self._counters[name] += value
            total = self._counters[name]
        self._ctx.record_metric(METRIC_PREFIX + name, value, tags)
        self._ctx.publish_metric(name, total)

    def _fail(self, reason: str) -> None:
        """Перевести плагин в `error` и назвать причину голосом (Р-14).

        Голос — `log_error`, а не `health.report_error`: это диагностическая
        строка о конфигурации, а не проглоченный инцидент рантайма. Оба разъёма в
        одной ветке исполнения запрещены и сторожатся машинно
        (`test_one_connector_per_point.py`), поэтому выбирается один — и здесь это
        тот, который называет причину читателю `otel_export.status`.
        """
        self._state = STATE_ERROR
        self._reason = reason
        self._ctx.log_error(f"otel_export: {reason}")

    # ------------------------------------------------------------------ #
    # Команды
    # ------------------------------------------------------------------ #

    def _cmd_status(self, data: dict | None = None) -> dict:
        """`otel_export.status` — единственное окно наружу в состояние экспортёра.

        **Что здесь может сломаться.** Три поля отвечают на три разных вопроса, и
        слить их нельзя: `state` — «может ли плагин экспортировать», `reason` —
        «почему нет», `sdk` — «установлен ли extra». Пустой `reason` при
        `state == "ready"` законен; непустой при `ready` означал бы, что причина
        осталась от прошлой жизни объекта.

        `handler_threads` — не украшение, а детектор (Р-11): список длиннее
        одного означает, что пул `Resource` работает в условиях, для которых он
        не построен.

        **`queue` отвечает на вопросы, которые счётчики не различают.** У очереди
        свои корзины потерь, и складывать их в одно число нельзя: «не поместилось»
        (`dropped_overflow`), «сток не принял» (`sink_failed`), «не дожали на
        останове» (`lost_on_close`) и «пришло после закрытия»
        (`dropped_after_close`) требуют РАЗНЫХ действий от читателя. Последнее
        считается вычитанием: собственный `counters()` очереди отдаёт его
        сложенным с переполнением под одним именем, и развести их можно только
        здесь.
        """
        self._sync_queue_counters()
        with self._counters_lock:
            counters = dict(self._counters)
        endpoint = self._cfg.endpoint if self._cfg is not None else getattr(self._reg, "endpoint", "")
        return {
            "state": self._state,
            "reason": self._reason,
            "sdk": self._sdk,
            "endpoint": endpoint,
            "handler_threads": sorted(self._handler_threads),
            "subscribed": self._subscribed,
            "subscribe_attempts": self._subscribe_attempts,
            "pending": self._queue.depth if self._queue is not None else 0,
            "counters": counters,
            "queue": self._queue_snapshot(),
        }

    def _queue_snapshot(self) -> dict:
        """Показания очереди дренажа с РАЗВЕДЁННЫМИ корзинами потерь."""
        queue = self._queue
        if queue is None:
            return {}
        info = queue.get_info()
        dropped_overflow = int(info.get("dropped", 0))
        return {
            "depth": int(info.get("depth", 0)),
            "capacity": int(info.get("capacity", 0)),
            "batch_size": info.get("batch_size"),
            "flush_interval_sec": info.get("flush_interval_sec"),
            "closed": bool(info.get("closed")),
            "written": int(info.get("written", 0)),
            "dropped_overflow": dropped_overflow,
            "sink_failed": int(info.get("sink_failed", 0)),
            "lost_on_close": int(info.get("lost_on_close", 0)),
            # Разность двух показаний очереди: `counters()` складывает
            # «не поместилось» и «пришло после close()» под именем вызывающего,
            # а `get_info()["dropped"]` — только первое.
            "dropped_after_close": int(info.get("dropped_overflow", 0)) - dropped_overflow,
        }

    def _cmd_flush(self, data: dict | None = None) -> dict:
        """`otel_export.flush` — отправить накопленное и ответить ЧИСЛАМИ (Р-21).

        **Что здесь может сломаться.** Соблазн — ответить `{"status": "ok"}` и
        нулями: команда есть, ошибки нет. Но «ok» у команды дожатия читается как
        «всё отправлено», и статус обязан различать три исхода — отправлено,
        часть не доехала, отправлять нечем. Поэтому `ok` ставится ровно при
        `failed == 0`, а не при «вызов вернулся».

        **Этот метод исполняется НА ПРИЁМНОМ ПОТОКЕ процесса, и другого
        вызывающего у него нет.** Команда приезжает конвертом `type=="command"`
        и попадает сюда изнутри `RouterManager.receive()`
        (`router_module/core/router_manager.py:1343` -> `_dispatch_command`);
        боевых вызовов мимо этой дороги не существует.

        **Цена ограничена с Task 2.4, и ограничивает её очередь.** Сама отправка
        ушла в поток дренажа; здесь остаётся ОЖИДАНИЕ прогресса, и оно кончается
        через `flush_timeout_ms` (3 с) в любом случае — против отвечающего
        коллектора, против мёртвого и против «чёрной дыры». До этого приёмный
        поток стоял столько, сколько живёт SDK: замеры CTO — refused при 30000 мс
        23.44 с, при 3000 мс 4.08 с (+36% сверх «потолка»), чёрная дыра 42.08 с,
        401 — 0.02 с. То есть `export_timeout_ms` этой границей не управлял и не
        управляет: у SDK это дедлайн расписания ретраев, а не потолок вызова.

        **Статусов три, а не два.** Дедлайн, истёкший при непустой очереди, —
        это не `ok`: записи не отправлены и не потеряны, они всё ещё ждут. Ответ
        `timeout` отличает «сейчас не доехало» от «доехало» и от «отказано».

        В состоянии `error` отправлять нечем и не через что (`_exporter` там не
        построен): ответ — отказ с причиной, а не пустой успех.
        """
        if self._state == STATE_ERROR or self._exporter is None or self._queue is None:
            return {
                "status": "error",
                "reason": self._reason or "экспортёр не построен",
                "pending": self._queue.depth if self._queue is not None else 0,
                "flushed": 0,
                "failed": 0,
            }

        with self._counters_lock:
            exported_before = self._counters["exported"]
            failed_before = self._counters["export_failed"]
        self._flush_queue(self._flush_timeout_sec())
        with self._counters_lock:
            flushed = self._counters["exported"] - exported_before
            failed = self._counters["export_failed"] - failed_before

        pending = self._queue.depth
        if failed:
            status = "failed"
        elif pending:
            status = "timeout"
        else:
            status = "ok"
        return {
            "status": status,
            "flushed": flushed,
            "failed": failed,
            "pending": pending,
            "reason": self._last_export_reason,
        }


def _answer_is_success(answer: Any) -> bool:
    """Прочитать ответ брокера. Неуспех — любой из трёх исходов `request_async`.

    Колбэк получает одну из трёх форм: конверт ответа команды (`success` +
    `result`), словарь таймаута (`{"success": False, "error": "timeout", …}`) и
    словарь синхронного отказа отправки (`{"success": False, "error": …}`).
    Различать их незачем — повтор нужен во всех трёх, — но нужен единый разбор:
    транспорт мог доставить билет (`success` верхнего уровня истинно), а сама
    команда отказать внутри `result`. Читать только верхний уровень значило бы
    считать подтверждением доставленный отказ.

    Отсутствие ключа `success` считается успехом: команда, вернувшая словарь без
    этого поля, свою работу сделала. Отсутствие ответа вовсе (`None`) — нет.
    """
    if not isinstance(answer, Mapping):
        return False
    if answer.get("error"):
        return False
    if answer.get("success") is False:
        return False
    result = answer.get("result")
    if isinstance(result, Mapping) and result.get("success") is False:
        return False
    return True
