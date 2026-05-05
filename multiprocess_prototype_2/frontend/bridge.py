"""DataReceiverBridge — мост worker thread → Qt signals → main thread."""
from PySide6.QtCore import QObject, Signal


class DataReceiverBridge(QObject):
    """Классифицирует IPC-сообщения и emit'ит Qt signals для main thread.

    Используется из worker thread data_receiver.
    Qt гарантирует queued connection для cross-thread signals.
    """

    frame_received = Signal(dict)
    state_updated = Signal(dict)
    command_response = Signal(dict)

    def dispatch(self, msg_dict: dict) -> None:
        """Классифицировать сообщение по data_type и emit соответствующий signal."""
        data_type = msg_dict.get("data_type", "")
        if data_type in ("frame_ready", "frame"):
            self.frame_received.emit(msg_dict)
        elif data_type in ("status", "state_changed", "fps_update"):
            self.state_updated.emit(msg_dict)
        else:
            self.command_response.emit(msg_dict)
