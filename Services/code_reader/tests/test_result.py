# -*- coding: utf-8 -*-
"""Контрактные тесты разбора результата.

Опорные данные — реальный пакет с прибора MV-ID3013PM-06M (прошивка V4.0.2.C):
``QR-30MM;`` = ``51 52 2D 33 30 4D 4D 3B``.
"""

from __future__ import annotations

import socket
import threading

import pytest

from Services.code_reader.core.result import (
    ReadStatus,
    parse_packet,
    split_stream,
)
from Services.code_reader.core.sink import ResultSink

LIVE_PACKET = b"QR-30MM;"


class TestParsePacket:
    def test_живой_пакет_с_прибора(self) -> None:
        result = parse_packet(LIVE_PACKET)
        assert result.payload == "QR-30MM"
        assert result.status is ReadStatus.OK
        assert result.is_good
        assert result.raw == LIVE_PACKET

    def test_no_read_даёт_отличимый_статус(self) -> None:
        assert parse_packet(b"NoRead;").status is ReadStatus.NO_CODE

    def test_два_вида_неудачи_различимы_когда_тексты_разные(self) -> None:
        kwargs = {"no_code_text": "__NOCODE__", "bad_code_text": "__BADCODE__"}
        assert parse_packet(b"__NOCODE__;", **kwargs).status is ReadStatus.NO_CODE
        assert parse_packet(b"__BADCODE__;", **kwargs).status is ReadStatus.BAD_CODE

    def test_одинаковые_тексты_делают_bad_code_недостижимым(self) -> None:
        """Заводское умолчание: оба текста ``NoRead``.

        Это ограничение настройки прибора, а не разбора — «код есть, но не
        читается» в таком виде неотличим от «кода нет».
        """
        kwargs = {"no_code_text": "NoRead", "bad_code_text": "NoRead"}
        assert parse_packet(b"NoRead;", **kwargs).status is ReadStatus.BAD_CODE

    def test_обрамление_другой_конфигурации_снимается(self) -> None:
        assert parse_packet(b"\x02QR-30MM;\x03\r\n").payload == "QR-30MM"

    def test_префикс_снимается(self) -> None:
        assert parse_packet(b">>QR-30MM;", prefix=">>").payload == "QR-30MM"

    def test_код_совпавший_с_текстом_noread_уходит_в_брак(self) -> None:
        """Причина, по которой в тексты NoRead кладут ``__NOCODE__``, а не слово."""
        assert parse_packet(b"NoRead;").status is ReadStatus.NO_CODE

    def test_to_dict_отдаёт_примитивы(self) -> None:
        data = parse_packet(LIVE_PACKET).to_dict()
        assert data == {
            "raw": "51 52 2D 33 30 4D 4D 3B",
            "payload": "QR-30MM",
            "status": "ok",
        }
        assert all(isinstance(value, str) for value in data.values())


class TestSplitStream:
    def test_два_пакета_в_одном_recv(self) -> None:
        packets, tail = split_stream(b"QR-10MM;QR-20MM;")
        assert packets == [b"QR-10MM;", b"QR-20MM;"]
        assert tail == b""

    def test_разорванный_пакет_ждёт_продолжения(self) -> None:
        packets, tail = split_stream(b"QR-10MM;QR-2")
        assert packets == [b"QR-10MM;"]
        assert tail == b"QR-2"

        packets, tail = split_stream(tail + b"0MM;")
        assert packets == [b"QR-20MM;"]
        assert tail == b""

    def test_без_терминатора_всё_уходит_в_остаток(self) -> None:
        assert split_stream(b"QR-10MM", terminator="") == ([], b"QR-10MM")


class TestResultSink:
    def test_принимает_и_разбирает_поток(self) -> None:
        received: list[str] = []
        done = threading.Event()

        def handler(result) -> None:
            received.append(result.payload)
            if len(received) == 2:
                done.set()

        with ResultSink(handler, host="127.0.0.1", port=0) as sink:
            with socket.create_connection(("127.0.0.1", sink.port), timeout=2) as sock:
                sock.sendall(b"QR-10MM;QR-2")
                # Без паузы TCP склеит оба send в один recv, и сборка
                # разорванного пакета останется непроверенной — тест выживал
                # под инъекцией «split_stream теряет остаток».
                threading.Event().wait(0.1)
                sock.sendall(b"0MM;")
                assert done.wait(3), f"получено только {received}"

        assert received == ["QR-10MM", "QR-20MM"]

    def test_повторный_start_запрещён(self) -> None:
        with ResultSink(lambda _: None, host="127.0.0.1", port=0) as sink:
            with pytest.raises(RuntimeError):
                sink.start()

    def test_stop_на_незапущенном_безопасен(self) -> None:
        ResultSink(lambda _: None, host="127.0.0.1", port=0).stop()
