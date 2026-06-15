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
