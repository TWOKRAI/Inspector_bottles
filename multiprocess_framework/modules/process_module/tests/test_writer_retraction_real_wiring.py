# -*- coding: utf-8 -*-
"""Провод снятия на НАСТОЯЩИХ объектах: heartbeat → StateProxy → StateStoreManager.

Зачем отдельный файл. Приёмка (``test_f2_acceptance_writer_retraction.py``) и
авторские hazard'ы (``test_writer_retraction_hazards.py``) гоняют шаг снятия
через ДУБЛЬ прокси (``_Proxy``). Это правильно для своих задач — дубль делает
дерево наблюдаемым построчно, — но означает, что настоящий
:class:`StateProxy` в дороге снятия не участвует НИ В ОДНОМ тесте.

Измерено инъекциями 2026-08-23: сломай настоящему ``StateProxy.delete`` путь
(шли родителя вместо переданного) или сделай его молчаливым ``return`` — и весь
приёмочный файл остаётся ЗЕЛЁНЫМ, потому что он этого кода не касается. Ровно
тот случай, про который в правилах проекта сказано: где командная поверхность
проверяется дублями, нужен ОДИН тест, сшивающий настоящие объекты, иначе
переименование продакшн-атрибута оставляет все тесты зелёными.

Здесь такой тест ровно один, и он намеренно узкий: не дублирует ни приёмку, ни
hazard'ы, а сторожит СТЫК — что шаг тика адресует настоящему прокси тот самый
путь, который настоящий стор понимает как поддерево писателя.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from multiprocess_framework.modules.process_module.heartbeat.process_heartbeat import ProcessHeartbeat
from multiprocess_framework.modules.process_module.heartbeat.telemetry import (
    PLUGIN_LEVELS_ATTR,
    PluginLevels,
)
from multiprocess_framework.modules.state_store_module.manager.state_store_manager import StateStoreManager
from multiprocess_framework.modules.state_store_module.proxy.state_proxy import StateProxy

ПРОЦЕСС = "camera_0"
ПИСАТЕЛЬ = "capture"
СОСЕД = "capture2"

#: Маркер отсутствия: ``store.get`` на удалённом пути БРОСАЕТ KeyError, а ``None``
#: — законное значение листа. Путать одно с другим — тот самый дефект, который Ф2
#: убирает, поэтому в тесте он не выразим.
ОТСУТСТВУЕТ = object()


class _DirectRouter:
    """Роутер, который отдаёт сообщение обработчику менеджера сразу.

    Не мок поведения прокси: прокси здесь НАСТОЯЩИЙ и сам собирает сообщение.
    Заменена только асинхронность доставки — иначе тест зависел бы от тика
    очереди, а проверяет он адресацию, а не расписание.
    """

    def __init__(self) -> None:
        self.manager: StateStoreManager | None = None
        self.sent: list[dict] = []

    def send_async(self, msg, priority: str = "normal") -> None:
        self.sent.append(msg)
        self._dispatch(msg)

    def send(self, msg) -> dict:
        self.sent.append(msg)
        self._dispatch(msg)
        return {"status": "success"}

    def register_message_handler(self, key, handler, **kwargs) -> None:  # noqa: D102
        pass

    def _dispatch(self, msg: dict) -> None:
        if self.manager is None:
            return
        команда = msg.get("command", "")
        if команда == "state.set":
            self.manager.handle_state_set(msg)
        elif команда == "state.merge":
            self.manager.handle_state_merge(msg)
        elif команда == "state.delete":
            self.manager.handle_state_delete(msg)


@pytest.fixture
def стенд():
    """Настоящие прокси и менеджер, соединённые прямым роутером."""
    router = _DirectRouter()
    mgr = StateStoreManager(router=router)
    mgr.initialize()
    router.manager = mgr
    proxy = StateProxy(ПРОЦЕСС, router=router)
    yield proxy, mgr, router
    mgr.shutdown()


def _heartbeat_с_портом(proxy: StateProxy, port: PluginLevels):
    """Минимальный носитель ``_services`` для шага снятия.

    Полный ``ProcessHeartbeat`` поднимать не за чем: проверяется адресация шага,
    а не его запуск из ``_loop`` — провод ``_loop`` → ``_publish_telemetry_to_tree``
    сторожат соседние тесты.
    """
    services = SimpleNamespace(
        name=ПРОЦЕСС,
        _state_proxy=proxy,
        log_info=lambda *a, **k: None,
        log_debug=lambda *a, **k: None,
    )
    setattr(services, PLUGIN_LEVELS_ATTR, port)
    return SimpleNamespace(_services=services)


class TestTheRealProxyIsActuallyWired:
    """Стык «шаг тика → настоящий прокси → настоящий стор»."""

    def test_departed_writer_subtree_leaves_the_real_tree(self, стенд):
        proxy, mgr, router = стенд
        корень = f"processes.{ПРОЦЕСС}.state.plugins.{ПИСАТЕЛЬ}"
        сосед = f"processes.{ПРОЦЕСС}.state.plugins.{СОСЕД}"

        proxy.set(корень + ".fps", 21.3)
        proxy.set(корень + ".frame_count", 5)
        proxy.set(сосед + ".fps", 852.3)

        # Якорь существования: до снятия в НАСТОЯЩЕМ сторе лежат литералы.
        assert mgr.store.get(корень + ".fps") == 21.3
        assert mgr.store.get(корень + ".frame_count") == 5
        assert mgr.store.get(сосед + ".fps") == 852.3

        port = PluginLevels()
        port.publish("fps", 21.3, ПИСАТЕЛЬ)
        port.retract(ПИСАТЕЛЬ)

        ProcessHeartbeat._delete_departed_subtrees(_heartbeat_с_портом(proxy, port), proxy)

        assert mgr.store.get(корень + ".fps", ОТСУТСТВУЕТ) is ОТСУТСТВУЕТ
        assert mgr.store.get(корень + ".frame_count", ОТСУТСТВУЕТ) is ОТСУТСТВУЕТ
        # Пара-контроль: сосед с общим текстовым префиксом не задет.
        assert mgr.store.get(сосед + ".fps") == 852.3

    def test_the_step_emits_a_state_delete_addressed_to_the_writer_subtree(self, стенд):
        """Адресация: путь на проводе — поддерево писателя, не лист и не родитель."""
        proxy, mgr, router = стенд

        port = PluginLevels()
        port.publish("fps", 21.3, ПИСАТЕЛЬ)
        port.retract(ПИСАТЕЛЬ)

        ProcessHeartbeat._delete_departed_subtrees(_heartbeat_с_портом(proxy, port), proxy)

        удаления = [m for m in router.sent if m.get("command") == "state.delete"]
        assert len(удаления) == 1, f"ровно одно снятие на одного ушедшего: {удаления}"
        assert удаления[0]["data"]["path"] == f"processes.{ПРОЦЕСС}.state.plugins.{ПИСАТЕЛЬ}"

    def test_a_living_writer_produces_no_delete_on_the_wire(self, стенд):
        """Пара-контроль к предыдущему: без ухода снятий на проводе нет вовсе.

        Без него «одно снятие» доказывало бы только что что-то отправлено, а не
        что отправлено по поводу ухода.
        """
        proxy, mgr, router = стенд

        port = PluginLevels()
        port.publish("fps", 21.3, ПИСАТЕЛЬ)

        ProcessHeartbeat._delete_departed_subtrees(_heartbeat_с_портом(proxy, port), proxy)

        assert [m for m in router.sent if m.get("command") == "state.delete"] == []
