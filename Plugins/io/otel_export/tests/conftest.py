# -*- coding: utf-8 -*-
"""Тот же предохранитель, что у набора сервиса: никакой настоящей сети в тестах.

Фикстура не копируется, а ИМПОРТИРУЕТСЯ: две копии одного предохранителя
разъезжаются молча, и узнать об этом можно только по тому, что одна половина
набора однажды ушла в сеть. Разбор, замер и причина — в докстринге
`Services/otel_export/tests/conftest.py`.
"""

from __future__ import annotations

from Services.otel_export.tests.conftest import forbid_real_sdk_in_process  # noqa: F401
