"""Live-тест моста кадров (gui-service Task 1.3) — реальные объекты целиком.

Юнит-харнессы 1.2/1.3 пушат прямо с хоста в сокет и поэтому не видят, как хаб
адресует push внешней сессии. На живом стенде лида (52091085, порт 8891) это и
всплыло: клиент с ``sender="pult"`` подписался, мост отправил 492 дескриптора, а
клиент не получил ни одного — хаб (``SocketChannel._resolve_session``) доставляет
push, только если голова адреса совпадает с именем канала-двери (``backend_ctl``).

Здесь: headless-бэкенд рецепта ``bridge_synth`` с overlay'ем
``presentation_bridge.yaml`` (``gui`` → ``BridgeGuiProcess``), ``SocketClient`` с
чужим ``sender`` + ``RemoteFrameSource`` → кадры реально приходят.

Манифест — временная копия (как ``test_recipe_service_live.py``): боевой
``multiprocess_prototype/app.yaml`` не пишется (путь ``build_launcher``, не ``main()``).
Свой порт из диапазона 8880-8899 (ловушка «двух бэкендов», ``backend_ctl/AGENTS.md``).
"""

from __future__ import annotations

import threading
import time
from pathlib import Path

import numpy as np
import pytest
import yaml

from backend_ctl.harness import BackendHarness

_PORT = 8893  # уникальный порт этого модуля (8891 занят стендом лида)
_RECIPE = "bridge_synth"
_WANT_FRAMES = 20
_WINDOW_SEC = 3.0


def _write_temp_manifest(repo_dir: Path, tmp_root: Path) -> Path:
    """Копия ``app.yaml``: все пути — абсолютные на репозиторий, рецепт и overlay свои."""
    src = repo_dir / "app.yaml"
    raw = yaml.safe_load(src.read_text(encoding="utf-8"))
    raw["system"] = str(repo_dir / raw["system"])
    raw["base"] = [str(repo_dir / b) for b in raw.get("base") or []]
    if isinstance(raw.get("styles"), dict) and raw["styles"].get("dir"):
        raw["styles"]["dir"] = str(repo_dir / raw["styles"]["dir"])
    raw["recipes"] = str(repo_dir / "recipes")
    raw["pipeline"] = str(repo_dir / "recipes" / f"{_RECIPE}.yaml")
    raw["presentation"] = str(repo_dir / "frontend" / "presentation_bridge.yaml")
    out = tmp_root / "app.yaml"
    out.write_text(yaml.safe_dump(raw, sort_keys=False, allow_unicode=True), encoding="utf-8")
    return out


def _launcher(manifest: Path):
    from multiprocess_prototype.backend.config.manifest import load_manifest
    from multiprocess_prototype.main import build_launcher

    return build_launcher(load_manifest(manifest), None, include_presentation=True)


@pytest.fixture(scope="module")
def bridge_backend(tmp_path_factory: pytest.TempPathFactory, monkeypatch_module):
    repo_dir = Path(__file__).resolve().parents[2] / "multiprocess_prototype"
    # env-overlay презентации перебил бы наш манифест — снимаем на время модуля.
    monkeypatch_module.delenv("INSPECTOR_PRESENTATION", raising=False)
    monkeypatch_module.delenv("INSPECTOR_HEADLESS", raising=False)
    manifest = _write_temp_manifest(repo_dir, tmp_path_factory.mktemp("frame_bridge_live"))
    harness = BackendHarness(port=_PORT, launcher_factory=lambda: _launcher(manifest))
    drv = harness.start()
    try:
        yield drv
    finally:
        harness.stop()


@pytest.fixture(scope="module")
def monkeypatch_module():
    mp = pytest.MonkeyPatch()
    try:
        yield mp
    finally:
        mp.undo()


@pytest.mark.harness_smoke
def test_external_client_receives_frames_through_the_bridge(bridge_backend) -> None:
    from multiprocess_framework.modules.frontend_module.bridge.remote_frame_source import RemoteFrameSource
    from multiprocess_framework.modules.router_module.channels.socket_client import SocketClient

    # Предусловие стенда: gui поднят именно мостом, иначе дальше проверять нечего.
    stats = bridge_backend.send_command("gui", "frames.stats", {}, timeout=8.0)
    assert (stats.get("result") or stats).get("success") is True, f"gui не мост (нет frames.stats): {stats}"

    frames: list = []
    got_enough = threading.Event()

    def _on_frame(sender: str, frame: np.ndarray, bseq: int) -> None:
        frames.append((sender, frame.shape, frame.dtype, bseq))
        if len(frames) >= _WANT_FRAMES:
            got_enough.set()

    client = SocketClient("127.0.0.1", _PORT, sender="pult")  # sender ≠ имя двери хаба
    client.connect(timeout=5.0)
    source = RemoteFrameSource(client, dispatch=lambda fn: fn())
    try:
        reply = source.subscribe(None, _on_frame, timeout=8.0)
        assert reply.get("success") is True, reply
        t0 = time.monotonic()
        got_enough.wait(_WINDOW_SEC)
        elapsed = time.monotonic() - t0
        assert len(frames) >= _WANT_FRAMES, (
            f"за {elapsed:.1f}с пришло {len(frames)} кадров (< {_WANT_FRAMES}); "
            f"stats клиента={source.stats}, адрес={client.subscriber_address}"
        )
        sender, shape, dtype, _ = frames[0]
        assert sender == "synthetic_source"
        assert shape == (480, 640, 3)
        assert dtype == np.uint8
    finally:
        source.close()
        client.close()
