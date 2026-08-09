"""Тесты PluginContext — создание контекста из IProcessServices.

Проверяет:
- Создание из MockProcessServices
- process_name привязан к services.name
- Менеджеры передаются корректно
- Логирование делегируется services
- with_config() создаёт новый контекст с тем же services
"""

from multiprocess_framework.modules.process_module.plugins.base import PluginContext
from multiprocess_framework.modules.process_module.plugins.testing import MockProcessServices


# ---------------------------------------------------------------------------
# Создание PluginContext из MockProcessServices
# ---------------------------------------------------------------------------


def test_context_from_mock_services():
    """PluginContext(services=MockProcessServices(), config={}) создаётся без ошибок."""
    services = MockProcessServices(name="proc1")
    ctx = PluginContext(services=services, config={})
    assert ctx is not None


def test_context_process_name_from_services():
    """ctx.process_name == services.name."""
    services = MockProcessServices(name="my_process")
    ctx = PluginContext(services=services, config={})
    assert ctx.process_name == "my_process"


def test_context_config_stored():
    """ctx.config хранит переданный конфиг."""
    services = MockProcessServices()
    config = {"alpha": 1, "beta": "x"}
    ctx = PluginContext(services=services, config=config)
    assert ctx.config == config


def test_context_empty_config_by_default():
    """ctx.config == {} при отсутствии явного config."""
    services = MockProcessServices()
    ctx = PluginContext(services=services)
    assert ctx.config == {}


# ---------------------------------------------------------------------------
# Менеджеры
# ---------------------------------------------------------------------------


def test_context_managers_from_services():
    """ctx.worker_manager и ctx.command_manager привязаны к атрибутам services."""
    services = MockProcessServices()
    ctx = PluginContext(services=services, config={})
    assert ctx.worker_manager is services.worker_manager
    assert ctx.command_manager is services.command_manager


def test_context_router_manager_from_services():
    """ctx.router_manager берётся из services.router_manager."""
    from unittest.mock import MagicMock

    mock_router = MagicMock()
    services = MockProcessServices(router_manager=mock_router)
    ctx = PluginContext(services=services, config={})
    assert ctx.router_manager is mock_router


def test_context_memory_manager_from_services():
    """ctx.memory_manager берётся из services.memory_manager."""
    from unittest.mock import MagicMock

    mock_mem = MagicMock()
    services = MockProcessServices(memory_manager=mock_mem)
    ctx = PluginContext(services=services, config={})
    assert ctx.memory_manager is mock_mem


# ---------------------------------------------------------------------------
# Логирование
# ---------------------------------------------------------------------------


def test_context_logging_log_info_from_services():
    """ctx.log_info вызывает services.log_info — запись попадает в services.logs."""
    services = MockProcessServices()
    ctx = PluginContext(services=services, config={})
    ctx.log_info("тест info через контекст")
    assert len(services.logs) == 1
    assert services.logs[0]["level"] == "INFO"
    assert services.logs[0]["msg"] == "тест info через контекст"


def test_context_logging_log_error_from_services():
    """ctx.log_error вызывает services.log_error — запись попадает в services.logs."""
    services = MockProcessServices()
    ctx = PluginContext(services=services, config={})
    ctx.log_error("тест error через контекст")
    assert services.logs[0]["level"] == "ERROR"
    assert services.logs[0]["msg"] == "тест error через контекст"


# ---------------------------------------------------------------------------
# with_config()
# ---------------------------------------------------------------------------


def test_context_with_config_creates_new_context():
    """with_config() возвращает новый объект PluginContext."""
    services = MockProcessServices(name="proc")
    ctx = PluginContext(services=services, config={"old": True})
    new_ctx = ctx.with_config({"new_key": 42})
    assert new_ctx is not ctx


def test_context_with_config_has_new_config():
    """with_config() новый контекст содержит переданный конфиг."""
    services = MockProcessServices(name="proc")
    ctx = PluginContext(services=services, config={"old": True})
    new_ctx = ctx.with_config({"new_key": 42})
    assert new_ctx.config == {"new_key": 42}


def test_context_with_config_same_services():
    """with_config() новый контекст использует те же services (тот же worker_manager)."""
    services = MockProcessServices(name="proc")
    ctx = PluginContext(services=services, config={})
    new_ctx = ctx.with_config({"x": 1})
    # Менеджеры должны указывать на те же объекты
    assert new_ctx.worker_manager is services.worker_manager
    assert new_ctx.command_manager is services.command_manager


def test_context_with_config_process_name_preserved():
    """with_config() сохраняет process_name из services."""
    services = MockProcessServices(name="named_proc")
    ctx = PluginContext(services=services, config={})
    new_ctx = ctx.with_config({"val": 99})
    assert new_ctx.process_name == "named_proc"


# ---------------------------------------------------------------------------
# A2 (Б-2): фасад несёт ВСЮ пятёрку, и это судится протоколом, а не списком
# ---------------------------------------------------------------------------

_LOG_METHODS = ("log_debug", "log_info", "log_warning", "log_error", "log_critical")


def _protocol_log_methods() -> tuple:
    """Имена log-методов, ОБЪЯВЛЕННЫХ протоколом (а не выписанных здесь руками).

    Список берётся из самого ``IProcessServices``, поэтому добавление метода в
    протокол ломает тест ниже — как и требует правило «добавление обязано
    ломать, а не оставлять дыру». Выпиши имена константой — и новый метод
    протокола молча остался бы непроверенным.
    """
    from multiprocess_framework.modules.process_module.plugins.interfaces import IProcessServices

    return tuple(sorted(n for n in dir(IProcessServices) if n.startswith("log_")))


def test_protocol_declares_the_whole_five():
    """Сперва сам протокол: он обязан объявлять пятёрку, а не тройку.

    Б-2 держался на том, что протокол объявлял три метода, ObservableMixin имел
    пять, а фасад штамповал два — три разных списка в трёх местах.
    """
    assert set(_protocol_log_methods()) == set(_LOG_METHODS), (
        f"протокол объявляет {_protocol_log_methods()}, ожидалась пятёрка {_LOG_METHODS}"
    )


def test_real_plugin_context_has_every_log_method_of_the_protocol():
    """РЕАЛЬНЫЙ PluginContext против протокола — не мок против протокола.

    Прежний тест проверял ``log_warning`` на ``MockProcessServices``: мок
    протоколу удовлетворял, а фасад — нет, и дыра жила при зелёных тестах.
    Проверяется тот объект, который получает плагин.
    """
    ctx = PluginContext(services=MockProcessServices())
    missing = [name for name in _protocol_log_methods() if not hasattr(ctx, name)]
    assert not missing, (
        f"PluginContext не несёт объявленные протоколом методы: {missing}. "
        "Штатная деградация плагина превратится в AttributeError"
    )
    for name in _protocol_log_methods():
        assert callable(getattr(ctx, name)), f"ctx.{name} есть, но не вызываем"


def test_with_config_clone_carries_the_whole_five():
    """Производный контекст обязан нести ту же пятёрку (инъекция и-6).

    Прецедент этого же файла: ``state_proxy`` терялся у клона, потому что
    ставился ПОСЛЕ ``__init__``. Пятёрка ставится внутри ``__init__``, но
    свойство всё равно закрепляется тестом, а не рассуждением.
    """
    ctx = PluginContext(services=MockProcessServices())
    clone = ctx.with_config({"a": 1}, plugin_name="probe_plugin")
    missing = [name for name in _protocol_log_methods() if not hasattr(clone, name)]
    assert not missing, f"with_config-клон потерял методы: {missing}"


def test_every_level_reaches_the_services_under_the_plugin_name():
    """Каждый из пяти доезжает до services И несёт имя плагина, а не процесса.

    Проверяется ЭФФЕКТ (запись у сервисов с нужным уровнем и штампом), а не
    наличие имени метода: спай на имени сторожил бы имя, не свойство.
    """
    services = MockProcessServices()
    ctx = PluginContext(services=services).with_config({}, plugin_name="probe_plugin")

    expected = {
        "log_debug": "DEBUG",
        "log_info": "INFO",
        "log_warning": "WARNING",
        "log_error": "ERROR",
        "log_critical": "CRITICAL",
    }
    for name, level in expected.items():
        fn = getattr(ctx, name, None)
        assert callable(fn), f"ctx.{name} отсутствует"
        fn(f"через {name}")

    got = {rec["level"] for rec in services.logs}
    assert got == set(expected.values()), (
        f"до services доехали уровни {sorted(got)}, ожидались {sorted(expected.values())}"
    )
    stamped = [rec for rec in services.logs if rec.get("module") == "probe_plugin"]
    assert len(stamped) == len(expected), (
        f"под именем плагина пришло {len(stamped)} записей из {len(expected)}: "
        f"{[r.get('module') for r in services.logs]}"
    )
