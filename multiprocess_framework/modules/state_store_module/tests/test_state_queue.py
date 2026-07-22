"""Тесты выбора очереди state.changed (FW_STATE_QUEUE, Task 1.2).

Матрица:
  - OFF (default): конверт несёт ``queue_type == "system"`` — бит-в-бит как раньше.
  - ON (``state_queue=True``): ``queue_type == "state"`` — доставка в ``{proc}_state``
    (drop_oldest), мимо never-drop system-почты команд.
  - Ортогональность коалесцированию: queue_type определяется отдельным флагом и не
    зависит от режима буферизации (проверка на обеих комбинациях ``coalesce``).
  - Дефолтная раскладка очередей содержит "state" (аддитивно, создаётся всегда).

Флаг разрешается в ctor DeltaDispatcher (ctor > env > default); тесты задают режим
явным аргументом ``state_queue=``.
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


def _dispatch_one(state_queue: bool | None, coalesce: bool | None = False):
    """Разослать одну дельту подписчику 'gui', вернуть захваченный конверт."""
    subs = SubscriptionManager()
    router = _CapturingRouter()
    disp = DeltaDispatcher(subs, router=router, sender_name="StateStore", coalesce=coalesce, state_queue=state_queue)
    subs.subscribe("processes.**", "gui")
    disp.dispatch_single(Delta(path="processes.cam.n", old_value=MISSING, new_value=1, source="s", revision=1))
    if coalesce:
        disp._flush_once()
    assert len(router.sent) == 1
    return router.sent[0]


def test_off_routes_to_system() -> None:
    """OFF (default): state.changed → queue_type "system" (бит-в-бит)."""
    msg = _dispatch_one(state_queue=False)
    assert msg["command"] == "state.changed"
    assert msg["queue_type"] == "system"


def test_on_routes_to_state() -> None:
    """ON: state.changed → queue_type "state" (drop_oldest, мимо system-почты)."""
    msg = _dispatch_one(state_queue=True)
    assert msg["queue_type"] == "state"


def test_queue_type_independent_of_coalescing() -> None:
    """queue_type определяется FW_STATE_QUEUE отдельно от коалесцирования:
    "state" сохраняется и при включённой буферизации."""
    assert _dispatch_one(state_queue=True, coalesce=False)["queue_type"] == "state"
    assert _dispatch_one(state_queue=True, coalesce=True)["queue_type"] == "state"
    assert _dispatch_one(state_queue=False, coalesce=True)["queue_type"] == "system"


def test_default_queues_include_state() -> None:
    """Аддитивная раскладка: у процесса всегда есть очередь "state" (maxsize 8),
    из которой возникает канал {proc}_state и его приём."""
    from multiprocess_framework.modules.process_module.configs.process_launch_config import DEFAULT_QUEUES

    assert "state" in DEFAULT_QUEUES
    assert DEFAULT_QUEUES["state"]["maxsize"] == 8
