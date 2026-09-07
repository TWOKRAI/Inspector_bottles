# -*- coding: utf-8 -*-
"""`OtelExportPlugin` — хост экспортёра OTLP: приём хвоста, отметка, счётчики (Task 2.1).

Side-effect плагин (нет `inputs`/`outputs`) в обычном `GenericProcessApp`, по
форме — как `telemetry_sink`. Что он делает сегодня: объявляет брокеру намерение
подписаться на хвост наблюдаемости ВСЕХ процессов, принимает пачки записей,
ставит им отметку приёма, отбрасывает числовую плоскость, приводит записи к
модели OTel и считает восемь величин в двух плоскостях.

**Чего он ещё НЕ делает, и это осознанно, а не забыто.** Наружу не уходит ни
одна запись: `LogExporter` появляется в Task 2.2/2.4. Отображённые записи
копятся в кольце ограниченного размера (`max_queue_size` из конфига), и
переполнение считается счётчиком `otel_export.dropped_overflow` — то есть уже
сегодня видно, сколько бы потерялось. Говорить «экспорт работает» до Ф4.1
нельзя.

**Что здесь может сломаться, учитывая, как оно устроено.**

1. *Хендлер живёт на ПРИЁМНОМ потоке процесса.* Пока он работает, почта
   процесса не разбирается. Отсюда запрет внутри него: ни сети, ни ожидания на
   локах, ни `sleep`. Единственный лок в хендлере — вокруг инкремента счётчиков,
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
"""

from __future__ import annotations

import threading
import time
from collections.abc import Mapping
from dataclasses import replace
from types import SimpleNamespace
from typing import Any

from pydantic import ValidationError

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
from Services.otel_export.exporter import sdk_available
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

    def configure(self, ctx: PluginContext) -> None:
        """READY: регистры -> конфиг -> SDK -> маппер и пул. Не бросает (Р-14).

        **Что здесь может сломаться.** Оркестратор бросок из `configure()` ловит
        (`plugin_orchestrator.py`), процесс поднимется, но плагин останется в
        `IDLE`, а причина уедет одной строкой `log_error` — то есть команды
        `otel_export.status` не будет вовсе, и спросить «почему не экспортирует»
        будет не у кого. Поэтому оба отказа (нет SDK, пустой/невалидный
        `endpoint`) ловятся тут: состояние `error`, причина текстом, оба читаются
        командой. Голос — один разъём на ветку (ADR-PM-030): здесь `log_error`,
        а `health.report_error` — на исчерпании попыток подписки, в другой ветке.

        Счётчики создаются ОДИН раз за жизнь объекта: повторный `configure()`
        (прямой вызов в обход `_do_configure`, который такое отсекает состоянием)
        не имеет права молча обнулить уже накопленные числа — обнулённый счётчик
        неотличим от «ничего не происходило».
        """
        self._ctx = ctx
        self._reg = self._init_register(ctx)

        # Пересборка на повторном configure допустима для всего, что выводится из
        # конфига, и запрещена для накопленного. Отсюда getattr-проверка.
        if getattr(self, "_counters", None) is None:
            self._counters: dict[str, int] = dict.fromkeys(COUNTER_NAMES, 0)
        self._counters_lock = threading.Lock()
        #: Идентификаторы потоков, на которых исполнялся хендлер приёма (Р-11).
        #: dict, а не set: запись `d[k] = True` — одна операция байт-кода, и
        #: конкурентный доступ к ней не теряет ключей даже без лока, а лок в
        #: хендлере хочется держать ровно вокруг счётчиков.
        self._handler_threads: dict[int, bool] = {}
        self._pending: list[Any] = []
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
        # Приёмник голоса для log_windowed: тот зовёт у логгера метод ПО ИМЕНИ
        # УРОВНЯ (`emit_voice`: getattr(logger, "warning")), а у контекста методы
        # зовутся `log_warning`. Тонкий переходник вместо своей копии окна.
        self._voice = SimpleNamespace(warning=ctx.log_warning, info=ctx.log_info)

        # Каталог уровней объявляется ДО разбора конфига: объявление — каталожная
        # запись, и она осмысленна даже у плагина, который дальше уйдёт в `error`
        # (иначе GUI не построит строк, и «счётчиков нет» будет неотличимо от
        # «плагина нет»). Имена БЕЗ точки и БЕЗ префикса — см. METRIC_PREFIX.
        for counter in COUNTER_NAMES:
            ctx.declare_metric(counter)

        try:
            self._cfg = OtelExportConfig(**self._reg.model_dump())
        except ValidationError as exc:
            # format_validation_error, а не str(exc): pydantic 2.13 печатает
            # входное значение целиком, и отвергнутый (то есть чаще всего
            # настоящий) заголовок авторизации уехал бы в system.log.
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
        """STOPPED: снять намерение симметрично объявлению, назвать итог числами.

        **Что здесь может сломаться.** `_stopped` ставится ПЕРВЫМ действием, до
        любой отправки: слот `request_async`, заведённый в `start()`, останов не
        отменяет, и опоздавший колбэк отказа завёл бы новую попытку подписки от
        имени уже остановленного плагина. Флаг — единственное, что отличает
        «ответ приехал вовремя» от «приехал в мёртвый объект».

        Снятие намерения идёт fire-and-forget той же дорогой, что объявление:
        ответа здесь ждать не на чем — процесс останавливается, и приёмный цикл
        уйдёт раньше, чем брокер успеет ответить.
        """
        self._stopped = True

        if self._subscribed or self._subscribe_attempts:
            self._request_broker(
                UNSUBSCRIBE_COMMAND,
                {"subscriber": ctx.process_name},
                self._on_unsubscribe_answer,
            )

        with self._counters_lock:
            snapshot = dict(self._counters)
        ctx.log_info(
            f"otel_export: остановлен, state={self._state}, в кольце осталось {len(self._pending)}, счётчики {snapshot}"
        )

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
        сети, ни ожиданий: самая дорогая операция — сборка `Resource` из пула, а
        отправка наружу отложена до Task 2.2/2.4 намеренно.

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
        """Положить отображённую запись в кольцо до появления отправки (Task 2.4).

        **Что здесь может сломаться.** Список без предела — утечка на долгом
        прогоне: хвост идёт непрерывно, а забирать записи пока некому. Предел —
        `max_queue_size` из конфига (то же число, которое потом уедет в
        `BatchLogRecordProcessor`), вытеснение — самое старое, и оно СЧИТАЕТСЯ:
        `drop_oldest` без счётчика — это тихая потеря, ровно тот класс, ради
        которого заведено тождество Task 3.4.
        """
        limit = self._cfg.max_queue_size if self._cfg is not None else 2048
        self._pending.append(mapped)
        if len(self._pending) > limit:
            overflow = len(self._pending) - limit
            del self._pending[:overflow]
            self._bump("dropped_overflow", overflow)

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
        """
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
            "pending": len(self._pending),
            "counters": counters,
        }

    def _cmd_flush(self, data: dict | None = None) -> dict:
        """`otel_export.flush` — дожать очередь. Сегодня дожимать НЕЧЕМ.

        **Что здесь может сломаться.** Соблазн — ответить `{"status": "ok"}` и
        нулями: команда есть, ошибки нет. Но «ok» у команды дожатия читается как
        «всё отправлено», а отправки в Task 2.1 нет вовсе — экспортёр появляется
        в Task 2.2/2.4. Поэтому статус `noop` и число записей, которые сейчас
        лежат в кольце: оно честно говорит, сколько бы дожималось.
        """
        if self._state == STATE_ERROR:
            return {"status": "error", "reason": self._reason, "pending": len(self._pending)}
        return {
            "status": "noop",
            "pending": len(self._pending),
            "flushed": 0,
            "reason": "отправка наружу появляется в Task 2.2/2.4; сейчас записи только копятся",
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
