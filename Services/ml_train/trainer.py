"""Trainer — цикл обучения: AMP, EMA, mixup, warmup+cosine, early stopping.

Артефакты прогона (runs_dir/run_name/):
    config.yaml    — снимок конфига (воспроизводимость)
    classes.txt    — имена классов (по строке, индекс = номер строки)
    history.json   — метрики по эпохам (пишется после каждой эпохи — crash-safe)
    metrics.json   — итог: лучшая эпоха + подробный отчёт val (+ test при наличии)
    best.pt        — лучший чекпоинт по монитор-метрике (при EMA — веса EMA)
    last.pt        — последняя эпоха

Чекпоинт = dict: model_state, config (dict), class_names, image_size,
epoch, metrics — самодостаточен для экспорта/инференса.
"""

from __future__ import annotations

import copy
import json
import logging
import math
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

import numpy as np
import torch
from torch import nn

from Services.ml_train import metrics as M
from Services.ml_train.config import TrainConfig
from Services.ml_train.data import DataBundle, build_dataloaders
from Services.ml_train.models import MultiHeadModel, build_model

logger = logging.getLogger(__name__)


@dataclass
class TrainResult:
    """Итог прогона."""

    run_dir: Path
    best_epoch: int
    best_metrics: dict[str, Any]
    history: list[dict[str, Any]]
    checkpoint_path: Path


class _Ema:
    """Экспоненциальное скользящее среднее весов (валидация и чекпоинт — по EMA).

    Ключи shadow хранятся без префикса torch.compile (`_orig_mod.`) — чекпоинт
    и eval-копия работают с «чистыми» именами. Warmup: эффективный decay
    min(decay, (1+n)/(10+n)) — первые эпохи не «вмораживают» случайную
    инициализацию в теневые веса.
    """

    def __init__(self, model: nn.Module, decay: float) -> None:
        self.decay = decay
        self.updates = 0
        self.shadow = {k.removeprefix("_orig_mod."): v.detach().clone().float() for k, v in model.state_dict().items()}

    @torch.no_grad()
    def update(self, model: nn.Module) -> None:
        self.updates += 1
        decay = min(self.decay, (1.0 + self.updates) / (10.0 + self.updates))
        for raw_key, v in model.state_dict().items():
            k = raw_key.removeprefix("_orig_mod.")
            if v.dtype.is_floating_point:
                self.shadow[k].mul_(decay).add_(v.detach().float(), alpha=1.0 - decay)
            else:
                self.shadow[k] = v.detach().clone().float()

    def state_dict_like(self, model: nn.Module) -> dict[str, torch.Tensor]:
        """Теневые веса, приведённые к dtype модели (ключи — без префикса compile)."""
        sd = {k.removeprefix("_orig_mod."): v for k, v in model.state_dict().items()}
        return {k: self.shadow[k].to(v.dtype) for k, v in sd.items()}


class Trainer:
    """Обучение по TrainConfig. Использование: Trainer(config).fit()."""

    def __init__(self, config: TrainConfig) -> None:
        self.config = config
        self.device = _resolve_device(config.train.device)
        self.amp_dtype = _resolve_amp(config.train.amp, self.device)
        torch.manual_seed(config.data.seed)
        # собственный rng (mixup и т.п.) — глобальный np.random не трогаем
        self._rng = np.random.default_rng(config.data.seed)

        self.bundle: DataBundle = build_dataloaders(config.data)
        num_classes = config.model.num_classes or len(self.bundle.class_names)
        if num_classes != len(self.bundle.class_names):
            raise ValueError(
                f"model.num_classes={num_classes} не совпадает с числом классов в данных "
                f"({len(self.bundle.class_names)})"
            )
        self.model: MultiHeadModel = build_model(config.model, num_classes).to(self.device)
        if config.train.channels_last:
            self.model = self.model.to(memory_format=torch.channels_last)
        # eval-копия для EMA-валидации: создаётся ОДИН раз и ДО torch.compile
        # (deepcopy OptimizedModule нестабилен; копия раз в эпоху — лишняя память)
        self._ema_eval = copy.deepcopy(self.model) if config.train.ema_decay > 0 else None
        if config.train.compile:
            self.model = torch.compile(self.model)  # type: ignore[assignment]

        weights = self._class_weight_tensor()
        self.criterion = nn.CrossEntropyLoss(
            weight=weights.to(self.device) if weights is not None else None,
            label_smoothing=config.optim.label_smoothing,
        )
        self.optimizer = torch.optim.AdamW(
            self.model.parameters(),
            lr=config.optim.lr,
            weight_decay=config.optim.weight_decay,
        )
        self.scheduler = self._build_scheduler()
        self.scaler = torch.amp.GradScaler(self.device.type, enabled=self.amp_dtype == torch.float16)
        self.ema = _Ema(self.model, config.train.ema_decay) if config.train.ema_decay > 0 else None

        self.run_dir = self._prepare_run_dir()
        logger.info(
            "Trainer: arch=%s classes=%d device=%s amp=%s run=%s",
            config.model.arch,
            num_classes,
            self.device,
            self.amp_dtype,
            self.run_dir,
        )

    # ------------------------------------------------------------------ #
    # Публичное
    # ------------------------------------------------------------------ #

    def fit(self) -> TrainResult:
        """Полный цикл обучения.

        Post: в run_dir лежат config.yaml, classes.txt, history.json,
              metrics.json, best.pt, last.pt; возвращён TrainResult.
        """
        cfg = self.config
        monitor, mode = cfg.train.monitor, cfg.monitor_mode
        best_value = math.inf if mode == "min" else -math.inf
        best_epoch = -1
        best_metrics: dict[str, Any] = {}
        epochs_without_improve = 0
        history: list[dict[str, Any]] = []

        for epoch in range(cfg.optim.epochs):
            t0 = time.perf_counter()
            train_loss = self._train_one_epoch()
            val_summary, val_loss = self._validate(self.bundle.val_loader)
            if monitor == "angle_mae_deg" and val_summary.get("angle_mae_deg") is None:
                # в данных нет валидных углов (например, folder-источник) —
                # иначе best.pt не сохранился бы ни разу, а plateau упал бы на None
                logger.warning("monitor=angle_mae_deg недоступен (нет валидных углов) — переключаюсь на val_loss")
                monitor, mode, best_value = "val_loss", "min", math.inf
            if isinstance(self.scheduler, torch.optim.lr_scheduler.ReduceLROnPlateau):
                plateau_value = val_summary.get(monitor)
                self.scheduler.step(val_loss if plateau_value is None else plateau_value)
            elif self.scheduler is not None:
                self.scheduler.step()

            entry = {
                "epoch": epoch,
                "train_loss": round(train_loss, 5),
                "val_loss": round(val_loss, 5),
                "accuracy": val_summary["accuracy"],
                "balanced_accuracy": val_summary["balanced_accuracy"],
                "angle_mae_deg": val_summary.get("angle_mae_deg"),
                "lr": self.optimizer.param_groups[0]["lr"],
                "seconds": round(time.perf_counter() - t0, 1),
            }
            history.append(entry)
            _write_json(self.run_dir / "history.json", history)
            logger.info(
                "epoch %d/%d: train_loss=%.4f val_loss=%.4f acc=%.4f bal_acc=%.4f%s (%.1fs)",
                epoch + 1,
                cfg.optim.epochs,
                train_loss,
                val_loss,
                entry["accuracy"],
                entry["balanced_accuracy"],
                f" angle_mae={entry['angle_mae_deg']}°" if entry["angle_mae_deg"] is not None else "",
                entry["seconds"],
            )

            current = entry["val_loss"] if monitor == "val_loss" else val_summary.get(monitor)
            improved = current is not None and (current < best_value if mode == "min" else current > best_value)
            if improved:
                best_value, best_epoch, best_metrics = current, epoch, val_summary
                epochs_without_improve = 0
                self._save_checkpoint(self.run_dir / "best.pt", epoch, val_summary)
            else:
                epochs_without_improve += 1

            self._save_checkpoint(self.run_dir / "last.pt", epoch, val_summary)
            patience = cfg.train.early_stopping_patience
            if patience > 0 and epochs_without_improve >= patience:
                logger.info("Early stopping: %d эпох без улучшения %s", patience, monitor)
                break

        final = {"best_epoch": best_epoch, "monitor": monitor, "best": best_metrics}
        if self.bundle.test_loader is not None and best_epoch >= 0:
            self._load_state(torch.load(self.run_dir / "best.pt", map_location=self.device, weights_only=True))
            test_summary, _ = self._validate(self.bundle.test_loader)
            final["test"] = test_summary
            logger.info("test: acc=%.4f bal_acc=%.4f", test_summary["accuracy"], test_summary["balanced_accuracy"])
        _write_json(self.run_dir / "metrics.json", final)

        return TrainResult(
            run_dir=self.run_dir,
            best_epoch=best_epoch,
            best_metrics=best_metrics,
            history=history,
            checkpoint_path=self.run_dir / "best.pt",
        )

    # ------------------------------------------------------------------ #
    # Эпоха
    # ------------------------------------------------------------------ #

    def _train_one_epoch(self) -> float:
        self.model.train()
        cfg = self.config
        total_loss, n_batches = 0.0, 0
        for images, target in self.bundle.train_loader:
            images = self._to_device(images)
            labels = target["class_index"].to(self.device)
            self.optimizer.zero_grad(set_to_none=True)
            with torch.amp.autocast(self.device.type, dtype=self.amp_dtype, enabled=self.amp_dtype is not None):
                if cfg.optim.mixup_alpha > 0:
                    loss = self._mixup_step(images, labels)
                else:
                    logits, angle = self.model(images)
                    loss = self.criterion(logits, labels)
                    if angle is not None:
                        loss = loss + cfg.optim.angle_loss_weight * _angle_loss(angle, target, self.device)
            self.scaler.scale(loss).backward()
            self.scaler.step(self.optimizer)
            self.scaler.update()
            if self.ema is not None:
                self.ema.update(self.model)
            total_loss += loss.item()
            n_batches += 1
        return total_loss / max(n_batches, 1)

    def _mixup_step(self, images: torch.Tensor, labels: torch.Tensor) -> torch.Tensor:
        lam = float(self._rng.beta(self.config.optim.mixup_alpha, self.config.optim.mixup_alpha))
        perm = torch.randperm(images.size(0), device=images.device)
        mixed = lam * images + (1.0 - lam) * images[perm]
        logits, _ = self.model(mixed)
        return lam * self.criterion(logits, labels) + (1.0 - lam) * self.criterion(logits, labels[perm])

    @torch.no_grad()
    def _validate(self, loader) -> tuple[dict[str, Any], float]:
        """Метрики на наборе. При EMA — на теневых весах (как и сохраняемый чекпоинт)."""
        model = self._eval_model()
        model.eval()
        y_true, y_pred = [], []
        pred_sc, true_sc, valid = [], [], []
        total_loss, n_batches = 0.0, 0
        for images, target in loader:
            images = self._to_device(images)
            labels = target["class_index"].to(self.device)
            with torch.amp.autocast(self.device.type, dtype=self.amp_dtype, enabled=self.amp_dtype is not None):
                logits, angle = model(images)
                loss = self.criterion(logits, labels)
                if angle is not None:
                    loss = loss + self.config.optim.angle_loss_weight * _angle_loss(angle, target, self.device)
            total_loss += loss.item()
            n_batches += 1
            y_true.append(labels.cpu().numpy())
            y_pred.append(logits.argmax(dim=1).cpu().numpy())
            if angle is not None:
                pred_sc.append(angle.float().cpu().numpy())
                true_sc.append(target["angle"].numpy())
                valid.append(target["angle_valid"].numpy())
        sym_map = self.bundle.symmetry_map
        class_symmetry = [sym_map.get(n, "none") for n in self.bundle.class_names] if sym_map else None
        summary = M.evaluation_summary(
            np.concatenate(y_true),
            np.concatenate(y_pred),
            self.bundle.class_names,
            pred_sincos=np.concatenate(pred_sc) if pred_sc else None,
            true_sincos=np.concatenate(true_sc) if true_sc else None,
            angle_valid=np.concatenate(valid) if valid else None,
            class_symmetry=class_symmetry,
        )
        return summary, total_loss / max(n_batches, 1)

    # ------------------------------------------------------------------ #
    # Внутреннее
    # ------------------------------------------------------------------ #

    def _eval_model(self) -> nn.Module:
        if self.ema is None or self._ema_eval is None:
            return self.model
        self._ema_eval.load_state_dict(self.ema.state_dict_like(self.model))
        return self._ema_eval

    def _to_device(self, images: torch.Tensor) -> torch.Tensor:
        images = images.to(self.device, non_blocking=True)
        if self.config.train.channels_last:
            images = images.to(memory_format=torch.channels_last)
        return images

    def _class_weight_tensor(self) -> torch.Tensor | None:
        opt = self.config.optim.class_weights
        if opt == "none":
            return None
        if opt == "auto":
            return self.bundle.class_weights
        if len(opt) != len(self.bundle.class_names):
            raise ValueError(f"class_weights: {len(opt)} значений, классов {len(self.bundle.class_names)}")
        return torch.tensor(opt, dtype=torch.float32)

    def _build_scheduler(self):
        cfg = self.config.optim
        if cfg.scheduler == "none":
            return None
        if cfg.scheduler == "plateau":
            return torch.optim.lr_scheduler.ReduceLROnPlateau(
                self.optimizer,
                mode=self.config.monitor_mode,
                factor=0.5,
                patience=5,
                min_lr=cfg.lr * cfg.min_lr_ratio,
            )
        # cosine + линейный warmup (per-epoch)
        warmup, total, floor = cfg.warmup_epochs, cfg.epochs, cfg.min_lr_ratio

        def factor(epoch: int) -> float:
            if warmup > 0 and epoch < warmup:
                return (epoch + 1) / warmup
            progress = (epoch - warmup) / max(total - warmup, 1)
            return floor + 0.5 * (1.0 - floor) * (1.0 + math.cos(math.pi * min(progress, 1.0)))

        return torch.optim.lr_scheduler.LambdaLR(self.optimizer, lr_lambda=factor)

    def _prepare_run_dir(self) -> Path:
        cfg = self.config.train
        name = cfg.run_name or f"{self.config.model.arch.replace('/', '_')}_{datetime.now():%Y%m%d_%H%M%S}"
        run_dir = Path(cfg.runs_dir) / name
        run_dir.mkdir(parents=True, exist_ok=True)
        self.config.to_yaml(run_dir / "config.yaml")
        (run_dir / "classes.txt").write_text("\n".join(self.bundle.class_names) + "\n", encoding="utf-8")
        return run_dir

    def _save_checkpoint(self, path: Path, epoch: int, val_summary: dict[str, Any]) -> None:
        state = self.ema.state_dict_like(self.model) if self.ema is not None else self.model.state_dict()
        # torch.compile оборачивает модель → ключи с префиксом _orig_mod.;
        # чекпоинт храним в «чистых» ключах, чтобы экспорт грузил без компиляции
        state = {k.removeprefix("_orig_mod."): v for k, v in state.items()}
        torch.save(
            {
                "model_state": state,
                "config": self.config.to_dict(),
                "class_names": self.bundle.class_names,
                "image_size": list(self.bundle.image_size),
                "symmetry_map": self.bundle.symmetry_map,  # для декода угла в инференсе
                "epoch": epoch,
                "metrics": {k: v for k, v in val_summary.items() if k != "confusion_matrix"},
            },
            path,
        )

    def _load_state(self, checkpoint: dict[str, Any]) -> None:
        # при compile=True грузим в подлежащий модуль (ключи чекпоинта — без префикса)
        target = getattr(self.model, "_orig_mod", self.model)
        target.load_state_dict(checkpoint["model_state"])
        if self.ema is not None:
            self.ema = _Ema(self.model, self.config.train.ema_decay)


def _angle_loss(pred: torch.Tensor, target: dict[str, torch.Tensor], device: torch.device) -> torch.Tensor:
    """MSE по (sin, cos) с маской angle_valid (классы с full-симметрией исключены)."""
    true = target["angle"].to(device)
    mask = target["angle_valid"].to(device)
    if not mask.any():
        return pred.sum() * 0.0  # сохранить граф, нулевой вклад
    err = ((pred - true) ** 2).sum(dim=1)
    return (err * mask.float()).sum() / mask.float().sum()


def _resolve_device(spec: str) -> torch.device:
    if spec == "auto":
        return torch.device("cuda" if torch.cuda.is_available() else "cpu")
    device = torch.device(spec)
    if device.type == "cuda" and not torch.cuda.is_available():
        raise RuntimeError("Запрошен CUDA, но torch.cuda.is_available() == False")
    return device


def _resolve_amp(mode: str, device: torch.device) -> torch.dtype | None:
    """auto: bf16 на CUDA с поддержкой, иначе fp16; CPU — без AMP.

    Явный fp16 вне CUDA запрещён: GradScaler не работает на CPU —
    fp16-градиенты остались бы без скейлинга (тихий underflow).
    """
    if mode == "off":
        return None
    if mode == "bf16":
        return torch.bfloat16
    if mode == "fp16":
        if device.type != "cuda":
            raise ValueError("amp=fp16 поддерживается только на CUDA; для CPU используйте off/bf16/auto")
        return torch.float16
    if device.type != "cuda":
        return None
    return torch.bfloat16 if torch.cuda.is_bf16_supported() else torch.float16


def _write_json(path: Path, data: Any) -> None:
    path.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")


def train(config: TrainConfig) -> TrainResult:
    """Высокоуровневая точка входа: обучить по конфигу (+ авто-экспорт при export.auto)."""
    result = Trainer(config).fit()
    if config.export.auto and result.best_epoch >= 0:
        from Services.ml_train.export import export_onnx

        export_onnx(result.checkpoint_path, models_dir=config.export.models_dir, opset=config.export.opset)
    return result
