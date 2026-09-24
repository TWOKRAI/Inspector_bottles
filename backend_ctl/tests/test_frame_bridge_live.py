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

Читатель — в ОТДЕЛЬНОМ процессе (``python -c``), как настоящий Пульт. В одном дереве с
бэкендом ``RemoteFrameSource`` (``track=False``) снимал бы сегменты продюсера с учёта
ОБЩЕГО ``resource_tracker`` — на остановке бэкенда трекер печатал
``KeyError: '/output_frames_N'`` (ревью 1.3, m4). Поэтому же тест проверяет stderr
прогона: ни одной такой строки.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

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


_READER_SCRIPT = r"""
import json, sys, threading, time
from multiprocess_framework.modules.frontend_module.bridge.remote_frame_source import RemoteFrameSource
from multiprocess_framework.modules.router_module.channels.socket_client import SocketClient

port, want, window = int(sys.argv[1]), int(sys.argv[2]), float(sys.argv[3])
frames, enough = [], threading.Event()

def on_frame(sender, frame, bseq):
    frames.append([sender, list(frame.shape), str(frame.dtype), bseq])
    if len(frames) >= want:
        enough.set()

client = SocketClient("127.0.0.1", port, sender="pult")  # sender != имя двери хаба
client.connect(timeout=5.0)
source = RemoteFrameSource(client, dispatch=lambda fn: fn())
reply = source.subscribe(None, on_frame, timeout=8.0)
t0 = time.monotonic()
enough.wait(window)
elapsed = time.monotonic() - t0
stats = source.stats
source.close()
client.close()
print("RESULT " + json.dumps({"reply": reply, "n": len(frames), "first": frames[:1], "elapsed": elapsed,
                              "stats": stats, "address": client.subscriber_address}))
"""


def _run_reader(repo_root: Path) -> dict:
    env = dict(os.environ)
    env["PYTHONPATH"] = str(repo_root) + (os.pathsep + env["PYTHONPATH"] if env.get("PYTHONPATH") else "")
    proc = subprocess.run(
        [sys.executable, "-c", _READER_SCRIPT, str(_PORT), str(_WANT_FRAMES), str(_WINDOW_SEC)],
        cwd=str(repo_root),
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
    )
    lines = [ln for ln in proc.stdout.splitlines() if ln.startswith("RESULT ")]
    assert proc.returncode == 0 and lines, f"читатель упал rc={proc.returncode}\n{proc.stdout}\n{proc.stderr}"
    return json.loads(lines[-1][len("RESULT ") :])


@pytest.mark.harness_smoke
def test_external_client_receives_frames_through_the_bridge(tmp_path: Path, capfd, monkeypatch) -> None:
    repo_root = Path(__file__).resolve().parents[2]
    # env-overlay презентации перебил бы наш манифест.
    monkeypatch.delenv("INSPECTOR_PRESENTATION", raising=False)
    monkeypatch.delenv("INSPECTOR_HEADLESS", raising=False)
    manifest = _write_temp_manifest(repo_root / "multiprocess_prototype", tmp_path)

    harness = BackendHarness(port=_PORT, launcher_factory=lambda: _launcher(manifest))
    drv = harness.start()
    try:
        # Предусловие стенда: gui поднят именно мостом, иначе дальше проверять нечего.
        stats = drv.send_command("gui", "frames.stats", {}, timeout=8.0)
        assert (stats.get("result") or stats).get("success") is True, f"gui не мост (нет frames.stats): {stats}"
        result = _run_reader(repo_root)
    finally:
        harness.stop()

    assert result["reply"].get("success") is True, result
    assert result["n"] >= _WANT_FRAMES, f"за {result['elapsed']:.1f}с пришло {result['n']} кадров: {result}"
    sender, shape, dtype, _ = result["first"][0]
    assert sender == "synthetic_source"
    assert shape == [480, 640, 3]
    assert dtype == "uint8"

    # m4: остановка бэкенда без KeyError трекера (читатель вне дерева не трогает его учёт).
    captured = capfd.readouterr()
    leaked = [ln for ln in (captured.err + captured.out).splitlines() if "KeyError" in ln]
    assert leaked == [], f"resource_tracker бэкенда потерял регистрации продюсера: {leaked}"
