"""AppManifest / load_manifest — резолв путей, version+extras, discovery (Ф5.11)."""

from __future__ import annotations

from pathlib import Path

from multiprocess_framework.modules.app_module import AppManifest, load_manifest


def _write(tmp: Path, text: str) -> Path:
    p = tmp / "app.yaml"
    p.write_text(text, encoding="utf-8")
    return p


def test_load_minimal_manifest(tmp_path: Path) -> None:
    (tmp_path / "pipeline.yaml").write_text("name: p\nprocesses: []\n", encoding="utf-8")
    path = _write(tmp_path, "name: My App\npipeline: pipeline.yaml\n")
    m = load_manifest(path)
    assert isinstance(m, AppManifest)
    assert m.name == "My App"
    assert m.version == 1  # дефолт
    assert m.extras == {}
    assert m.pipeline == (tmp_path / "pipeline.yaml").resolve()
    assert m.source == path.resolve()


def test_version_and_extras_passthrough(tmp_path: Path) -> None:
    (tmp_path / "pipeline.yaml").write_text("processes: []\n", encoding="utf-8")
    path = _write(
        tmp_path,
        "name: X\nversion: 3\npipeline: pipeline.yaml\nextras:\n  theme: dark\n  brand: acme\n",
    )
    m = load_manifest(path)
    assert m.version == 3
    assert m.extras == {"theme": "dark", "brand": "acme"}  # pass-through, framework не читает


def test_relative_paths_resolved_from_manifest_dir(tmp_path: Path) -> None:
    (tmp_path / "pipeline.yaml").write_text("processes: []\n", encoding="utf-8")
    path = _write(
        tmp_path,
        "pipeline: pipeline.yaml\nbase: base.yaml\nsystem: sys.yaml\nrecipes: recipes\n",
    )
    m = load_manifest(path)
    assert m.base == (tmp_path / "base.yaml").resolve()
    assert m.system == (tmp_path / "sys.yaml").resolve()
    assert m.recipes == (tmp_path / "recipes").resolve()


def test_discovery_paths_absolute_from_manifest_dir(tmp_path: Path) -> None:
    (tmp_path / "pipeline.yaml").write_text("processes: []\n", encoding="utf-8")
    path = _write(
        tmp_path,
        "pipeline: pipeline.yaml\n"
        "discovery:\n"
        "  plugin_paths: [my_plugins]\n"
        "  service_paths: [my_services]\n"
        "  auto_discover: true\n",
    )
    m = load_manifest(path)
    assert m.discovery.plugin_paths == [str((tmp_path / "my_plugins").resolve())]
    assert m.discovery.service_paths == [str((tmp_path / "my_services").resolve())]
    assert m.discovery.auto_discover is True


def test_discovery_defaults_when_absent(tmp_path: Path) -> None:
    (tmp_path / "pipeline.yaml").write_text("processes: []\n", encoding="utf-8")
    path = _write(tmp_path, "pipeline: pipeline.yaml\n")
    m = load_manifest(path)
    # дефолты plugins/services, резолвнуты от каталога манифеста
    assert m.discovery.plugin_paths == [str((tmp_path / "plugins").resolve())]
    assert m.discovery.service_paths == [str((tmp_path / "services").resolve())]
    assert m.discovery.auto_discover is True
