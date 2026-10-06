# -*- coding: utf-8 -*-
"""
Pytest: логи по умолчанию не пишутся в дерево исходников modules/.

Каталог задаётся через MULTIPROCESS_LOG_DIR (см. logger_module.core.log_paths).
"""

from __future__ import annotations

import os
import threading

import pytest


def pytest_configure(config: pytest.Config) -> None:
    """Прогон на ``spawn`` — как прод (Атлас 0.8b, группа A).

    Тесты строят процессы и ``multiprocessing``-примитивы, не проходя через
    ``spawner.launch_orchestrator``; без явного метода на Linux первый же ``Event()`` фиксирует
    ``fork``, и ``spawn``-процесс с таким объектом падает («SemLock … fork context»).
    """
    from .process_manager_module.platforms import StubPlatformAdapter

    StubPlatformAdapter().setup_multiprocessing()


# ---------------------------------------------------------------------------
# Политика памяти GUI (T1): сборкой gc владеет главный поток, граница каждого теста
# ---------------------------------------------------------------------------
# Те же имена и тела — в корневом conftest.py и в multiprocess_framework/modules/conftest.py
# (в modules/ эти перекрывают корневые; из modules/ корень не грузится). Спека —
# plans/2026-10-03_lifecycle-owner-scope/task-T1.md, «Точки включения» 2–3.


@pytest.fixture(scope="session", autouse=True)
def _gui_memory_policy(pytestconfig: pytest.Config):
    """Сессия: автосборка выключена, сборка — тиком QTimer и на границах тестов."""
    from multiprocess_framework.modules.frontend_module.core.qt_gc_policy import (
        gui_memory_policy,
        install_gui_memory_policy,
    )

    pre = gui_memory_policy()
    policy = pre or install_gui_memory_policy(None, freeze=True, freeze_after_s=0.0, observe=True)
    yield policy
    pytestconfig.gc_policy_stats = policy.stats()
    if pre is None:
        policy.uninstall()


@pytest.fixture(autouse=True)
def _gui_memory_boundary(_gui_memory_policy):
    """Граница теста: автосборку не оставили включённой; мусор теста собран на главном потоке.

    Определена ПЕРВОЙ из function-autouse: её teardown идёт последним.
    """
    yield
    policy = _gui_memory_policy
    violated = policy.enforce()
    policy.collect_now()
    if violated:
        pytest.fail("Тест оставил автосборку gc включённой: восстановите прежнее состояние через paused_gc()")


@pytest.fixture(autouse=True)
def _reset_early_log_buffer() -> None:
    """Ф6.4а: буфер ранних записей — ПРОЦЕССНОЕ состояние, и оно течёт между тестами.

    В проде это ровно то, что нужно: одна жизнь процесса — один старт, один
    слив. В прогоне процесс общий на тысячи тестов, поэтому запись, сделанная
    без менеджера в одном тесте, сливалась в первый же менеджер СЛЕДУЮЩЕГО и
    становилась там первой строкой файла (поймано тремя красными в
    ``test_fallback_handle`` и ``test_source_stamp_artifact``).

    Сброс до и после: «до» защищает тест от предшественника, «после» — от
    самого себя, если он упал на середине.
    """
    from .logger_module.adapters.std_facade import reset_early_buffer

    reset_early_buffer()
    yield
    reset_early_buffer()


@pytest.fixture(autouse=True)
def _reset_windowed_voice_holder() -> None:
    """Task 2.12: окна голосов — ПРОЦЕССНОЕ состояние того же класса, что буфер выше.

    С задачи 2.12 предупреждение о смене смысла ``stats.enabled`` (ADR-PM-046)
    дросселируется окном по ключу на процессном держателе
    (``windowed_voice._PROCESS_VOICES``). В проде это ровно то, что нужно: одна
    жизнь процесса — одно окно на ключ. В прогоне процесс общий, и окно, занятое
    одним тестом, глушит голос у следующего.

    **Ставится не «на всякий случай»: пойманы две поломки, и вторая опаснее.**
    ``statistics_module::test_c7_*`` краснел ДАЖЕ в изоляции своего файла (соседи
    по файлу съедали окно раньше). А пара
    ``test_f2_task29_fingerprint_probe::TestTheProbeDoesNotSpeakForTheOperator``
    перестала РАЗЛИЧАТЬ: её положительная половина покраснела, а отрицательная
    («зонд молчит») осталась ЗЕЛЁНОЙ — голос был подавлен чужим окном, и тест
    проходил, не проверив ничего. Красное видно, вакуумное зелёное — нет.

    Четыре теста, ассертящих голос, владеют окном ЯВНО и продолжают владеть:
    тест про окно обязан владеть окном так же, как тест про время — часами. Эта
    фикстура — второй рубеж для тех, кто про дроссель не знает: сегодня семь
    файлов зовут ``stats.enabled: false`` мимоходом, не проверяя голос, и любой
    из них может стать чужим окном для следующего.

    Радиус тот же, что у ``_reset_early_log_buffer``: одно процессное состояние
    плоскости наблюдаемости, сброс до и после. Боевых пользователей процессного
    держателя ровно один ключ (сверено грепом), так что фикстура ничего, кроме
    него, не двигает.

    **Оговорка о нагрузке, без которой докстринг врёт (находка ревью).** Обе
    поломки выше описаны как ИЗМЕРЕННЫЕ — и они были измерены, но ДО этой
    фикстуры: она пришла позже явных владельцев окна в четырёх файлах. При
    нынешнем дереве свойство держат явные владельцы ПООДИНОЧКЕ, и обнуление
    тела этой фикстуры дефекта не открывает: ревьюер прогнал с пустым телом —
    ``process_module`` + ``statistics_module`` **3208 passed, 1 xfailed**,
    ``channel_routing`` + ``logger_module`` + ``shared_resources``
    **1432 passed, 2 skipped**. То есть сегодня она — второй рубеж, а не
    единственный; её работа начнётся с первым тестом, который позовёт
    ``stats.enabled: false`` мимоходом и не будет знать про окно.
    """
    from .logger_module.core.windowed_voice import reset_process_voices

    reset_process_voices()
    yield
    reset_process_voices()


@pytest.fixture(autouse=True)
def _reset_logger_manager_singleton() -> None:
    """Ф6.х.1: ``LoggerManager._instance`` — второе процессное состояние, текущее между тестами.

    Тест, забывший ``shutdown()``, оставлял живой менеджер (его потоки, каналы и
    tap'ы) всем последующим: измерено на ``test_send_error_visibility`` —
    перестановка одного файла меняла время прогона 16.8 с ↔ 88–95 с, из них
    72 с приходились на один чужой тест. Снимаем через ``shutdown()``: голое
    ``_instance = None`` не бампит эпоху наблюдаемости, и закэшированные фасады
    в ``std_facade._CACHE`` остались бы связаны с мёртвым менеджером.

    Определена ПОСЛЕ ``_reset_early_log_buffer`` намеренно: teardown идёт в
    обратном порядке, поэтому сперва снимается менеджер, потом чистится буфер —
    записи, набуференные самим shutdown-переходом, не переживают тест.
    """
    from .logger_module.core.logger_manager import LoggerManager

    def _shutdown_leftover() -> None:
        manager = LoggerManager._instance
        if manager is not None:
            manager.shutdown()

    _shutdown_leftover()
    yield
    _shutdown_leftover()


#: Долгоживущие стенды ПО РЕШЕНИЮ: префикс nodeid → причина. Пусто не случайно:
#: сегодня ни один тест не имеет права держать flusher дольше себя. Запись без
#: причины не считается (образец дисциплины — _RUNNERLESS_BY_DECISION в 4.0).
_FLUSHER_LONG_LIVED_ALLOWED: dict[str, str] = {}


@pytest.fixture(autouse=True)
def _no_leaked_state_flushers(request: pytest.FixtureRequest):
    """Третье текущее процессное состояние: daemon-flusher'ы StateStoreManager.

    ``initialize()`` запускает поток ``StateCoalesceFlusher`` (тик 0.12 с), и
    гасит его только ``shutdown()``. Тест, забывший пару, оставляет поток
    ЖИВЫМ до конца прогона: поток держит диспетчер сильной ссылкой (bound
    method в target), поэтому стенд не собирается GC и не финализируется —
    он бессмертен. Замерено пробой 2026-08-12 на корневом гейте: 18 утёкших
    потоков из 4 файлов state_store_module/tests — ~150 пробуждений в секунду
    фонового шума всему остатку прогона; все 18 фигурируют в каждом
    faulthandler-дампе access violation (там они соседи детонации, не причина —
    причина закрыта отдельно, MPLBACKEND в корневом conftest).

    Сравнение по МНОЖЕСТВУ потоков до/после, не по числу: чужая утечка,
    пережившая свой тест, не должна красить соседей — краснеет только тест,
    ДОБАВИВШИЙ живой поток. Утёкший поток гасится best-effort до fail, чтобы
    один забытый shutdown() не шумел остатку прогона.
    """
    marker = "StateCoalesceFlusher"
    before = {t.ident for t in threading.enumerate() if t.name == marker and t.is_alive()}
    yield
    leaked = [t for t in threading.enumerate() if t.name == marker and t.is_alive() and t.ident not in before]
    if not leaked:
        return
    for prefix, _reason in _FLUSHER_LONG_LIVED_ALLOWED.items():
        if request.node.nodeid.startswith(prefix):
            return
    for t in leaked:
        owner = getattr(getattr(t, "_target", None), "__self__", None)
        if owner is not None and hasattr(owner, "stop_flusher"):
            owner.stop_flusher(timeout=1.0)
    pytest.fail(
        f"Тест оставил {len(leaked)} живой(ых) поток(ов) {marker}: "
        "StateStoreManager.initialize() обязан закрываться shutdown() в teardown "
        "(try/finally или фикстура с yield). Долгоживущий стенд по решению — "
        "запись в _FLUSHER_LONG_LIVED_ALLOWED с причиной."
    )


@pytest.fixture(scope="session", autouse=True)
def _multiprocess_framework_log_dir(tmp_path_factory: pytest.TempPathFactory) -> None:
    d = tmp_path_factory.mktemp("multiprocess_logs")
    previous = os.environ.get("MULTIPROCESS_LOG_DIR")
    os.environ["MULTIPROCESS_LOG_DIR"] = str(d)
    yield
    if previous is None:
        os.environ.pop("MULTIPROCESS_LOG_DIR", None)
    else:
        os.environ["MULTIPROCESS_LOG_DIR"] = previous


def pytest_terminal_summary(terminalreporter, exitstatus: int, config: pytest.Config) -> None:
    """Одна строка сводки политики памяти GUI (T1): нарушения, чужие сборки, худшая пауза."""
    stats = getattr(config, "gc_policy_stats", None)
    if not stats:
        return
    terminalreporter.write_line(
        f"gc-policy: collections={stats['collections']} collected_objects={stats['collected_objects']} "
        f"enabled_violations={stats['enabled_violations']} foreign_collections={stats['foreign_collections']} "
        f"max_pause_ms={stats['max_pause_ms']:.3f} total_pause_ms={stats['total_pause_ms']:.1f}"
    )
