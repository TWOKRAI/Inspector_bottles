# -*- coding: utf-8 -*-
"""TCP-приёмник результатов считывателя ID3000 — печатает то, что реально пришло.

Считыватель в режиме `TCP Client` сам подключается к этому серверу и шлёт
результат каждого чтения. Скрипт печатает каждый пакет как текст И как hex:
терминатор, префикс/суффикс и то, что приходит при «no read», видно только
в hex — в мануале этого нет, формат снимается с прибора.

Настройка в IDMVS → Communication Settings → TCP Client:
    TCP Protocol = вкл
    TCP Dst Addr = IP этого ПК (сейчас 192.168.1.12)
    TCP Dst Port = порт, который слушает этот скрипт

Запуск:
    .venv/Scripts/python.exe Services/code_reader/tools/id3000_tcp_sink.py --port 5000
    .venv/Scripts/python.exe Services/code_reader/tools/id3000_tcp_sink.py --selfcheck
"""

from __future__ import annotations

import argparse
import socket
import socketserver
import sys
import threading
from datetime import datetime

NEWLINE = chr(10)


def printable(payload: bytes) -> str:
    r"""Непечатные байты — как \xNN.

    Считыватели обрамляют результат управляющими символами (STX 0x02, ETX 0x03),
    и сырой такой байт рвёт строку в терминале — а он и есть искомая часть формата.
    """
    out = []
    for byte in payload:
        if byte == 0x0D:
            out.append(r"\r")
        elif byte == 0x0A:
            out.append(r"\n")
        elif 0x20 <= byte < 0x7F:
            out.append(chr(byte))
        else:
            out.append(r"\x" + format(byte, "02X"))
    return "".join(out)


def dump(prefix: str, payload: bytes) -> str:
    """Пакет в двух видах: печатный текст и hex — терминатор виден только во втором."""
    pad = " " * len(prefix)
    hexed = " ".join(format(byte, "02X") for byte in payload)
    head = f"{prefix} {len(payload):>4} байт | {printable(payload)}"
    tail = f"{pad} {'':>4}      | {hexed}"
    return head + NEWLINE + tail


class Handler(socketserver.BaseRequestHandler):
    def handle(self) -> None:
        peer = f"{self.client_address[0]}:{self.client_address[1]}"
        print(f"{NEWLINE}=== подключился {peer} ===", flush=True)
        try:
            while True:
                data = self.request.recv(65536)
                if not data:
                    break
                stamp = datetime.now().strftime("%H:%M:%S.%f")[:-3]
                print(dump(f"[{stamp}]", data), flush=True)
        except ConnectionResetError:
            pass
        finally:
            print(f"=== отключился {peer} ===", flush=True)


class Server(socketserver.ThreadingTCPServer):
    allow_reuse_address = True
    daemon_threads = True


def selfcheck() -> int:
    """Пакет обязан дойти байт в байт, а управляющие символы — не разорвать вывод."""
    captured: list[bytes] = []

    class Capture(Handler):
        def handle(self) -> None:
            captured.append(self.request.recv(65536))

    with Server(("127.0.0.1", 0), Capture) as srv:
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        sent = b"\x02QR-20MM\x03\r\n"
        with socket.create_connection(srv.server_address, timeout=2) as sock:
            sock.sendall(sent)
        for _ in range(200):
            if captured:
                break
            threading.Event().wait(0.01)
        srv.shutdown()

    assert captured, "сервер не принял пакет"
    assert captured[0] == sent, f"пакет искажён: {captured[0]!r} вместо {sent!r}"

    rendered = dump("[test]", sent)
    assert rendered.count(NEWLINE) == 1, "непечатный байт разорвал вывод: " + rendered
    assert r"\x02" in rendered and r"\x03" in rendered, "STX/ETX не экранированы: " + rendered
    assert r"\r\n" in rendered, "терминатор не показан в текстовом виде: " + rendered
    assert "02 51 52" in rendered and "03 0D 0A" in rendered, "hex неполон: " + rendered

    print("selfcheck ok: байты не искажены, управляющие символы экранированы, вывод цел")
    print(rendered)
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument(
        "--host",
        default="0.0.0.0",  # nosec B104 — зонд стенда: прибор приходит из сети линии
        help="интерфейс (по умолчанию все)",
    )
    parser.add_argument("--port", type=int, default=5000, help="порт (по умолчанию %(default)s)")
    parser.add_argument("--selfcheck", action="store_true", help="проверить и выйти")
    args = parser.parse_args()

    if args.selfcheck:
        return selfcheck()

    with Server((args.host, args.port), Handler) as srv:
        print(f"слушаю {args.host}:{args.port} — в IDMVS укажи TCP Dst Addr/Port сюда")
        print("Тишина — это норма: вывод появится, когда камера подключится и прочитает код.")
        print("Ctrl+C для выхода")
        try:
            srv.serve_forever()
        except KeyboardInterrupt:
            print(NEWLINE + "остановлен")
    return 0


if __name__ == "__main__":
    sys.exit(main())
