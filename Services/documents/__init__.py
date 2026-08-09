# -*- coding: utf-8 -*-
"""Плоскость документов: аудит смен наблюдаемости и вердикты о качестве детали.

Публичный API — только то, что перечислено в ``__all__``. Внешние модули импортируют
отсюда; ``schema``/``store`` — детали реализации этого пакета.
"""

from __future__ import annotations

from .interfaces import KIND_AUDIT, KIND_VERDICT, IDocumentSink, IDocumentStore
from .store import DocumentStore
from .wiring import make_document_sink

__all__ = [
    "KIND_AUDIT",
    "KIND_VERDICT",
    "IDocumentSink",
    "IDocumentStore",
    "DocumentStore",
    "make_document_sink",
]
