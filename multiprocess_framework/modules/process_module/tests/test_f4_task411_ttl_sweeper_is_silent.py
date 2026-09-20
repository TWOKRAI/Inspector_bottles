# -*- coding: utf-8 -*-
"""Приёмочные тесты (RED, до реализации) — Task 4.11 «ttl-sweeper origin gate».

Критерий задачи: пересборка наблюдаемости с ``origin="ttl-sweeper"`` не имеет
права печатать голос ADR-PM-046 (смена смысла ``observability.stats.enabled``),
даже когда действующее значение ключа — ``False``. Довод из брифа: текст голоса
— совет АВТОРУ ключа, а свип его не вводил; автор уже был предупреждён на своей
дороге. Свип при этом не немой (сам факт возврата ключа к нижнему слою обязан
быть доказуем), истечения TTL не имеют права попадать в счётчик «подавлено»
окна голоса, повтор той же дороги (тот же ``origin``) тоже молчит, а
авторские дороги (бут, вотчер, ``config.reload``, ``switch:*``) продолжают
звучать как раньше.

Четыре критерия из брифа и их тесты в этом файле:
    1. Свип TTL молчит про ADR-PM-046, но сам факт возврата ключа доказан
       (``report`` + фактический уровень) ->
       ``TestDirectOriginGate.test_ttl_sweeper_origin_never_voices_adr_pm_046``
       (прямой вызов + достижимость) и
       ``TestSweepIntegration.test_sweep_reverting_an_unrelated_key_does_not_voice_adr_but_announces_itself``
       (интеграция: настоящий истёкший TTL-ключ; см. примечание в теле теста
       про то, почему собственная строка свипа доказана НЕ текстом в файле).
    2. Дорога ПОВТОРА свипа (тот же origin) тоже молчит N тактов подряд ->
       ``TestSweepIntegration.test_repeated_retry_ticks_on_the_same_origin_stay_silent``.
    3. Пара к 1+2: авторские дороги ПРОДОЛЖАЮТ голосить (гейт не имеет права
       заглушить никого, кроме свипа) ->
       ``TestDirectOriginGate.test_every_other_documented_origin_still_voices``.
    4. Число «подавлено» окна голоса не считает истечения TTL, только реальные
       действия оператора ->
       ``TestSuppressedCountExcludesTtlSweeps.test_ttl_expiry_is_not_counted_among_suppressed_operator_actions``.

**Голос читается ТОЛЬКО из файла настоящего ``LoggerManager``** — на этом же
механизме уже был случай (см. ``docs/claude/memory/
feedback_emergency_log_reaches_stderr_not_the_log_files.md``), когда 24 теста
на ``caplog`` были зелёными при неверном адресе записи, а красный дал ровно
один тест, открывавший файл. Здесь ``caplog`` не используется вовсе.

Границы (см. бриф): тела ``managers/observability_reload.py``,
``managers/observability_ttl.py``, ``managers/process_managers.py`` и файлы
``test_f4_task411_voice_at_apply_stage.py`` /
``test_f2_task212_repurposed_voice_window.py`` /
``test_repurposed_voice_window_hazards.py`` не читались (кроме сигнатур ``def
apply_observability_layers`` / ``def sweep_session_ttl``, снятых грепом одной
строки — сам код и докстринги функций не открывались). Публичные имена
(``apply_observability_layers``, ``sweep_session_ttl``, ``ObservabilityLayers``,
``process_observability_layers``, ``set_voices_policy`` / ``reset_voices_policy``
/ ``reset_process_voices`` / ``reset_voice_counters``) взяты грепом сигнатур
(``def <имя>``) и из УЖЕ СУЩЕСТВУЮЩИХ (не запрещённых) тестовых файлов той же
директории (``test_observability_ttl.py``, ``test_observability_audit.py``),
которые уже вызывают эти функции по имени — то есть это не догадка, а
подтверждённый грепом контракт.

**Что пришлось угадать (единственное место):** что ``sweep_session_ttl``
внутри реально зовёт ``apply_observability_layers(..., origin="ttl-sweeper")``
при успешном возврате истёкшего ключа. Это не читалось в теле функции (файл
запрещён), но это ЯВНО заявлено самим брифом задачи («N тактов повтора → 0
строк», «дорога ПОВТОРА свипа — тот же origin») и подтверждено косвенно грепом
по незапрещённому ``test_observability_audit.py``, где
``audit.record(ACTION_EXPIRE, origin="ttl-sweeper", ...)`` — та же строка уже
используется как origin боевого кода. Если это не так — тесты, завязанные на
интеграционный путь (``TestSweepIntegration``), покраснеют по ДРУГОЙ причине
(``AttributeError``/не тем текстом), и это тоже валидный и диагностируемый
результат, а не порча теста.

**Второе, менее уверенное место:** что ``config.reload`` без файла
(``path``) и без ``ttl`` всё равно уходит в СЕССИОННЫЙ слой с ttl по умолчанию
(300 с) — установлено по докстрингу и соседнему тесту
``test_write_without_ttl_still_gets_a_deadline`` (тот же приём для
``logger.sink.disable``), не проверено напрямую для ``config.reload``. Для
тестов этого файла это не критично: важен только факт немедленной пересборки
(и тем самым голоса), а не то, в какой слой запись легла и когда истечёт.

**Прогон подтвердил (не догадка, а измерение на стенде):** окно голоса
ADR-PM-046 не пересекается между разными ``origin`` на одном и том же
``ObservabilityLayers`` (иначе 7 из 8 параметризованных тестов ниже
подавились бы окном, открытым первым же тестом класса — они не подавились,
все прошли зелёными на РЕАЛЬНОМ, ещё не тронутом коде).
"""

from __future__ import annotations

from typing import Any, Dict, List

import pytest

from multiprocess_framework.modules.logger_module.configs.logger_manager_config import (
    LoggerManagerConfig,
)
from multiprocess_framework.modules.logger_module.core.logger_manager import LoggerManager
from multiprocess_framework.modules.logger_module.core.windowed_voice import (
    reset_process_voices,
    reset_voice_counters,
    reset_voices_policy,
    voice_counters,
)
from multiprocess_framework.modules.process_module.commands.builtin_commands import BuiltinCommands
from multiprocess_framework.modules.process_module.configs.observability_layers import (
    ObservabilityLayers,
    process_observability_layers,
)
from multiprocess_framework.modules.process_module.managers.observability_reload import (
    apply_observability_layers,
)
from multiprocess_framework.modules.process_module.managers.observability_ttl import sweep_session_ttl

ORIGIN_TTL_SWEEPER = "ttl-sweeper"

# Инвентарь авторских дорог из брифа (кроме "рождения менеджеров" — её литерал
# origin бриф не называет, угадывать не стали, см. докстринг файла).
OTHER_DOCUMENTED_ORIGINS = [
    "boot:layers",
    "boot:companion",
    "watcher:app",
    "watcher:recipe",
    "command:config.reload",
    "switch:broadcast",
    "switch:recipe_change",
]


@pytest.fixture(autouse=True)
def _isolated_voice_state():
    """``windowed_voice`` — процессный singleton (см. memory
    ``feedback_windowed_voice_is_a_process_wide_singleton``): держатель окон,
    политика и счётчики живут на процесс, а не на тест. Сбрасываем ДО и ПОСЛЕ
    каждого теста, чтобы этот файл не зависел от порядка своих же тестов и не
    портил соседей при прогоне вместе с остальным пакетом.
    """

    reset_process_voices()
    reset_voice_counters()
    reset_voices_policy()
    try:
        yield
    finally:
        reset_process_voices()
        reset_voice_counters()
        reset_voices_policy()


# ---------------------------------------------------------------------------
# Вспомогательные фейки — минимальный процесс с РЕАЛЬНЫМ логированием.
# ---------------------------------------------------------------------------


class _Clock:
    """Управляемые часы для СЛОЯ TTL (отдельная ось от окна голоса)."""

    def __init__(self, start: float = 1000.0) -> None:
        self.now = start

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


class _Cm:
    def __init__(self) -> None:
        self.handlers: Dict[str, Any] = {}

    def register_command(self, name, handler, metadata=None, tags=None) -> None:
        self.handlers[name] = handler


class _RealVoiceSvc:
    """Минимальный процесс: ``_log_*`` пишут в НАСТОЯЩИЙ ``LoggerManager``.

    В отличие от фейкового харнесса ``_Svc`` в ``test_observability_ttl.py``
    (там ``_log_warning`` копит строки в список), здесь запись уходит через
    ``self.logger_manager.warning(...)`` — то есть в файл. Бриф прямо требует
    читать голос ИЗ ФАЙЛА, а не из перехваченного списка/``caplog``.
    """

    def __init__(self, logger: LoggerManager, config: Dict[str, Any] | None = None) -> None:
        self.command_manager = _Cm()
        self.name = "t411_seg"
        self.logger_manager = logger
        self.error_manager = None
        self.stats_manager = None
        self.worker_manager = None
        self.router_manager = None
        self._state_proxy = None
        self._heartbeat = None
        self._config = dict(config or {})

    def get_config(self, key, default=None):
        return self._config.get(key, default)

    def send_message(self, target, message) -> None:  # pragma: no cover — не используется здесь
        pass

    def _log_debug(self, message: str, **kwargs) -> None:
        kwargs.setdefault("module", self.name)
        self.logger_manager.debug(message, **kwargs)

    def _log_info(self, message: str, **kwargs) -> None:
        kwargs.setdefault("module", self.name)
        self.logger_manager.info(message, **kwargs)

    def _log_warning(self, message: str, **kwargs) -> None:
        kwargs.setdefault("module", self.name)
        self.logger_manager.warning(message, **kwargs)

    def _log_error(self, message: str, **kwargs) -> None:
        kwargs.setdefault("module", self.name)
        self.logger_manager.error(message, **kwargs)

    # ProcessHeartbeat / некоторые команды зовут публичные имена
    log_info = _log_info
    log_debug = _log_debug


def _log_text(tmp_path) -> str:
    """Содержимое ВСЕХ файлов ``*.log`` под каталогом логов теста."""

    parts: List[str] = []
    for path in tmp_path.rglob("*.log"):
        parts.append(path.read_text(encoding="utf-8", errors="replace"))
    return "\n".join(parts)


def _adr_lines(tmp_path) -> List[str]:
    return [line for line in _log_text(tmp_path).splitlines() if "ADR-PM-046" in line]


def _level(svc) -> str:
    return svc.logger_manager.config.default_level


# ---------------------------------------------------------------------------
# Фикстуры
# ---------------------------------------------------------------------------


@pytest.fixture
def bare_logger(tmp_path):
    """Только настоящий файловый ``LoggerManager`` — для прямых вызовов
    ``apply_observability_layers`` без обвязки процесса."""

    logger = LoggerManager(
        config=LoggerManagerConfig(
            app_name="t411_bare",
            log_directory=str(tmp_path),
            enable_batching=False,
        )
    )
    try:
        yield tmp_path
    finally:
        logger.shutdown()


@pytest.fixture
def real_wired(tmp_path, monkeypatch):
    """Полный минимальный процесс: настоящий логгер + команды + управляемые
    часы СЛОЯ TTL (НЕ окна голоса — то отдельная ось, живёт на время.monotonic).

    ``MULTIPROCESS_LOG_DIR`` выставляется В ФИКСТУРЕ, и это не косметика.
    Свип зовёт ``apply_observability_layers`` БЕЗ ``log_dir``; дальше
    ``base_managers_payload(None)`` → ``resolve_base_log_dir(None)`` при молчащем
    окружении отдаёт машинный дефолт (системный temp), и ``logger.reconfigure``
    внутри свипа уводит приёмники ИЗ ``tmp_path``. Голос ADR при этом уцелевает
    (он звучит ДО ``reconfigure``), а собственный голос свипа ``_announce_revert``
    — нет, он звучит ПОСЛЕ. Без этой строки вторая половина критерия 1 была бы
    ненаблюдаема, и первая редакция теста именно поэтому её и сняла — назвав при
    этом НЕВЕРНУЮ причину (см. разбор в тесте ниже).
    """

    monkeypatch.setenv("MULTIPROCESS_LOG_DIR", str(tmp_path))
    logger = LoggerManager(
        config=LoggerManagerConfig(
            app_name="t411_wired",
            log_directory=str(tmp_path),
            enable_batching=False,
        )
    )
    svc = _RealVoiceSvc(logger)
    bc = BuiltinCommands(svc)
    bc._register_observability_commands()
    clock = _Clock()
    process_observability_layers(svc).clock = clock
    try:
        yield svc, svc.command_manager.handlers, clock, tmp_path
    finally:
        logger.shutdown()


# ---------------------------------------------------------------------------
# Критерий 1 + достижимость: дорога ttl-sweeper молчит, авторские — нет.
# Прямой вызов apply_observability_layers, минимальный контекст.
# ---------------------------------------------------------------------------


class TestDirectOriginGate:
    def test_ttl_sweeper_origin_never_voices_adr_pm_046(self, bare_logger) -> None:
        """Критерий 1 (половина): origin="ttl-sweeper" молчит даже при
        stats.enabled=False."""

        tmp_path = bare_logger
        layers = ObservabilityLayers(app={"stats": {"enabled": False}})

        apply_observability_layers(layers, origin=ORIGIN_TTL_SWEEPER)
        assert _adr_lines(tmp_path) == [], (
            "дорога ttl-sweeper напечатала ADR-PM-046 — она ключ не вводила, автора предупреждать не должна"
        )

        # Достижимость В ТОМ ЖЕ тесте: тот же resolved (stats.enabled всё ещё
        # False), другой origin — обязан заговорить. Ноль строк выше не имеет
        # права означать «голос вообще не работает на этом стенде».
        apply_observability_layers(layers, origin="command:config.reload")
        lines = _adr_lines(tmp_path)
        assert len(lines) == 1, f"механизм голоса недостижим на этом стенде вовсе: {lines}"
        assert "ADR-PM-046" in lines[0]

    @pytest.mark.parametrize("origin", OTHER_DOCUMENTED_ORIGINS)
    def test_every_other_documented_origin_still_voices(self, bare_logger, origin: str) -> None:
        """Критерий 3: гейт не имеет права заглушить никого, кроме свипа —
        авторская дорога (здесь: любая из документированных) продолжает
        голосить ровно как до задачи."""

        tmp_path = bare_logger
        layers = ObservabilityLayers(app={"stats": {"enabled": False}})

        apply_observability_layers(layers, origin=origin)
        lines = _adr_lines(tmp_path)
        assert len(lines) == 1, f"дорога {origin!r} обязана звучать так же, как до задачи: {lines}"


# ---------------------------------------------------------------------------
# Критерии 1 + 2 (интеграция): реальный свип реального TTL-ключа.
# ---------------------------------------------------------------------------


class TestSweepIntegration:
    """Две ловушки теста, которые пришлось найти прогоном (записано честно).

    1) Первая редакция ставила ``layers.app = {"stats": {"enabled": False}}``
    ДО операторской настройки TTL-ключа. Настройка сама идёт через
    ``apply_observability_layers`` и открывала окно голоса ПЕРВОЙ — и тогда
    «свип не добавил строк» проходил ЗАКОННО (окно уже открыто), ничего не
    говоря про origin. Порядок ниже НАРОЧНО другой: плоскость выключается
    ПОСЛЕ настройки TTL-ключа, тихим присваиванием слоя.

    2) Настройка TTL-ключа НЕ идёт через команду ``config.reload`` — та тоже
    зовёт ``apply_observability_layers``/``logger.reconfigure``, и тогда за тест
    было бы ДВА обращения к шву вместо одного, а проверяется голос ровно того,
    которое делает сам свип. Поэтому настройка идёт напрямую через
    ``layers.session_set`` (чистые данные, без ``reconfigure``).

    **Исправлено по ревью 2026-09-08 — прежняя редакция называла здесь неверную
    причину и на её основании сняла половину критерия приёмки.** Утверждалось,
    что WARNING канала ``observability`` не маршрутизируется в файл, потому что
    минимальные слои не несут ``channels``/``observation.rules``. Ревьюер
    воспроизвёл обратное: на голом ``LoggerManager`` запись канала
    ``observability`` уходит в файл (файл=1, stderr=0). Настоящая причина —
    ``log_dir``: свип зовёт применение без него, машинный дефолт при молчащем
    окружении указывает в системный temp, и ``reconfigure`` уводит приёмники из
    ``tmp_path``. Одна строка в фикстуре (``MULTIPROCESS_LOG_DIR``) снимает это,
    и **обе половины критерия 1 наблюдаемы в файле одновременно**.

    Отсюда же снято слово «вакуумная»: проверка не вакуумна, и это измерено
    парой — при заглушённом ``_announce_revert`` строка «TTL истёк» в файле
    пропадает, при снятом гейте строка ADR-PM-046 в файле появляется.
    """

    def test_sweep_reverting_an_unrelated_key_does_not_voice_adr_but_announces_itself(self, real_wired) -> None:
        """Критерий 1 целиком: 0 строк ADR-PM-046 И ровно 1 строка о том, что
        сам свип истёкший ключ таки вернул — без второй половины ноль в первой
        значил бы «свип вообще не отработал», а не «гейт сработал»."""

        svc, handlers, clock, tmp_path = real_wired
        layers = process_observability_layers(svc)

        # Настройка TTL-ключа данными слоя — плоскость ЕЩЁ включена (по
        # умолчанию), и reconfigure ЛОГГЕРА не вызывается вовсе.
        layers.session_set("log_level", "DEBUG", 10, origin="test-setup")
        assert _adr_lines(tmp_path) == [], "стенд не чист: голос уже звучал до включения плоскости"

        # Плоскость выключается ДАННЫМИ слоя, без apply — voice не звучит.
        layers.app = {"stats": {"enabled": False}}

        clock.advance(11)
        report = sweep_session_ttl(svc)
        assert report is not None and report.get("keys") == ["log_level"], report
        assert _level(svc) != "DEBUG", "ключ не вернулся к нижнему слою — свип не сработал вовсе"

        # Вторая половина критерия 1 — В ФАЙЛЕ, а не только через report.
        # Первая редакция теста сняла её, объяснив это тем, что WARNING канала
        # `observability` в файл не маршрутизируется. Объяснение неверно
        # (воспроизведено ревью: на голом LoggerManager та же запись в файле
        # есть). Настоящая причина — переезд каталога логов внутри свипа; она
        # снимается одной строкой в фикстуре, и проверка становится возможной.
        #
        # Эти две строки — контроль достижимости друг для друга: без строки
        # «TTL истёк» ноль строк ADR означал бы «свип вообще не отработал».
        revert_lines = [ln for ln in _log_text(tmp_path).splitlines() if "TTL истёк" in ln]
        assert len(revert_lines) == 1, (
            "свип обязан сказать О СЕБЕ ровно один раз — иначе ноль строк ADR ниже "
            f"означал бы «свип не отработал», а не «гейт сработал»; строк: {revert_lines!r}"
        )
        assert _adr_lines(tmp_path) == [], (
            "возврат по TTL (origin=ttl-sweeper) заговорил про ADR-PM-046, хотя сам свип "
            "плоскость чисел не включал и не выключал"
        )

    def test_repeated_retry_ticks_on_the_same_origin_stay_silent(self, real_wired) -> None:
        """Критерий 2: повтор той же дороги (тот же origin) — N тактов, 0
        строк ADR-PM-046, включая финальный успешный повтор."""

        svc, handlers, clock, tmp_path = real_wired
        layers = process_observability_layers(svc)

        layers.session_set("log_level", "DEBUG", 10, origin="test-setup")
        assert _adr_lines(tmp_path) == [], "стенд не чист: голос уже звучал до включения плоскости"

        layers.app = {"stats": {"enabled": False}}
        clock.advance(11)

        broken = svc.logger_manager.reconfigure

        def _fail(payload):
            raise RuntimeError("reconfigure упал")

        svc.logger_manager.reconfigure = _fail
        try:
            for _ in range(5):
                sweep_session_ttl(svc)
        finally:
            svc.logger_manager.reconfigure = broken

        assert _adr_lines(tmp_path) == [], (
            "пять неудачных повторов дороги ttl-sweeper (тот же origin) напечатали ADR-PM-046"
        )

        recovered = sweep_session_ttl(svc)
        assert recovered is not None and recovered.get("success") is True, recovered

        assert _adr_lines(tmp_path) == [], "успешный (шестой) повтор той же дороги тоже обязан был промолчать"


# ---------------------------------------------------------------------------
# Критерий 4: истечения TTL не попадают в число подавленных операторских
# действий. Мера — процессный счётчик ``windowed_suppressed``
# (``windowed_voice.take()`` бампит его ТОЛЬКО когда сам подавляет попытку,
# до и независимо от того, куда потом уходит текст строки) — а не текст
# суффикса «подавлено» в файле. Так весь тест остаётся детерминированным, без
# реального ``time.sleep``: подавление проверяется на попытке взять окно, а
# не на том, что окно потом ЗАКРОЕТСЯ и кто-то напечатает суффикс.
# ---------------------------------------------------------------------------


class TestSuppressedCountExcludesTtlSweeps:
    def test_ttl_expiry_is_not_counted_among_suppressed_operator_actions(self, real_wired) -> None:
        svc, handlers, clock, tmp_path = real_wired
        layers = process_observability_layers(svc)

        baseline_counter = voice_counters()["windowed_suppressed"]

        # Настройка (плоскость ещё включена — окно ADR-PM-046 не трогается).
        handlers["config.reload"]({"observability": {"log_level": "DEBUG"}, "ttl": 100})
        layers.app = {"stats": {"enabled": False}}

        # Действие A (оператор) — первый взгляд на выключенную плоскость в
        # этом тесте: окно открывается, не подавлено.
        res_a = handlers["config.reload"]({"observability": {"log_level": "INFO"}})
        assert res_a["success"] is True
        assert voice_counters()["windowed_suppressed"] == baseline_counter, (
            "первое действие оператора не имеет права быть подавленным"
        )

        # Действие B (оператор, срочная правка) — окно ещё открыто, подавлено
        # ЗАКОННО: это реальное действие оператора.
        res_b = handlers["config.reload"]({"observability": {"log_level": "WARNING"}, "ttl": 1})
        assert res_b["success"] is True
        assert voice_counters()["windowed_suppressed"] == baseline_counter + 1, (
            "действие B обязано было засчитаться подавленным"
        )

        # Свип (origin=ttl-sweeper) возвращает срочную правку B. Эффективный
        # stats.enabled по-прежнему False — если гейта по origin нет, попытка
        # тоже уйдёт в то же самое окно и добавит единицу в ТОТ ЖЕ счётчик.
        clock.advance(2)
        report = sweep_session_ttl(svc)
        assert report is not None

        assert voice_counters()["windowed_suppressed"] == baseline_counter + 1, (
            "истечение TTL (origin=ttl-sweeper) добавило себя в число подавленных "
            "операторских действий — «подавлено» перестало считать ТОЛЬКО оператора"
        )
