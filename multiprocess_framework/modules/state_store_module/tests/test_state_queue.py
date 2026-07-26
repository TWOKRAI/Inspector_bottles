"""Тесты очереди state.changed — ЕДИНСТВЕННЫЙ путь (Ф6.2, флаг FW_STATE_QUEUE удалён).

История: Task 1.2 ввёл выбор очереди под флагом (OFF — never-drop ``system`` как раньше,
ON — ``state`` с drop_oldest), Ф6.1 флипнул дефолт, Ф6.2 **удалила флаг вместе с OFF-веткой**.
Переключателя больше нет: конверт всегда несёт ``queue_type == "state"``, поэтому burst
``state.set`` не топит system-почту команд подписчика (до этого gui переставал отвечать
вовсе — см. `plans/truth-holes-closure.md` Фаза 1). Ф6.3 сняла и второй переключатель
(``FW_STATE_COALESCE``), поэтому конверт здесь забирается после явного ``_flush_once``.

Плечо OFF удалено ОСОЗНАННО, а не «забыто»: тестировать снятую ветку — значит держать её
живой в тестах и создавать иллюзию, что путь поддерживается.
"""

from __future__ import annotations

from ..core.delta import MISSING, Delta
from ..core.subscription_manager import SubscriptionManager
from ..manager.delta_dispatcher import DeltaDispatcher


class _CapturingRouter:
    """Мини-роутер: захватывает send_async-сообщения."""

    def __init__(self) -> None:
        self.sent: list = []

    def send_async(self, msg, priority: str = "normal") -> None:
        self.sent.append(msg)


def _dispatch_one():
    """Разослать одну дельту подписчику 'gui', вернуть захваченный конверт."""
    subs = SubscriptionManager()
    router = _CapturingRouter()
    disp = DeltaDispatcher(subs, router=router, sender_name="StateStore")
    subs.subscribe("processes.**", "gui")
    disp.dispatch_single(Delta(path="processes.cam.n", old_value=MISSING, new_value=1, source="s", revision=1))
    disp._flush_once()  # тик flusher'а заменён детерминированным вызовом
    assert len(router.sent) == 1
    return router.sent[0]


def test_routes_to_state_queue() -> None:
    """state.changed → queue_type "state" (drop_oldest, мимо never-drop system-почты)."""
    msg = _dispatch_one()
    assert msg["command"] == "state.changed"
    assert msg["queue_type"] == "state"


def test_no_delivery_switches_left() -> None:
    """Регресс-якорь снятия лесов: у DeltaDispatcher НЕТ переключателей доставки.

    Ф6.2 сняла выбор очереди (``FW_STATE_QUEUE``), Ф6.3 — выбор режима отправки
    (``FW_STATE_COALESCE``, ctor-параметр ``coalesce``). Если любой вернётся — тест
    упадёт и напомнит, что dark-launch закрывается удалением ветки, а не вечным
    флагом (установка владельца, Фаза 6).
    """
    import inspect

    params = inspect.signature(DeltaDispatcher.__init__).parameters
    assert "state_queue" not in params
    assert "coalesce" not in params

    from multiprocess_framework.modules.config_module import feature_flags

    assert "FW_STATE_QUEUE" not in feature_flags.FLAGS
    assert "FW_STATE_COALESCE" not in feature_flags.FLAGS


def test_default_queues_include_state() -> None:
    """Аддитивная раскладка: у процесса всегда есть очередь "state" (maxsize 8),
    из которой возникает канал {proc}_state и его приём."""
    from multiprocess_framework.modules.process_module.configs.process_launch_config import DEFAULT_QUEUES

    assert "state" in DEFAULT_QUEUES
    assert DEFAULT_QUEUES["state"]["maxsize"] == 8


def test_custom_queues_still_get_state(monkeypatch) -> None:
    """Кастомный ``queues`` НЕ может отменить обязательную очередь "state".

    Предмерж-ревью Ф6: после удаления FW_STATE_QUEUE выбора транспорта нет, поэтому
    процесс без очереди "state" молча не получал бы НИ ОДНОЙ дельты (у отправителя —
    warning «Queue 'state' not found», у получателя — тишина и вечный стейл).
    Пользовательские глубины при этом сохраняются.
    """
    from multiprocess_framework.modules.process_module.configs.process_launch_config import (
        DEFAULT_QUEUES,
        ProcessLaunchConfig,
    )

    cfg = ProcessLaunchConfig(name="p", class_path="m.C", queues={"system": {"maxsize": 7}})
    _name, proc_dict = cfg.build()
    queues = proc_dict["queues"]
    assert queues["system"]["maxsize"] == 7  # своё уважено
    assert queues["state"] == DEFAULT_QUEUES["state"]  # обязательное добавлено
