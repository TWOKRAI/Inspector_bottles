# -*- coding: utf-8 -*-
"""Отчёт о дрейфе контракта не должен умирать от кодировки консоли.

Регресс 2026-07-21: ``python -m backend_ctl.dump_capabilities --check`` находил
дрейф и падал ``UnicodeEncodeError`` на символе ``≥`` при печати дифа. Консоль
Windows по умолчанию cp1251 — кириллицу она кодирует, а математические знаки и
стрелки из описаний команд нет. Итог: инструмент ломался ровно в тот момент,
когда ему было что сообщить, и CI видел краш вместо диагноза.

Лечение — на границе вывода (``reconfigure(errors="replace")``), а не вычищением
символов из описаний: потерять глиф лучше, чем потерять отчёт.
"""

from __future__ import annotations

import io
import sys

from backend_ctl.dump_capabilities import _make_output_encoding_safe


class _Cp1251Stream(io.TextIOWrapper):
    """Поток с cp1251, как консоль Windows по умолчанию."""

    def __init__(self) -> None:
        super().__init__(io.BytesIO(), encoding="cp1251", errors="strict")


def _reconfigurable_cp1251():
    return io.TextIOWrapper(io.BytesIO(), encoding="cp1251", errors="strict")


class TestOutputEncodingSafety:
    def test_cp1251_stream_cannot_print_contract_chars_before_fix(self):
        """Фиксируем сам механизм отказа — иначе тест ниже ничего не доказывает."""
        stream = _reconfigurable_cp1251()
        try:
            stream.write("описание ≥ порога")
            stream.flush()
        except UnicodeEncodeError:
            pass
        else:  # pragma: no cover — сработает, если Python сменит поведение cp1251
            raise AssertionError("ожидался UnicodeEncodeError на '≥' в cp1251")

    def test_after_fix_contract_chars_are_printable(self, monkeypatch):
        stream = _reconfigurable_cp1251()
        monkeypatch.setattr(sys, "stdout", stream)
        monkeypatch.setattr(sys, "stderr", _reconfigurable_cp1251())

        _make_output_encoding_safe()

        # Ровно те символы, на которых падал реальный прогон.
        print("diff: описание ≥ порога, поток → приёмник")
        sys.stdout.flush()

    def test_survives_stream_without_reconfigure(self, monkeypatch):
        """Поток мог быть подменён (pytest capture, пайп) — тогда просто не трогаем."""

        class _NoReconfigure:
            encoding = "cp1251"

            def write(self, _s: str) -> int:
                return 0

            def flush(self) -> None:
                return None

        monkeypatch.setattr(sys, "stdout", _NoReconfigure())
        monkeypatch.setattr(sys, "stderr", _NoReconfigure())

        _make_output_encoding_safe()  # не должно бросить
