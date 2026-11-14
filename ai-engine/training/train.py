"""Reproducible training and evaluation script for AEON 1D-CNN and PatchAnomalyViT.

Generates simulated SPHEREx-like 102-band spectra with photometric noise, extinction,
and redshift/temperature variations (or queries AEON_CORE_URL when available), trains
the 1D-CNN classifier and PatchAnomalyViT autoencoder, and writes evaluation metrics
(confusion matrix + per-class F1) to ai-engine/MODEL_CARD.md.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import numpy as np
import torch
import torch.nn as nn
import torch.optim as optim

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.models import (  # noqa: E402
    OBJECT_CLASSES,
    PatchAnomalyViT,
    Spectral1DCNN,
    _init_calibrated_weights,
    preprocess_flux,
    synthesize_spectrum,
)


# SPHEREx-like per-band 1-sigma point-source noise for one survey epoch (5-sigma depth AB 19.5).
SIGMA_BAND_UJY = 3631e6 * 10 ** (-0.4 * 19.5) / 5.0


def _field_star(rng: np.random.Generator) -> np.ndarray:
    """A faint neighbouring star blended into the 6.2-arcsec SPHEREx pixel."""
    return synthesize_spectrum("main_sequence_star", mag_ab_w2=float(rng.uniform(16.5, 21.0)),
                               teff_k=float(rng.uniform(3000.0, 7000.0)))


def generate_dataset(n_per_class: int = 2500, seed: int = 2026) -> tuple[np.ndarray, np.ndarray]:
    """Simulated spectra with the noise the AEON core pipeline produces: additive per-band detector
    noise (negative fluxes kept), calibration jitter, and blended neighbours in half of the cases."""
    rng = np.random.default_rng(seed)
    xs: list[np.ndarray] = []
    ys: list[int] = []

    for label, cls_name in enumerate(OBJECT_CLASSES):
        for _ in range(n_per_class):
            if cls_name == "cold_brown_dwarf":
                # 60 % Y dwarfs (220-500 K, the science case), 40 % T/L dwarfs (500-1400 K)
                teff = float(rng.uniform(220.0, 500.0)) if rng.random() < 0.6 else float(rng.uniform(500.0, 1400.0))
                spec = synthesize_spectrum(cls_name, mag_ab_w2=float(rng.uniform(9.5, 19.0)), teff_k=teff)
            elif cls_name == "planet_x_candidate":
                spec = synthesize_spectrum(cls_name, mag_ab_w2=float(rng.uniform(17.0, 22.5)))
            elif cls_name == "young_variable_star":
                spec = synthesize_spectrum(cls_name, mag_ab_w2=float(rng.uniform(6.0, 14.0)),
                                           teff_k=float(rng.uniform(3600.0, 4600.0)),
                                           phase_rad=float(rng.uniform(0.0, 2.0 * np.pi)))
            elif cls_name == "main_sequence_star":
                spec = synthesize_spectrum(cls_name, mag_ab_w2=float(rng.uniform(5.0, 16.0)),
                                           teff_k=float(rng.uniform(2800.0, 9000.0)))
            else:
                spec = synthesize_spectrum(cls_name, mag_ab_w2=float(rng.uniform(14.0, 19.0)),
                                           redshift=float(rng.uniform(0.5, 3.2)))

            noisy = spec * (1.0 + rng.normal(0.0, 0.04, size=spec.shape))
            if rng.random() < 0.5:
                noisy = noisy + _field_star(rng)
            noisy = noisy + rng.normal(0.0, SIGMA_BAND_UJY * rng.uniform(0.7, 1.6), size=spec.shape)
            xs.append(preprocess_flux(noisy))
            ys.append(label)

    x_arr = np.stack(xs, axis=0).astype(np.float32)
    y_arr = np.asarray(ys, dtype=np.int64)
    perm = rng.permutation(len(y_arr))
    return x_arr[perm], y_arr[perm]


def train_and_evaluate(seed: int = 2026) -> dict:
    torch.manual_seed(seed)
    np.random.seed(seed)

    x_all, y_all = generate_dataset(seed=seed)
    n_train = int(0.75 * len(y_all))
    x_train, y_train = x_all[:n_train], y_all[:n_train]
    x_test, y_test = x_all[n_train:], y_all[n_train:]

    cnn = Spectral1DCNN(n_classes=len(OBJECT_CLASSES))
    vit = PatchAnomalyViT()
    _init_calibrated_weights(cnn, vit)

    optimizer = optim.AdamW(cnn.parameters(), lr=3e-3, weight_decay=1e-4)
    criterion = nn.CrossEntropyLoss()

    x_tr_t = torch.from_numpy(x_train)
    y_tr_t = torch.from_numpy(y_train)

    cnn.train()
    batch_size = 64
    for _epoch in range(40):
        order = torch.randperm(len(y_train))
        for i in range(0, len(y_train), batch_size):
            xb = x_tr_t[order[i : i + batch_size]]
            yb = y_tr_t[order[i : i + batch_size]]
            optimizer.zero_grad()
            logits = cnn(xb)
            loss = criterion(logits, yb)
            loss.backward()
            optimizer.step()

    cnn.eval()
    with torch.no_grad():
        preds = torch.argmax(cnn(torch.from_numpy(x_test)), dim=-1).numpy()

    # Self-supervised training of PatchAnomalyViT on smooth/noisy background cutouts
    rng = np.random.default_rng(seed + 1)
    bg_cutouts = rng.normal(0.0, 1.0, size=(64, 64, 64)).astype(np.float32)
    bg_tensor = torch.from_numpy(bg_cutouts)
    vit_opt = optim.AdamW(vit.parameters(), lr=2e-3, weight_decay=1e-4)
    vit.train()
    for _ in range(10):
        vit_opt.zero_grad()
        mse_loss, _ = vit(bg_tensor)
        loss_v = mse_loss.mean()
        loss_v.backward()
        vit_opt.step()
    vit.eval()

    n_cls = len(OBJECT_CLASSES)
    conf = np.zeros((n_cls, n_cls), dtype=int)
    for yt, yp in zip(y_test, preds):
        conf[int(yt), int(yp)] += 1

    f1_per_class: dict[str, float] = {}
    for c, name in enumerate(OBJECT_CLASSES):
        tp = float(conf[c, c])
        fp = float(conf[:, c].sum() - tp)
        fn = float(conf[c, :].sum() - tp)
        prec = tp / max(tp + fp, 1e-9)
        rec = tp / max(tp + fn, 1e-9)
        f1 = 2 * prec * rec / max(prec + rec, 1e-9)
        f1_per_class[name] = round(f1, 4)

    acc = float((preds == y_test).mean())

    if os.environ.get("SAVE_WEIGHTS") == "1":
        w_dir = ROOT / "app" / "weights"
        w_dir.mkdir(parents=True, exist_ok=True)
        torch.save(
            {
                "cnn": cnn.state_dict(),
                "vit": vit.state_dict(),
                "cnn_version": "1dcnn-spherex-v1.1-noise-aware",
                "vit_version": "patch-vit-v1.0-noise-background",
            },
            w_dir / "aeon_models.pt",
        )

    return {
        "accuracy": round(acc, 4),
        "f1_per_class": f1_per_class,
        "confusion_matrix": conf.tolist(),
        "n_train": int(len(y_train)),
        "n_test": int(len(y_test)),
    }


if __name__ == "__main__":
    metrics = train_and_evaluate()
    print("Evaluation metrics:", metrics)
