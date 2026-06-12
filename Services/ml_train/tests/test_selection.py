"""RunRegistry: сканирование, выбор лучшего, устойчивость к битым прогонам (без torch)."""

import json

import yaml

from Services.ml_train.selection import RunRegistry


def _make_run(runs_dir, name, arch, best, monitor="balanced_accuracy", with_ckpt=True):
    run = runs_dir / name
    run.mkdir(parents=True)
    (run / "config.yaml").write_text(yaml.safe_dump({"model": {"arch": arch}}), encoding="utf-8")
    (run / "metrics.json").write_text(json.dumps({"best_epoch": 7, "monitor": monitor, "best": best}), encoding="utf-8")
    if with_ckpt:
        (run / "best.pt").write_bytes(b"fake")
    return run


def test_scan_and_best(tmp_path):
    _make_run(tmp_path, "run_a", "mobilenet_v3_large", {"accuracy": 0.90, "balanced_accuracy": 0.88})
    _make_run(tmp_path, "run_b", "mobilenetv4_medium", {"accuracy": 0.93, "balanced_accuracy": 0.92})
    reg = RunRegistry(tmp_path)
    reg.scan()
    assert set(reg.names()) == {"run_a", "run_b"}
    best = reg.best("balanced_accuracy")
    assert best is not None and best.name == "run_b"
    assert best.checkpoint is not None


def test_best_minimize_for_loss_like_metric(tmp_path):
    _make_run(tmp_path, "a", "x", {"angle_mae_deg": 5.0, "balanced_accuracy": 0.5})
    _make_run(tmp_path, "b", "x", {"angle_mae_deg": 2.0, "balanced_accuracy": 0.4})
    reg = RunRegistry(tmp_path)
    reg.scan()
    assert reg.best("angle_mae_deg").name == "b"


def test_run_without_checkpoint_excluded_from_best(tmp_path):
    _make_run(tmp_path, "no_ckpt", "x", {"balanced_accuracy": 0.99}, with_ckpt=False)
    _make_run(tmp_path, "ok", "x", {"balanced_accuracy": 0.5})
    reg = RunRegistry(tmp_path)
    reg.scan()
    assert reg.best("balanced_accuracy").name == "ok"


def test_broken_run_skipped(tmp_path):
    _make_run(tmp_path, "ok", "x", {"balanced_accuracy": 0.5})
    broken = tmp_path / "broken"
    broken.mkdir()
    (broken / "config.yaml").write_text("model: {arch: y}", encoding="utf-8")
    (broken / "metrics.json").write_text("{не json", encoding="utf-8")
    (tmp_path / "not_a_run").mkdir()  # папка без файлов — игнорируется молча
    reg = RunRegistry(tmp_path)
    reg.scan()
    assert reg.names() == ["ok"]


def test_summary_sorted(tmp_path):
    _make_run(tmp_path, "worse", "x", {"balanced_accuracy": 0.5, "accuracy": 0.5})
    _make_run(tmp_path, "better", "x", {"balanced_accuracy": 0.9, "accuracy": 0.9})
    reg = RunRegistry(tmp_path)
    reg.scan()
    rows = reg.summary()
    assert [r["run"] for r in rows] == ["better", "worse"]


def test_missing_dir(tmp_path):
    reg = RunRegistry(tmp_path / "nope")
    assert reg.scan() == {}
    assert reg.best() is None
