# -*- coding: utf-8 -*-
"""Авторские тесты Task 2.1 — опасные места МЕХАНИЗМА `OtelExportPlugin`.

Дополнение к приёмочным (`test_f2_task21_acceptance.py`), а не замена: те писал
независимый тестер по критериям приёмки и без права видеть реализацию. Здесь —
то, что видно только автору: места, где механизм устроен так, что ошибка в нём
не проявится ни счётчиком, ни красным приёмочным тестом.

Что проверяется и почему именно это:

1. **Повторный `configure()` не обнуляет счётчики.** Обнулённый счётчик
   неотличим от «ничего не происходило», а `_do_configure` защищает только
   дорогу через состояние — прямой вызов проходит насквозь.
2. **`shutdown()` из состояния `error`.** Плагин, не дошедший до `start()`, не
   имеет ни намерения, ни хендлера; попытка снять несуществующее намерение — это
   лишний билет в останове и `AttributeError` там, где его никто не ждёт.
3. **Взаимное исключение вокруг счётчиков — барьером ВНУТРИ критической секции.**
   Шторм потоков лока не доказывает (GIL 3.12 не даёт вклиниться между
   операциями надёжно), поэтому ожидаемый исход — `BrokenBarrierError`.
4. **Битый конверт не роняет приёмный поток.** `split_exportable` зовёт у записи
   `.get`; строка в списке уронила бы поток, на котором стоит вся почта процесса.
5. **Колбэк брокера, приехавший после `shutdown()`.** Слот `request_async` живёт
   до ответа или таймаута; останов его не отменяет.
6. **`resource_evicted` — ДЕЛЬТА, а не абсолютное значение.** `record_metric` —
   counter; отдай ему накопленное число, и оно сложится само с собой.
7. **Переполнение кольца считается.** `drop_oldest` без счётчика — тихая потеря.
8. **Отказ, доехавший внутри `result` при успешном транспорте.** Читать только
   верхний уровень ответа значило бы считать подтверждением доставленный отказ.
9. **Второй поток приёма голосит ОКНОМ, а не строкой на каждый приём** (Р-11).

Ни один тест не имеет права зависнуть: там, где есть ожидание, оно ограничено
таймаутом барьера, а поток — daemon с дедлайном на `join`.
"""

from __future__ import annotations

import threading
from types import SimpleNamespace
from typing import Any

import pytest

from multiprocess_framework.modules.logger_module.core import windowed_voice
from multiprocess_framework.modules.process_module.plugins import PluginContext

from Plugins.io.otel_export import plugin as plugin_module
from Plugins.io.otel_export.plugin import MAX_ATTEMPTS, OtelExportPlugin

ENDPOINT = "http://127.0.0.1:4318"

JOIN_DEADLINE_SEC = 5.0
"""Дедлайн `join` для каждого вспомогательного потока. Тест, который ВИСНЕТ
вместо падения, хуже отсутствующего: он прячет регрессию за таймаутом прогона."""


@pytest.fixture(autouse=True)
def _fresh_voice_windows(monkeypatch: pytest.MonkeyPatch) -> None:
    """Свежий держатель окон голоса на КАЖДЫЙ тест файла.

    Держатель процессный, а окно у плагина — 60 с, то есть перекрывает весь
    прогон файла: первый тест, задевший ключ `otel_export.malformed_envelope`,
    делал соседа немым, и утверждение «строка сказана» краснело в наборе, будучи
    зелёным в одиночку. Поймано прогоном, а не предусмотрено: сначала так и
    покраснело.
    """
    monkeypatch.setattr(windowed_voice, "_PROCESS_VOICES", windowed_voice.WindowedVoices())


# --------------------------------------------------------------------------- #
# Харнесс. Свой, а не импорт из файла тестера: тот — приёмочный ТЗ-документ,
# и опираться на его внутренние хелперы значило бы связать два набора в один.
# --------------------------------------------------------------------------- #


class _CommandManagerDouble:
    def __init__(self) -> None:
        self.registered: dict[str, Any] = {}

    def register_command(self, name: str, method: Any) -> None:
        self.registered[name] = method

    def get_command_info(self, name: str) -> Any:
        return self.registered.get(name)


class _RouterDouble:
    """Дубль ГРАНИЦЫ процесса: перехватывает регистрацию хендлера и билеты.

    `auto=False` откладывает колбэк: сценарий «ответ приехал позже останова»
    иначе невоспроизводим — синхронный дубль отвечает раньше, чем тест успевает
    остановить плагин.
    """

    def __init__(self, answers: list | None = None, auto: bool = True) -> None:
        self.handlers: dict[str, Any] = {}
        self.request_calls: list[dict] = []
        self.callbacks: list[Any] = []
        self.answers: list = list(answers or [])
        self.auto = auto

    def register_message_handler(self, key: str, handler: Any, *a: Any, **k: Any) -> bool:
        self.handlers[key] = handler
        return True

    def request_async(self, message: dict, on_response: Any, timeout: float = 5.0, correlation_id: Any = None) -> str:
        self.request_calls.append(message)
        self.callbacks.append(on_response)
        cid = correlation_id or f"cid-{len(self.request_calls)}"
        if not self.auto:
            return cid
        answer = self.answers.pop(0) if self.answers else {"success": True, "result": {"success": True}}
        if answer is not None:
            on_response(answer)
        return cid

    def subscribe_calls(self) -> list[dict]:
        return [m for m in self.request_calls if m.get("command") == plugin_module.SUBSCRIBE_COMMAND]

    def unsubscribe_calls(self) -> list[dict]:
        return [m for m in self.request_calls if m.get("command") == plugin_module.UNSUBSCRIBE_COMMAND]


def _make_ctx(
    process_name: str = "camera_h",
    *,
    router: Any = None,
    command_manager: Any = None,
    config: dict | None = None,
) -> tuple[Any, dict[str, list[str]]]:
    """Контекст на РЕАЛЬНОМ конструкторе `PluginContext`; дубли — только границы.

    Возвращает `(ctx, voices)`, где `voices` — журнал по уровням: строки нужны
    в утверждениях, а перехват на границе процесса делает их наблюдаемыми, не
    заглядывая внутрь плагина.
    """
    voices: dict[str, list[str]] = {"debug": [], "info": [], "warning": [], "error": [], "critical": []}

    def _log(level: str):
        def _fn(message: str, **_fields: Any) -> None:
            voices[level].append(str(message))

        return _fn

    services = SimpleNamespace(
        name=process_name,
        worker_manager=None,
        command_manager=command_manager if command_manager is not None else _CommandManagerDouble(),
        router_manager=router if router is not None else _RouterDouble(),
        memory_manager=None,
        state_proxy=None,
        log_debug=_log("debug"),
        log_info=_log("info"),
        log_warning=_log("warning"),
        log_error=_log("error"),
        log_critical=_log("critical"),
        send_message=lambda *a, **k: True,
        receive_message=lambda *a, **k: None,
    )
    ctx = PluginContext(
        services=services,
        config=config if config is not None else {"endpoint": ENDPOINT},
        io=None,
        registers=None,
        plugin_name="otel_export",
    )
    return ctx, voices


def _started(**kwargs: Any) -> tuple[OtelExportPlugin, Any, dict[str, list[str]]]:
    ctx, voices = _make_ctx(**kwargs)
    plugin = OtelExportPlugin()
    plugin._do_configure(ctx)
    plugin._do_start(ctx)
    return plugin, ctx, voices


def _log_record(**overrides: Any) -> dict:
    record = {"kind": "log", "severity": "INFO", "severity_number": 9, "message": "m", "module": "x", "ts": 1.0}
    record.update(overrides)
    return record


def _envelope(records: Any) -> dict:
    return {"command": "observability.record", "data": {"records": records}}


def _run_in_thread(target: Any) -> BaseException | None:
    """Выполнить `target` в daemon-потоке и вернуть исключение (или None).

    Дедлайн `join` обязателен: без него отказ взаимного исключения проявился бы
    вечным ожиданием прогона, а не красным тестом.
    """
    box: list[BaseException | None] = [None]

    def _body() -> None:
        try:
            target()
        except BaseException as exc:  # noqa: BLE001 — предмет проверки, не отказ теста
            box[0] = exc

    thread = threading.Thread(target=_body, daemon=True)
    thread.start()
    thread.join(JOIN_DEADLINE_SEC)
    assert not thread.is_alive(), f"поток не завершился за {JOIN_DEADLINE_SEC} с — механизм подвис"
    return box[0]


# --------------------------------------------------------------------------- #
# 1. Повторный configure
# --------------------------------------------------------------------------- #


class TestRepeatedConfigure:
    def test_second_configure_does_not_zero_the_counters(self) -> None:
        """Обнулённый счётчик неотличим от «ничего не происходило».

        `_do_configure` защищает только дорогу через состояние (второй вызов там
        отсекается проверкой `state != IDLE`). Прямой `configure(ctx)` — а его
        зовут и стенды, и будущая перенастройка — проходит насквозь.
        """
        plugin, ctx, _voices = _started()
        handler = ctx.router_manager.handlers["observability.record"]
        handler(_envelope([_log_record(), _log_record()]))
        assert plugin._cmd_status({})["counters"]["received"] == 2

        plugin.configure(ctx)

        assert plugin._cmd_status({})["counters"]["received"] == 2, (
            "повторный configure обнулил накопленный счётчик — числа прошлой жизни исчезли молча"
        )

    def test_second_configure_rebuilds_the_derived_objects(self) -> None:
        """Пара к тесту выше: накопленное сохраняется, ВЫВЕДЕННОЕ пересобирается.

        Без этой пары «не обнуляет» удовлетворялось бы и полным no-op'ом, то есть
        плагин игнорировал бы новую конфигурацию, не сказав ни слова.
        """
        plugin, ctx, _voices = _started()
        first_resolver = plugin._resolver
        plugin.configure(ctx)
        assert plugin._resolver is not first_resolver, "configure не пересобрал пул Resource"
        assert plugin._cmd_status({})["state"] == "ready"


# --------------------------------------------------------------------------- #
# 2. shutdown из состояния error
# --------------------------------------------------------------------------- #


class TestShutdownFromError:
    def test_shutdown_after_failed_configure_sends_no_ticket_and_does_not_raise(self) -> None:
        """Плагин в `error` не доходил до `start()`: снимать нечего.

        `start()` в этом состоянии не регистрирует хендлер и не объявляет
        намерение (Р-14) — значит `shutdown()` не имеет права слать снятие: билет
        ушёл бы брокеру от подписчика, которого тот никогда не видел.
        """
        router = _RouterDouble()
        ctx, _voices = _make_ctx(router=router, config={})  # endpoint пуст -> error
        plugin = OtelExportPlugin()
        plugin._do_configure(ctx)
        plugin._do_start(ctx)
        assert plugin._cmd_status({})["state"] == "error"

        plugin._do_shutdown(ctx)

        assert router.unsubscribe_calls() == [], (
            f"снятие намерения отправлено из состояния error: {router.request_calls!r}"
        )
        assert plugin.state.value == "stopped"

    def test_shutdown_after_start_sends_exactly_one_unsubscribe(self) -> None:
        """Пара: у живого плагина снятие симметрично объявлению — ровно одно."""
        plugin, ctx, _voices = _started()
        plugin._do_shutdown(ctx)
        assert len(ctx.router_manager.unsubscribe_calls()) == 1
        message = ctx.router_manager.unsubscribe_calls()[0]
        assert message["data"]["subscriber"] == "camera_h"
        assert message["targets"] == ["ProcessManager"]


# --------------------------------------------------------------------------- #
# 3. Взаимное исключение вокруг счётчиков
# --------------------------------------------------------------------------- #


class _BarrierDict(dict):
    """Словарь счётчиков, который ЖДЁТ барьера внутри записи значения.

    Приём против GIL: шторм потоков взаимного исключения не доказывает — 3.12 не
    даёт надёжно вклиниться между операциями `d[k] += 1`. Барьер ВНУТРИ
    критической секции даёт детерминированный исход: под локом второй поток до
    записи не доходит, барьер не собирается и рвётся по таймауту.
    """

    def __init__(self, source: dict, barrier: threading.Barrier) -> None:
        super().__init__(source)
        self._barrier = barrier

    def __setitem__(self, key: Any, value: Any) -> None:
        self._barrier.wait()
        super().__setitem__(key, value)


class TestCounterMutualExclusion:
    def test_two_threads_cannot_be_inside_the_counter_section_together(self) -> None:
        """Ожидаемый исход — `BrokenBarrierError` у ОБОИХ: секция взаимно исключающая.

        Если лок снять, оба потока доходят до записи, барьер собирается, и
        исключений не будет вовсе — то есть красное состояние этого теста читается
        однозначно, а не «иногда падает».
        """
        plugin, _ctx, _voices = _started()
        barrier = threading.Barrier(2, timeout=0.75)
        plugin._counters = _BarrierDict(plugin._counters, barrier)

        outcomes = [None, None]

        def _bump_in(index: int):
            def _fn() -> None:
                outcomes[index] = _run_in_thread(lambda: plugin._bump("received", 1))

            return _fn

        left = threading.Thread(target=_bump_in(0), daemon=True)
        right = threading.Thread(target=_bump_in(1), daemon=True)
        left.start()
        right.start()
        left.join(JOIN_DEADLINE_SEC)
        right.join(JOIN_DEADLINE_SEC)
        assert not left.is_alive() and not right.is_alive(), "потоки не завершились — секция подвисла"

        assert all(isinstance(outcome, threading.BrokenBarrierError) for outcome in outcomes), (
            f"барьер внутри критической секции собрался — значит два потока были в ней "
            f"одновременно, лок счётчиков не держит: {outcomes!r}"
        )


# --------------------------------------------------------------------------- #
# 4. Битый конверт
# --------------------------------------------------------------------------- #


class TestMalformedEnvelope:
    @pytest.mark.parametrize(
        "payload",
        [
            {},
            {"records": []},
            {"records": "не список"},
            {"records": 7},
            {"record": None},
        ],
        ids=["пусто", "пустая-пачка", "строка", "число", "record-None"],
    )
    def test_broken_payload_neither_raises_nor_counts(self, payload: dict) -> None:
        """Приёмный поток процесса роняет ВСЮ почту — падать здесь нельзя.

        `split_exportable` зовёт у записи `.get`; строка в списке дала бы
        `AttributeError` прямо в `receive()`. Счётчик `received` при этом обязан
        остаться нулём: битый конверт — не запись.
        """
        plugin, ctx, _voices = _started()
        handler = ctx.router_manager.handlers["observability.record"]

        handler({"command": "observability.record", "data": payload})

        assert plugin._cmd_status({})["counters"]["received"] == 0, (
            f"битый конверт {payload!r} посчитан принятой записью"
        )

    def test_non_dict_items_are_dropped_and_the_rest_survives(self) -> None:
        """Смешанная пачка: годное доезжает, негодное отбрасывается и НЕ считается.

        Литералы (1 из 3) написаны здесь, а не выведены из длины входа: иначе
        тест согласился бы и с «отброшено всё».
        """
        plugin, ctx, voices = _started()
        handler = ctx.router_manager.handlers["observability.record"]
        good = _log_record()

        handler(_envelope(["мусор", good, None]))

        assert plugin._cmd_status({})["counters"]["received"] == 1
        assert good.get("observed_ts"), "уцелевшая запись не получила отметку приёма"
        assert any("разобран не целиком" in line for line in voices["warning"]), (
            f"отброшенные элементы конверта не названы вовсе: {voices['warning']!r}"
        )

    def test_message_without_data_is_ignored(self) -> None:
        """Конверт без `data` (или не-словарь вовсе) — не повод падать."""
        plugin, ctx, _voices = _started()
        handler = ctx.router_manager.handlers["observability.record"]
        handler({"command": "observability.record"})
        handler("вообще не конверт")
        assert plugin._cmd_status({})["counters"]["received"] == 0


# --------------------------------------------------------------------------- #
# 5. Колбэк брокера после останова
# --------------------------------------------------------------------------- #


class TestLateBrokerCallback:
    def test_refusal_arriving_after_shutdown_starts_no_new_attempt(self) -> None:
        """Слот `request_async` останов не отменяет — опоздавший отказ обязан молчать.

        Без флага `_stopped` повтор из колбэка объявил бы намерение от имени
        остановленного плагина: брокер восстановил бы хвост, читать который уже
        некому, и трафик шёл бы до конца жизни процесса.
        """
        router = _RouterDouble(auto=False)
        ctx, _voices = _make_ctx(router=router)
        plugin = OtelExportPlugin()
        plugin._do_configure(ctx)
        plugin._do_start(ctx)

        assert len(router.subscribe_calls()) == 1, "намерение не объявлено — сценарий не воспроизведён"
        late_callback = router.callbacks[0]

        plugin._do_shutdown(ctx)
        tickets_after_shutdown = len(router.request_calls)

        late_callback({"success": False, "error": "timeout"})

        assert len(router.request_calls) == tickets_after_shutdown, (
            f"опоздавший отказ породил новый билет: {router.request_calls[tickets_after_shutdown:]!r}"
        )
        assert len(router.subscribe_calls()) == 1

    def test_refusal_arriving_before_shutdown_does_retry(self) -> None:
        """Пара: до останова тот же отказ обязан дать вторую попытку.

        Без этой пары предыдущий тест удовлетворялся бы плагином, который не
        повторяет НИКОГДА.
        """
        router = _RouterDouble(auto=False)
        ctx, _voices = _make_ctx(router=router)
        plugin = OtelExportPlugin()
        plugin._do_configure(ctx)
        plugin._do_start(ctx)

        router.callbacks[0]({"success": False, "error": "timeout"})

        assert len(router.subscribe_calls()) == 2, (
            f"отказ до останова не привёл ко второй попытке: {router.request_calls!r}"
        )


# --------------------------------------------------------------------------- #
# 6-7. Пул Resource и кольцо
# --------------------------------------------------------------------------- #


class TestResourceEvictionsAndOverflow:
    def test_evictions_are_reported_as_a_delta_not_as_the_running_total(self) -> None:
        """`record_metric` — counter: абсолютное значение сложилось бы само с собой.

        Пул на одну запись + три РАЗНЫХ источника: вытеснений ровно 2 (первый
        источник заполняет пул, второй и третий вытесняют). Отдай сюда накопленное
        `resolver.evicted`, и в плоскость уехало бы 1 + 2 = 3.
        """
        plugin, ctx, _voices = _started(config={"endpoint": ENDPOINT, "resource_pool_size": 1})
        handler = ctx.router_manager.handlers["observability.record"]

        for pid in (1, 2, 3):
            handler(_envelope([_log_record(extra={"context": {"proc_name": f"p{pid}", "pid": pid, "incarnation": 0}})]))

        assert plugin._resolver.evicted == 2, "сценарий не воспроизведён: пул вытеснил не два источника"
        assert plugin._cmd_status({})["counters"]["resource_evicted"] == 2, (
            f"вытеснения посчитаны не дельтой: {plugin._cmd_status({})['counters']!r}"
        )

    def test_ring_overflow_is_counted_not_silent(self) -> None:
        """`drop_oldest` без счётчика — тихая потеря; тождество Task 3.4 не сойдётся.

        Кольцо на 512 записей, подано 515: в кольце обязано остаться 512,
        выброшено 3.

        **Почему предел не «2», как хотелось бы для наглядности.**
        `_init_register` применяет overrides ПОЛЕ ЗА ПОЛЕМ через `setattr` с
        `validate_assignment=True`, а порядок — из `model_fields`, где
        `max_queue_size` идёт РАНЬШЕ `max_export_batch_size`. Значит присвоение
        `max_queue_size = 2` проверяется против ещё не тронутого батча 512 и
        отвергается кросс-полевым валидатором — фрагмент топологии с малой
        очередью не применится вовсе, в каком бы порядке ключи в нём ни стояли.
        Это находка про дверь конфига, а не про плагин; здесь она обойдена
        значением, равным дефолту батча.
        """
        plugin, ctx, _voices = _started(config={"endpoint": ENDPOINT, "max_queue_size": 512})
        handler = ctx.router_manager.handlers["observability.record"]

        handler(_envelope([_log_record(message=f"m{i}") for i in range(515)]))

        status = plugin._cmd_status({})
        assert status["pending"] == 512, f"кольцо не удержало предел: {status!r}"
        assert status["counters"]["dropped_overflow"] == 3, f"выброшенное не посчитано: {status!r}"
        assert status["counters"]["received"] == 515


# --------------------------------------------------------------------------- #
# 8. Отказ внутри result при успешном транспорте
# --------------------------------------------------------------------------- #


class TestNestedRefusal:
    def test_transport_success_with_refusal_inside_result_is_not_a_confirmation(self) -> None:
        """Доставленный отказ — всё ещё отказ.

        Билет доехал (`success` верхнего уровня истинно), а сама команда брокера
        отказала внутри `result`. Читай плагин только верхний уровень — он счёл бы
        намерение подтверждённым, и хвост не пришёл бы НИКОГДА, при состоянии
        `ready` и без единой строки в журнале.
        """
        nested_refusal = {"success": True, "result": {"success": False, "reason": "нет такого процесса"}}
        router = _RouterDouble(answers=[nested_refusal] * (MAX_ATTEMPTS + 1))
        command_manager = _CommandManagerDouble()
        ctx, _voices = _make_ctx(router=router, command_manager=command_manager)

        plugin = OtelExportPlugin()
        plugin._do_configure(ctx)
        plugin._do_start(ctx)

        assert len(router.subscribe_calls()) == MAX_ATTEMPTS
        assert command_manager.registered["otel_export.status"]({})["state"] == "degraded"

    def test_answer_without_success_key_is_a_confirmation(self) -> None:
        """Пара: словарь без поля `success` — команда отработала, повтора нет.

        Без этой пары разбор ответа удовлетворялся бы «не подтверждаем никогда».
        """
        router = _RouterDouble(answers=[{"result": {"subscribers": ["camera_h"]}}])
        command_manager = _CommandManagerDouble()
        ctx, _voices = _make_ctx(router=router, command_manager=command_manager)

        plugin = OtelExportPlugin()
        plugin._do_configure(ctx)
        plugin._do_start(ctx)

        assert len(router.subscribe_calls()) == 1
        assert command_manager.registered["otel_export.status"]({})["state"] == "ready"


# --------------------------------------------------------------------------- #
# 9. Второй поток приёма
# --------------------------------------------------------------------------- #


class TestSecondHandlerThreadIsVoicedOnce:
    def test_second_thread_voices_once_per_window_not_per_record(self) -> None:
        """Р-11: появление второго идентификатора — голос ОКНОМ.

        Свежий держатель окон даёт фикстура файла (`_fresh_voice_windows`): он
        процессный, и голос по этому ключу из соседнего теста сделал бы результат
        зависимым от порядка прогона.

        Литералы: один голос на два приёма со второго потока, ноль — с первого.
        """
        plugin, ctx, voices = _started()
        handler = ctx.router_manager.handlers["observability.record"]

        handler(_envelope([_log_record()]))
        assert [line for line in voices["warning"] if "более чем на одном потоке" in line] == [], (
            "приём с ОДНОГО потока не должен давать тревогу вовсе"
        )

        assert _run_in_thread(lambda: handler(_envelope([_log_record()]))) is None
        assert _run_in_thread(lambda: handler(_envelope([_log_record()]))) is None

        alarms = [line for line in voices["warning"] if "более чем на одном потоке" in line]
        assert len(alarms) == 1, (
            f"ожидался ровно ОДИН голос на окно (не тишина и не строка на каждый приём): {alarms!r}"
        )
        assert len(plugin._cmd_status({})["handler_threads"]) == 3, (
            "в показании должны быть все увиденные идентификаторы потоков"
        )


# ---------------------------------------------------------------------------
# Плоскость уровней — сторож дописан ВЕДУЩИМ после инъекции I7 (ноль умерших).
# ---------------------------------------------------------------------------


class TestLevelPlaneIsDeclaredAndPublished:
    """Решение Р-7: счётчики живут в ДВУХ плоскостях, и вторая не была сторожена.

    Инъекционная матрица Task 2.1, заплата I7: снятие из `configure()` всего
    цикла `ctx.declare_metric(counter)` убило **0 тестов из 155**. Ось живая —
    объявление реально происходит и реально влияет на процесс, — то есть ноль
    означал отсутствующий сторож, а не место, где свойство не может измениться.

    Почему это не мелочь. Секция `levels` ответа `introspect.telemetry` собирает
    ТОЛЬКО объявленные уровни (`builtin_commands.py`, `_cmd_introspect_telemetry`);
    stats-плоскость там не видна вовсе. Сними объявление — и критерий приёмки
    «счётчики видны в `introspect_telemetry(otel_export)`» перестаёт держаться,
    причём молча: `history_query` продолжит отвечать, а пульт опустеет.

    Дубль стоит на ГРАНИЦЕ фреймворка (`ctx.declare_metric` / `ctx.publish_metric`)
    — это тот же законный случай, что `register_message_handler`: имя метода
    контекста и есть контракт, а не деталь реализации.
    """

    def _ctx_with_metric_spies(self, **kwargs: Any) -> tuple[Any, list[str], list[tuple[str, Any]]]:
        ctx, _voices = _make_ctx(**kwargs)
        declared: list[str] = []
        published: list[tuple[str, Any]] = []
        ctx.declare_metric = lambda name: (declared.append(name), name)[1]
        ctx.publish_metric = lambda name, value: published.append((name, value))
        return ctx, declared, published

    def test_every_counter_is_declared_as_a_dotless_level(self) -> None:
        """Объявлены все восемь имён словаря, и ни одно не несёт точку."""
        ctx, declared, _published = self._ctx_with_metric_spies(config={"endpoint": "http://127.0.0.1:4318"})

        OtelExportPlugin()._do_configure(ctx)

        assert set(declared) == {
            "received",
            "exported",
            "skipped_numbers",
            "mapper_rejected",
            "attr_coerced",
            "dropped_overflow",
            "export_failed",
            "resource_evicted",
        }, f"каталог уровней разошёлся со словарём счётчиков: {declared!r}"
        dotted = [name for name in declared if "." in name]
        assert not dotted, (
            f"уровень с точкой в имени: {dotted!r}. declare_metric отвергает такое ValueError "
            "(ADR-PM-038) — плагин упал бы на старте, а точечные имена законны только в stats"
        )

    def test_level_carries_the_running_total_not_the_increment(self) -> None:
        """Уровень отвечает «сколько СЕЙЧАС»: после двух пачек там сумма, не приращение."""
        router = _RouterDouble()
        ctx, _declared, published = self._ctx_with_metric_spies(
            router=router, config={"endpoint": "http://127.0.0.1:4318"}
        )

        plugin = OtelExportPlugin()
        plugin._do_configure(ctx)
        plugin._do_start(ctx)
        handler = router.handlers["observability.record"]

        def _batch(n: int) -> dict:
            record = {
                "kind": "log",
                "severity": "INFO",
                "severity_number": 9,
                "message": "m",
                "module": "x",
                "ts": 1000.0,
            }
            return {"data": {"records": [dict(record) for _ in range(n)]}}

        handler(_batch(2))
        handler(_batch(3))

        received = [value for name, value in published if name == "received"]
        assert received == [2, 5], (
            f"уровень 'received' обязан нести накопленное (2, затем 5), получено {received!r} — "
            "приращение вместо суммы делает пульт бессмысленным: два тика подряд покажут одно число"
        )
