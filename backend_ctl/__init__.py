# -*- coding: utf-8 -*-
"""
backend_ctl — тонкий внешний driver управления бэкендом по TCP (dev-инструмент).

«GUI по сокету»: подключается к SocketChannel хоста (ProcessManager) и шлёт те же
router-сообщения, что GUI через CommandSender, плюс reply-поля (request_id/reply_to)
для request-response (P0.5). Без бизнес-логики — только транспорт + матч ответов по id.

Граница ровно Claude↔driver: внутрь системы и обратно всё идёт чистым RouterManager.
Гейт на стороне хоста: BACKEND_CTL=1 + localhost-bind. Кадры/SHM через сокет НЕ гоняем.
"""

from .driver import (
    BackendDriver,
    Capabilities,
    MemoryStats,
    ProcessCapabilities,
    QueueDepths,
    RouterStats,
    WorkerStatus,
)

__all__ = [
    "BackendDriver",
    "Capabilities",
    "ProcessCapabilities",
    "RouterStats",
    "QueueDepths",
    "MemoryStats",
    "WorkerStatus",
]
