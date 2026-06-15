"""Определение локальных IP-адресов ПК в LAN — для ссылки, которую открывают
на телефоне.

На ПК часто несколько интерфейсов (WiFi, Ethernet, VPN). Телефон обычно в WiFi,
поэтому возвращаем СПИСОК кандидатов с приоритетом: 192.168.* (типичный WiFi) →
172.16-31.* → прочее → 10.* (часто VPN) → 169.254.* (APIPA, нет сети). GUI
показывает все, пользователь выбирает подходящий. Трюк с UDP-сокетом мог бы
вернуть VPN-интерфейс (маршрут в интернет), поэтому одного адреса мало.
"""

from __future__ import annotations

import socket


def _route_ip() -> str | None:
    """IP интерфейса с маршрутом наружу (UDP connect, без реальной отправки)."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        sock.connect(("8.8.8.8", 80))
        return sock.getsockname()[0]
    except Exception:
        return None
    finally:
        sock.close()


def _hostname_ips() -> list[str]:
    """Все IPv4 хоста (по имени машины)."""
    try:
        return [info[4][0] for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET)]
    except Exception:
        return []


def _priority(ip: str) -> int:
    """Приоритет адреса: меньше = вероятнее WiFi-LAN телефона."""
    if ip.startswith("192.168."):
        return 0
    if ip.startswith("172."):
        try:
            if 16 <= int(ip.split(".")[1]) <= 31:
                return 1
        except (ValueError, IndexError):
            pass
    if ip.startswith("169.254."):  # APIPA — сети фактически нет
        return 5
    if ip.startswith("10."):  # часто VPN/туннель
        return 3
    return 2


def local_ips() -> list[str]:
    """Вероятные LAN-IP ПК (без loopback), отсортированы по приоритету.

    192.168.* первым (типичный WiFi), VPN/10.* — позже. Всегда непустой.
    """
    raw: list[str] = []
    route = _route_ip()
    if route:
        raw.append(route)
    raw.extend(_hostname_ips())

    seen: set[str] = set()
    out: list[str] = []
    for ip in raw:
        if ip and not ip.startswith("127.") and ip not in seen:
            seen.add(ip)
            out.append(ip)
    out.sort(key=_priority)
    return out or ["127.0.0.1"]


def local_ip() -> str:
    """Наиболее вероятный LAN-IP (первый из local_ips())."""
    return local_ips()[0]
