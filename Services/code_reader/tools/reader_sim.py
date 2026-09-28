# -*- coding: utf-8 -*-
"""Симулятор считывателя ID3000 — играет роль прибора в режиме `TCP Client`.

Нужен, чтобы гонять рецепт и плагин без железа: прибор на линии подключается к
нам сам и присылает пакет на каждое срабатывание триггера. Симулятор делает то
же — подключается к приёмнику (`CodeReaderPlugin` или
`tools/id3000_tcp_sink.py`) и шлёт коды в том же формате, что снят с прибора:
``QR-30MM;`` — терминатор ``;``, без CR/LF и без STX/ETX.

Запуск (приёмник должен быть уже поднят):
    .venv/Scripts/python.exe Services/code_reader/tools/reader_sim.py --port 5000
    .venv/Scripts/python.exe Services/code_reader/tools/reader_sim.py \
        --codes QR-10MM,QR-20MM --no-read-every 3 --interval 1.0 --count 9
    .venv/Scripts/python.exe Services/code_reader/tools/reader_sim.py --selfcheck

Чего симулятор НЕ изображает: буфер `Output Result Buffer` (досылку
накопленного после обрыва связи) и тайминги реального декодирования. Проверять
их можно только на приборе.
"""

from __future__ import annotations

import argparse
import socket
import sys
import time

DEFAULT_CODES = ("QR-10MM", "QR-15MM", "QR-20MM", "QR-30MM")


def packets(
    codes: list[str],
    count: int,
    *,
    terminator: str = ";",
    prefix: str = "",
    no_code_text: str = "NoRead",
    no_read_every: int = 0,
) -> list[bytes]:
    """Собрать последовательность пакетов ровно так, как их шлёт прибор.

    Args:
        codes: коды по кругу.
        count: сколько срабатываний изобразить.
        no_read_every: каждое N-ное срабатывание — «кода нет» (0 = никогда).
    """
    out: list[bytes] = []
    for i in range(count):
        if no_read_every and (i + 1) % no_read_every == 0:
            payload = no_code_text
        else:
            payload = codes[i % len(codes)]
        out.append(f"{prefix}{payload}{terminator}".encode("utf-8"))
    return out


def run(
    host: str,
    port: int,
    payloads: list[bytes],
    interval: float,
    *,
    verbose: bool = True,
) -> int:
    """Подключиться к приёмнику и отправить пакеты с заданным интервалом."""
    try:
        conn = socket.create_connection((host, port), timeout=5.0)
    except OSError as exc:
        print(f"не подключиться к {host}:{port}: {exc}")
        print("приёмник не поднят? проверь, что рецепт запущен или sink слушает порт")
        return 1
    with conn:
        for i, packet in enumerate(payloads, 1):
            conn.sendall(packet)
            if verbose:
                print(f"[{i}/{len(payloads)}] -> {packet!r}")
            if i < len(payloads):
                time.sleep(interval)
    return 0


def selfcheck() -> int:
    """Проверить сборку пакетов и сквозную отправку на локальный сокет."""
    assert packets(["A", "B"], 3) == [b"A;", b"B;", b"A;"]
    assert packets(["A"], 3, no_read_every=2) == [b"A;", b"NoRead;", b"A;"]
    assert packets(["A"], 1, prefix="<", terminator=">") == [b"<A>"]

    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server.bind(("127.0.0.1", 0))
    server.listen(1)
    bound_port = server.getsockname()[1]
    import threading

    received: list[bytes] = []

    def accept_once() -> None:
        conn, _ = server.accept()
        with conn:
            conn.settimeout(2.0)
            while True:
                chunk = conn.recv(4096)
                if not chunk:
                    break
                received.append(chunk)

    thread = threading.Thread(target=accept_once, daemon=True)
    thread.start()
    code = run("127.0.0.1", bound_port, packets(["Z"], 2), 0.05, verbose=False)
    thread.join(3.0)
    server.close()
    assert code == 0, code
    assert b"".join(received) == b"Z;Z;", received
    print("selfcheck OK")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--host", default="127.0.0.1", help="адрес приёмника")
    parser.add_argument("--port", type=int, default=5000, help="порт приёмника (%(default)s)")
    parser.add_argument(
        "--codes",
        default=",".join(DEFAULT_CODES),
        help="коды через запятую (по умолчанию %(default)s)",
    )
    parser.add_argument("--count", type=int, default=8, help="сколько срабатываний (%(default)s)")
    parser.add_argument("--interval", type=float, default=1.0, help="пауза между ними, с")
    parser.add_argument("--terminator", default=";", help="`Output Stop Text` прибора")
    parser.add_argument("--prefix", default="", help="`Output Start Text` прибора")
    parser.add_argument("--no-read-text", default="NoRead", help="`Output NoRead Text`")
    parser.add_argument(
        "--no-read-every",
        type=int,
        default=0,
        help="каждое N-ное срабатывание — «кода нет» (0 = никогда)",
    )
    parser.add_argument("--selfcheck", action="store_true", help="проверить и выйти")
    args = parser.parse_args()

    if args.selfcheck:
        return selfcheck()

    payloads = packets(
        [c for c in args.codes.split(",") if c],
        args.count,
        terminator=args.terminator,
        prefix=args.prefix,
        no_code_text=args.no_read_text,
        no_read_every=args.no_read_every,
    )
    return run(args.host, args.port, payloads, args.interval)


if __name__ == "__main__":
    sys.exit(main())
