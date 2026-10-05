---
name: ml-train-service
description: "Services/ml_train DONE v1 — universal training+model selection (MobileNetV3/V4, timm), ONNX export to ml_inference; resize-policy follow-up"
metadata:
  node_type: memory
  type: project
  originSessionId: d1ad0ce6-e7ae-4d5c-b218-3fb2070df954
---

Services/ml_train (branch feat/ml-train-service, commits 91c8c988+167760e7, plan plans/ml-train-service.md) — universal NN training service, closes the pipeline [[dataset-gen-service]] → ml_train → ml_inference.

- Archs: mobilenet_v3_large/small (torchvision), mobilenetv4_* (timm), `timm/<name>` passthrough (any timm arch). MultiHeadModel: class head + optional angle head (sin/cos, masked by angle_valid).
- Data sources: synthetic (dataset_gen SyntheticDataset on-the-fly), exported (labels.csv/json), folder (class-subdirs like old keras Good/Bad/Neutral).
- Trainer: AdamW, warmup+cosine/plateau, AMP bf16/fp16 (fp16 forbidden off-CUDA), EMA (warmup decay, single eval copy created BEFORE torch.compile), mixup (incompatible with angle_head — validated), early stopping, crash-safe history. Checkpoint keys stripped of `_orig_mod.`.
- RunRegistry (no torch) — compare runs, best(metric). export_onnx → data/models/ (onnx + sidecar + classes.txt), parity torch↔ORT ≤1e-3; angle head = 2 ONNX outputs, ml_inference uses outputs[0].
- Fable review APPROVE-with-notes; all MINOR fixed. **Open follow-up (MAJOR-1):** train resizes by stretch, ml_inference preprocess letterboxes (keep_aspect=True) — fine for square inputs only; fix = resize-policy field in sidecar + ml_inference.preprocess support.
- Gotchas: train batch of size 1 kills BatchNorm → drop_last in train loader; csv stores bools as "True"/"False" strings; torch installed in venv is CPU build (PyPI) — CUDA build is user's manual install.
