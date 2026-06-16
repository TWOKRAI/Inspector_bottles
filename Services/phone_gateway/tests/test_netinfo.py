"""Тесты netinfo — список IP-кандидатов и приоритет (WiFi выше VPN)."""

from __future__ import annotations

from Services.phone_gateway import netinfo


def test_local_ips_nonempty_no_loopback():
    ips = netinfo.local_ips()
    assert ips  # всегда хотя бы один (фолбэк 127.0.0.1 только если ничего нет)
    # loopback не должен попадать (кроме явного фолбэка)
    if ips != ["127.0.0.1"]:
        assert all(not ip.startswith("127.") for ip in ips)


def test_local_ip_is_first():
    assert netinfo.local_ip() == netinfo.local_ips()[0]


def test_priority_wifi_before_vpn():
    # 192.168.* (WiFi) приоритетнее 10.* (часто VPN)
    assert netinfo._priority("192.168.1.42") < netinfo._priority("10.8.0.25")
    # 169.254.* (APIPA, нет сети) — в самом конце
    assert netinfo._priority("169.254.1.1") > netinfo._priority("10.8.0.25")


def test_sorting_puts_wifi_first():
    sample = ["10.8.0.25", "192.168.1.42", "169.254.5.5"]
    sample.sort(key=netinfo._priority)
    assert sample[0] == "192.168.1.42"
    assert sample[-1] == "169.254.5.5"


def test_iface_rank_wifi_before_wired_before_virtual():
    # WiFi-адаптер приоритетнее проводного, проводной — приоритетнее виртуального
    assert netinfo._iface_rank("Wi-Fi") < netinfo._iface_rank("Ethernet")
    assert netinfo._iface_rank("Беспроводная сеть") < netinfo._iface_rank("Ethernet")
    assert netinfo._iface_rank("Ethernet") < netinfo._iface_rank("vEthernet (WSL)")
    assert netinfo._iface_rank("VMware Network Adapter") == 2


def test_endpoints_prefer_wifi_over_wired_same_range(monkeypatch):
    """WiFi и Ethernet оба 192.168.* — WiFi должен оказаться первым (адрес/QR)."""
    fake = [
        ("Ethernet", "192.168.1.50"),
        ("Wi-Fi", "192.168.0.7"),
        ("vEthernet (Default Switch)", "172.20.0.1"),
    ]
    monkeypatch.setattr(netinfo, "_psutil_endpoints", lambda: fake)
    eps = netinfo.local_endpoints()
    assert eps[0] == ("Wi-Fi", "192.168.0.7")  # WiFi первым, несмотря на тот же диапазон
    assert netinfo.local_ip() == "192.168.0.7"
    assert eps[-1][0].startswith("vEthernet")  # виртуальный — в конце


def test_endpoints_demote_cgnat_wifi_below_normal_lan(monkeypatch):
    """WiFi на CGNAT-сети (100.x) уступает Ethernet с нормальным LAN.

    Реальный случай: ПК-WiFi воткнут в чужую 100.x сеть, а телефон — в роутере
    192.168.x (= Ethernet ПК). Адрес/QR должны указывать на 192.168.x.
    """
    fake = [
        ("Беспроводная сеть", "100.73.10.92"),  # WiFi, но CGNAT — не та сеть
        ("Ethernet", "192.168.1.240"),  # нормальный домашний LAN
        ("sergey-vpn", "10.8.0.25"),  # VPN
    ]
    monkeypatch.setattr(netinfo, "_psutil_endpoints", lambda: fake)
    eps = netinfo.local_endpoints()
    assert eps[0] == ("Ethernet", "192.168.1.240")  # нормальный LAN первым
    assert netinfo.local_ip() == "192.168.1.240"
    assert eps[-1][1] == "100.73.10.92"  # CGNAT-WiFi — в конец


def test_addr_usability_demotes_cgnat_and_apipa():
    assert netinfo._addr_usability("192.168.1.5") == 0
    assert netinfo._addr_usability("10.0.0.5") == 0
    assert netinfo._addr_usability("100.73.10.92") == 2  # CGNAT
    assert netinfo._addr_usability("169.254.1.1") == 2  # APIPA
    assert netinfo._addr_usability("100.5.0.1") == 0  # 100.5 НЕ CGNAT (вне 64-127)


def test_endpoints_fallback_without_psutil(monkeypatch):
    """psutil упал — мягкий фолбэк на socket-способ (метки пустые)."""

    def _boom():
        raise RuntimeError("no psutil")

    monkeypatch.setattr(netinfo, "_psutil_endpoints", _boom)
    monkeypatch.setattr(netinfo, "_socket_endpoints", lambda: [("", "192.168.5.5")])
    eps = netinfo.local_endpoints()
    assert eps == [("", "192.168.5.5")]
    assert netinfo.local_ips() == ["192.168.5.5"]
