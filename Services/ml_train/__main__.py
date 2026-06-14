"""CLI сервиса обучения.

python -m Services.ml_train train <config.yaml> [--run-name X]
python -m Services.ml_train runs [--runs-dir data/ml_train/runs] [--metric balanced_accuracy]
python -m Services.ml_train export <best.pt|run_dir> [--models-dir data/models] [--model-id X]
python -m Services.ml_train archs
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    parser = argparse.ArgumentParser(prog="python -m Services.ml_train", description="Обучение и выбор моделей")
    sub = parser.add_subparsers(dest="command", required=True)

    p_train = sub.add_parser("train", help="обучить модель по YAML-конфигу")
    p_train.add_argument("config", help="путь к YAML-конфигу (TrainConfig)")
    p_train.add_argument("--run-name", default=None, help="имя прогона (иначе <arch>_<timestamp>)")

    p_runs = sub.add_parser("runs", help="таблица прогонов")
    p_runs.add_argument("--runs-dir", default="data/ml_train/runs")
    p_runs.add_argument(
        "--metric",
        default="balanced_accuracy",
        choices=["balanced_accuracy", "accuracy", "angle_mae_deg"],
    )

    p_export = sub.add_parser("export", help="экспорт чекпоинта в ONNX + sidecar")
    p_export.add_argument("checkpoint", help="best.pt либо папка прогона")
    p_export.add_argument("--models-dir", default="data/models")
    p_export.add_argument("--model-id", default=None)
    p_export.add_argument("--opset", type=int, default=17)

    p_eval = sub.add_parser("eval", help="валидация на реальном hold-out (буквы + угол)")
    p_eval.add_argument("model_id", help="id экспортированной модели (имя .onnx без расширения)")
    p_eval.add_argument("holdout_dir", help="папка hold-out: <буква>/<угол>.jpg")
    p_eval.add_argument("--models-dir", default="data/models")
    p_eval.add_argument("--device", default="cpu")

    sub.add_parser("archs", help="доступные архитектуры")

    args = parser.parse_args(argv)
    return _dispatch(args)


def _dispatch(args: argparse.Namespace) -> int:
    if args.command == "train":
        return _cmd_train(args)
    if args.command == "runs":
        return _cmd_runs(args)
    if args.command == "export":
        return _cmd_export(args)
    if args.command == "eval":
        return _cmd_eval(args)
    if args.command == "archs":
        return _cmd_archs()
    return 2


def _cmd_train(args: argparse.Namespace) -> int:
    from Services.ml_train import TrainConfig, train

    config = TrainConfig.from_yaml(args.config)
    if args.run_name:
        config.train.run_name = args.run_name
    result = train(config)
    print(f"\nГотово: {result.run_dir}")
    print(
        f"Лучшая эпоха: {result.best_epoch}; метрики: {result.best_metrics.get('accuracy')} acc, "
        f"{result.best_metrics.get('balanced_accuracy')} bal_acc"
    )
    return 0


def _cmd_runs(args: argparse.Namespace) -> int:
    from Services.ml_train import RunRegistry

    registry = RunRegistry(args.runs_dir)
    registry.scan()
    rows = registry.summary(sort_by=args.metric)
    if not rows:
        print(f"Прогонов не найдено в {args.runs_dir}")
        return 1
    header = f"{'run':40} {'arch':28} {'ep':>4} {'acc':>7} {'bal_acc':>8} {'angle°':>7}"
    print(header)
    print("-" * len(header))
    for r in rows:
        print(
            f"{r['run']:40.40} {r['arch']:28.28} {r['best_epoch']:>4} "
            f"{_fmt(r['accuracy']):>7} {_fmt(r['balanced_accuracy']):>8} {_fmt(r['angle_mae_deg']):>7}"
        )
    best = registry.best(args.metric)
    if best is not None:
        print(f"\nЛучший по {args.metric}: {best.name} → {best.checkpoint}")
    return 0


def _cmd_export(args: argparse.Namespace) -> int:
    from Services.ml_train import export_onnx

    path = Path(args.checkpoint)
    checkpoint = path / "best.pt" if path.is_dir() else path
    onnx_path = export_onnx(checkpoint, models_dir=args.models_dir, model_id=args.model_id, opset=args.opset)
    print(f"Экспортировано: {onnx_path} (+ sidecar .yaml + classes.txt)")
    return 0


def _cmd_eval(args: argparse.Namespace) -> int:
    import json

    from Services.ml_train.holdout_eval import evaluate_holdout

    summary = evaluate_holdout(args.model_id, args.holdout_dir, models_dir=args.models_dir, device=args.device)
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    within_key = next((k for k in summary if k.startswith("angle_within_")), None)
    within = summary.get(within_key) if within_key else None
    print(f"\nИтог: точность буквы={summary['accuracy']:.1%}", end="")
    if summary["angle_mae_deg"] is not None:
        tail = f" (≤порог: {within:.1%})" if within is not None else ""
        print(f", angle MAE={summary['angle_mae_deg']}°{tail}")
    else:
        print(" (углы не оценивались)")
    return 0


def _cmd_archs() -> int:
    from Services.ml_train import available_archs

    for arch, source in available_archs().items():
        print(f"{arch:32} {source}")
    print(f"{'timm/<имя>':32} любая архитектура timm")
    return 0


def _fmt(value: float | None) -> str:
    return f"{value:.4f}" if isinstance(value, float) else "—"


if __name__ == "__main__":
    sys.exit(main())
