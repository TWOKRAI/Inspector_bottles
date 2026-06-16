"""Определение локальных IP-адресов ПК в LAN — для ссылки/QR, которые
открывают на телефоне.

У ПК обычно несколько интерфейсов: WiFi, проводной Ethernet, VPN, виртуальные
адаптеры (Hyper-V/VMware/VirtualBox/WSL). Телефон почти всегда в WiFi, поэтому
адаптеры ранжируются по ТИПУ (имени интерфейса из psutil), а не только по
диапазону IP: WiFi → проводной/прочее → виртуальный. Внутри одного типа —
тай-брейк по диапазону (192.168.* вероятнее WiFi-LAN).

Раньше выбор шёл лишь по диапазону, и проводной Ethernet с тем же 192.168.*
«перебивал» WiFi → QR показывал не тот адрес. Если psutil недоступен — мягкий
фолбэк на старый способ (route + hostname, только IP без меток).
"""

from __future__ import annotations

import socket

# Имена WiFi-адаптеров (англ./рус. Windows, Linux, macOS).
_WIFI_HINTS = ("wi-fi", "wifi", "wlan", "wlp", "wireless", "беспровод", "airport")
# Виртуальные/служебные адаптеры — не для телефона (в самый конец).
_VIRTUAL_HINTS = (
    "vmware",
    "virtualbox",
    "vbox",
    "hyper-v",
    "vethernet",
    "wsl",
    "docker",
    "loopback",
    "tap",
    "tun",
    "vpn",
    "zerotier",
    "tailscale",
    "radmin",
    "default switch",
    "bluetooth",
    "isatap",
    "teredo",
    "pseudo",
)


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


def _iface_rank(name: str) -> int:
    """Ранг адаптера по имени: WiFi(0) < проводной/прочее(1) < виртуальный(2)."""
    low = name.lower()
    if any(h in low for h in _WIFI_HINTS):
        return 0
    if any(h in low for h in _VIRTUAL_HINTS):
        return 2
    return 1


def _addr_usability(ip: str) -> int:
    """Годность адреса как LAN для телефона: 0 = обычный приватный, 2 = вряд ли.

    CGNAT (100.64.0.0/10) и APIPA (169.254/16) почти никогда не та сеть, где
    телефон — их демоутим НИЖЕ нормального LAN, даже если они на WiFi-адаптере
    (бывает: ПК воткнут в чужую/провайдерскую 100.x сеть, а телефон — в роутере
    192.168.x на Ethernet ПК).
    """
    if ip.startswith("100."):  # CGNAT 100.64.0.0/10
        try:
            if 64 <= int(ip.split(".")[1]) <= 127:
                return 2
        except (ValueError, IndexError):
            pass
    if ip.startswith("169.254."):  # APIPA — сети фактически нет
        return 2
    return 0


def _priority(ip: str) -> int:
    """Тай-брейк по диапазону: меньше = вероятнее WiFi-LAN телефона."""
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


def _psutil_endpoints() -> list[tuple[str, str]]:
    """[(имя_адаптера, ip)] — поднятые интерфейсы с не-loopback IPv4 (psutil)."""
    import psutil

    stats = psutil.net_if_stats()
    out: list[tuple[str, str]] = []
    for name, addrs in psutil.net_if_addrs().items():
        st = stats.get(name)
        if st is not None and not st.isup:  # пропускаем выключенные адаптеры
            continue
        for addr in addrs:
            if addr.family == socket.AF_INET and addr.address and not addr.address.startswith("127."):
                out.append((name, addr.address))
    return out


def _socket_endpoints() -> list[tuple[str, str]]:
    """Фолбэк без psutil: IP через route+hostname, метка интерфейса пустая."""
    raw: list[str] = []
    route = _route_ip()
    if route:
        raw.append(route)
    raw.extend(_hostname_ips())
    return [("", ip) for ip in raw if ip and not ip.startswith("127.")]


def local_endpoints() -> list[tuple[str, str]]:
    """[(метка_интерфейса, ip)] — вероятные LAN-адреса ПК, WiFi первым.

    Сортировка: тип адаптера (WiFi → проводной → виртуальный), затем диапазон IP.
    Метка — имя интерфейса ("" если определить нельзя, фолбэк-режим). Всегда
    непустой список (как минимум фолбэк-loopback).
    """
    try:
        raw = _psutil_endpoints()
    except Exception:
        raw = []
    if not raw:
        raw = _socket_endpoints()

    seen: set[str] = set()
    uniq: list[tuple[str, str]] = []
    for name, ip in raw:
        if ip not in seen:
            seen.add(ip)
            uniq.append((name, ip))
    # Порядок ключей: годность адреса (нормальный LAN > CGNAT/APIPA) → тип
    # адаптера (WiFi > проводной > виртуальный) → диапазон IP. Так нормальный
    # LAN на Ethernet обходит WiFi-адаптер с CGNAT-адресом.
    uniq.sort(key=lambda ni: (_addr_usability(ni[1]), _iface_rank(ni[0]), _priority(ni[1])))
    return uniq or [("", "127.0.0.1")]


def local_ips() -> list[str]:
    """Вероятные LAN-IP ПК (без loopback), WiFi первым. Всегда непустой.

    WiFi-адаптер первым (даже если есть проводной с тем же 192.168.*),
    VPN/виртуальные — позже.
    """
    return [ip for _, ip in local_endpoints()]


def local_ip() -> str:
    """Наиболее вероятный LAN-IP (первый из local_ips())."""
    return local_ips()[0]
