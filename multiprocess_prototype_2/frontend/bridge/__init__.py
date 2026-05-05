"""bridge — пакет IPC-мостов: DataReceiverBridge и CommandSender."""
# Реэкспорт DataReceiverBridge для обратной совместимости с process.py и тестами,
# которые импортируют: from multiprocess_prototype_2.frontend.bridge import DataReceiverBridge
from ..bridge_impl import DataReceiverBridge  # noqa: F401

__all__ = ["DataReceiverBridge"]
