"""discover — единый helper: находит И плагин, И сервис из указанной папки (A6, Ф5.11)."""

from __future__ import annotations

import textwrap
from pathlib import Path

from multiprocess_framework.modules.app_module import (
    DiscoveryResult,
    ServiceManifest,
    discover,
    discover_services,
)


def test_discover_services_by_marker(tmp_path: Path) -> None:
    (tmp_path / "svc_a").mkdir()
    (tmp_path / "svc_a" / "service.yaml").write_text("name: alpha\nversion: 2\nextras:\n  k: v\n", encoding="utf-8")
    (tmp_path / "svc_b").mkdir()
    (tmp_path / "svc_b" / "service.yaml").write_text("", encoding="utf-8")  # пустой маркер
    (tmp_path / "not_a_service").mkdir()  # нет маркера — игнор

    svcs = discover_services(str(tmp_path))
    by_name = {s.name: s for s in svcs}
    assert set(by_name) == {"alpha", "svc_b"}
    assert by_name["alpha"].version == 2
    assert by_name["alpha"].extras == {"k": "v"}
    assert by_name["svc_b"].version == 1  # дефолт при пустом маркере
    assert isinstance(by_name["alpha"], ServiceManifest)


class _FakeRegistry:
    """Мок PluginRegistry: считает discover-вызовы, отдаёт failed_imports."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, ...]] = []

    def discover(self, *paths: str) -> int:
        self.calls.append(paths)
        return len(paths)  # «нашли по одному плагину на путь»

    def failed_imports(self) -> dict[str, str]:
        return {"broken.plugin": "SyntaxError: boom"}


def test_discover_finds_plugin_and_service(tmp_path: Path) -> None:
    """Acceptance-ядро: один helper находит И плагин, И сервис из указанной папки."""
    svc_dir = tmp_path / "services"
    (svc_dir / "echo").mkdir(parents=True)
    (svc_dir / "echo" / "service.yaml").write_text("name: echo\n", encoding="utf-8")

    reg = _FakeRegistry()
    result = discover(
        plugin_paths=[str(tmp_path / "plugins")],
        service_paths=[str(svc_dir)],
        registry=reg,
    )
    assert isinstance(result, DiscoveryResult)
    assert result.plugins_discovered == 1  # плагин(и) найден(ы)
    assert result.service_names() == ["echo"]  # сервис найден по маркеру
    assert result.failed_imports == {"broken.plugin": "SyntaxError: boom"}
    assert reg.calls == [(str(tmp_path / "plugins"),)]


def test_discover_real_plugin_registration(tmp_path: Path) -> None:
    """discover действительно импортирует plugin.py и регистрирует его в singleton."""
    from multiprocess_framework.modules.process_module.plugins.registry import PluginRegistry

    pkg = tmp_path / "discotest_pkg"
    pkg.mkdir()
    (pkg / "__init__.py").write_text("", encoding="utf-8")
    (pkg / "plugin.py").write_text(
        textwrap.dedent(
            """
            from multiprocess_framework.modules.process_module.plugins import (
                ProcessModulePlugin, register_plugin,
            )

            @register_plugin("disco_probe_plugin", category="utility", description="probe")
            class DiscoProbePlugin(ProcessModulePlugin):
                name = "disco_probe_plugin"
                category = "utility"
            """
        ),
        encoding="utf-8",
    )
    import sys

    sys.path.insert(0, str(tmp_path))
    try:
        result = discover(plugin_paths=[str(pkg)], service_paths=[])
        assert PluginRegistry.get("disco_probe_plugin") is not None
        assert result.plugins_discovered >= 1
    finally:
        # НЕ чистим весь singleton (общий на suite) — снимаем только свой probe,
        # чтобы не обнулить каталог для соседних тестов.
        sys.path.remove(str(tmp_path))
        PluginRegistry._plugins.pop("disco_probe_plugin", None)
