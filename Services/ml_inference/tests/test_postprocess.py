"""Тесты постобработки — softmax, top-k, порог, метки."""

from __future__ import annotations

import numpy as np

from Services.ml_inference.core.postprocess import classify_postprocess, softmax


def test_softmax_sums_to_one():
    out = softmax(np.array([1.0, 2.0, 3.0]))
    assert np.isclose(out.sum(), 1.0)
    assert out[2] > out[1] > out[0]


def test_top_k_sorted_desc():
    raw = np.array([[0.1, 5.0, 0.2, 3.0]], dtype=np.float32)
    preds = classify_postprocess(raw, top_k=2)
    assert len(preds) == 2
    assert preds[0]["class_id"] == 1  # наибольший logit
    assert preds[1]["class_id"] == 3
    assert preds[0]["confidence"] >= preds[1]["confidence"]


def test_threshold_filters():
    raw = np.array([[10.0, 0.0, 0.0]], dtype=np.float32)  # softmax → ~[1, 0, 0]
    preds = classify_postprocess(raw, top_k=3, threshold=0.5)
    assert len(preds) == 1
    assert preds[0]["class_id"] == 0


def test_labels_mapping():
    raw = np.array([[0.0, 9.0]], dtype=np.float32)
    preds = classify_postprocess(raw, labels=["cat", "dog"], top_k=1)
    assert preds[0]["label"] == "dog"


def test_label_fallback_when_no_labels():
    raw = np.array([[9.0, 0.0]], dtype=np.float32)
    preds = classify_postprocess(raw, labels=None, top_k=1)
    assert preds[0]["label"] == "class_0"


def test_accepts_1d_input():
    raw = np.array([1.0, 2.0, 3.0], dtype=np.float32)
    preds = classify_postprocess(raw, top_k=1)
    assert preds[0]["class_id"] == 2


def test_no_softmax_uses_raw_probs():
    raw = np.array([[0.2, 0.8]], dtype=np.float32)
    preds = classify_postprocess(raw, top_k=2, apply_softmax=False)
    assert np.isclose(preds[0]["confidence"], 0.8)
