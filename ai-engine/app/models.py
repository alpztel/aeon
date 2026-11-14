"""1D-CNN 102-band spectral classifier and PatchAnomalyViT cutout anomaly scorer (PyTorch)."""

from __future__ import annotations

import math
import os
from pathlib import Path
from typing import Any

import numpy as np
import torch
import torch.nn as nn
import torch.nn.functional as F

OBJECT_CLASSES: tuple[str, ...] = (
    "cold_brown_dwarf",
    "planet_x_candidate",
    "young_variable_star",
    "main_sequence_star",
    "high_z_galaxy",
)

# 102 SPHEREx-like band centres (0.75 - 5.00 um across 6 detector arrays x 17 channels)
_ARRAY_EDGES_UM = (0.75, 1.11, 1.64, 2.42, 3.82, 4.42, 5.00)


def build_wavelength_grid() -> np.ndarray:
    centres = []
    for i in range(6):
        edges = np.geomspace(_ARRAY_EDGES_UM[i], _ARRAY_EDGES_UM[i + 1], 18)
        centres.append(np.sqrt(edges[:-1] * edges[1:]))
    return np.concatenate(centres)


WAVELENGTH_UM = build_wavelength_grid()

# Molecular absorption features used in physical template generation
_FEATURES: tuple[tuple[str, float, float], ...] = (
    ("H2O", 1.40, 0.060),
    ("H2O", 1.88, 0.070),
    ("H2O", 2.70, 0.140),
    ("CH4", 1.66, 0.045),
    ("CH4", 2.20, 0.060),
    ("CH4", 3.32, 0.120),
    ("CO2", 4.26, 0.035),
    ("CO", 4.67, 0.060),
)


def _planck_fnu(lam_um: np.ndarray, temp_k: float) -> np.ndarray:
    x = np.clip(14387.769 / (lam_um * temp_k), 1e-6, 700.0)
    return (1.0 / (lam_um**3)) / np.expm1(x)


def _optical_depth(lam_um: np.ndarray, depths: dict[str, float]) -> np.ndarray:
    tau = np.zeros_like(lam_um, dtype=float)
    for mol, center, sigma in _FEATURES:
        amp = depths.get(mol, 0.0)
        if amp:
            tau += amp * np.exp(-0.5 * ((lam_um - center) / sigma) ** 2)
    return tau


def synthesize_spectrum(
    object_class: str,
    mag_ab_w2: float = 16.0,
    teff_k: float | None = None,
    redshift: float | None = None,
    phase_rad: float = 0.4,
) -> np.ndarray:
    """Generate a synthetic 102-band SPHEREx-like spectrum in uJy for training & template matching."""
    lam = WAVELENGTH_UM
    flux_w2 = 3631e6 * (10.0 ** (-0.4 * mag_ab_w2))

    if object_class == "cold_brown_dwarf":
        t_eff = teff_k if teff_k is not None else 250.0
        t_col = 3.2 * t_eff
        cold = float(np.clip((500.0 - t_eff) / 250.0, 0.0, 1.0))
        tau = _optical_depth(
            lam,
            {"H2O": 2.2, "CH4": 1.5 + 2.0 * cold, "CO2": 0.6 + 0.4 * cold, "CO": 0.5},
        )
        shape = _planck_fnu(lam, t_col) * np.exp(-tau)
    elif object_class == "planet_x_candidate":
        tau = _optical_depth(lam, {"CH4": 2.6, "H2O": 0.4})
        shape = _planck_fnu(lam, 5778.0) * 0.6 * np.exp(-tau)
    elif object_class == "young_variable_star":
        t_eff = teff_k if teff_k is not None else 4100.0
        a_v = 2.2 + 1.6 * np.sin(phase_rad)
        disk = 1.0 + 0.45 * np.sin(phase_rad + 1.3)
        star = _planck_fnu(lam, t_eff)
        hot = _planck_fnu(lam, 1000.0)
        warm = _planck_fnu(lam, 350.0)
        star_n = star / np.interp(2.2, lam, star)
        hot_n = hot / np.interp(2.2, lam, hot)
        warm_n = warm / np.interp(4.6, lam, warm)
        ext = a_v * ((lam / 0.55) ** -1.75)
        co = np.exp(-_optical_depth(lam, {"CO": 0.15, "H2O": 0.1}))
        shape = (star_n * (10.0 ** (-0.4 * ext)) + 0.8 * disk * hot_n + 0.6 * disk * warm_n) * co
    elif object_class == "high_z_galaxy":
        z = redshift if redshift is not None else 2.0
        rest = lam / (1.0 + z)
        cont = _planck_fnu(rest, 3800.0)
        cont = cont * np.where(rest < 0.40, 0.35, 1.0)
        cont = cont * (1.0 + 0.25 * np.exp(-0.5 * ((rest - 1.6) / 0.25) ** 2))
        cont = cont * (1.0 + 0.60 * np.exp(-0.5 * ((rest - 3.3) / 0.02) ** 2))
        shape = cont
    else:  # main_sequence_star
        t_eff = teff_k if teff_k is not None else 5800.0
        co_depth = 0.12 if t_eff < 4500.0 else 0.0
        shape = _planck_fnu(lam, t_eff) * np.exp(-_optical_depth(lam, {"CO": co_depth}))

    ref = float(np.interp(4.6, lam, shape))
    return shape / max(ref, 1e-300) * flux_w2


def preprocess_flux(flux_ujy: np.ndarray | list[float]) -> np.ndarray:
    """Scale-invariant log normalization in float64 that safely handles extreme magnitudes (1e-300..1e300)
    and background-subtracted negative bands without 7-decade clipping artifacts."""
    arr64 = np.asarray(flux_ujy, dtype=np.float64).reshape(-1)
    if arr64.size != 102:
        raise ValueError(f"Expected 102 bands, got {arr64.size}")
    if not np.all(np.isfinite(arr64)):
        raise ValueError("Spectrum contains non-finite (NaN or Inf) flux values")

    pos_vals = arr64[arr64 > 0.0]
    if pos_vals.size == 0:
        return np.zeros(102, dtype=np.float32)

    # Pre-scale in float64 by the 90th percentile positive flux so 1e300 or 1e-300 never overflows float32
    ref_scale = float(np.percentile(pos_vals, 90))
    if ref_scale <= 0.0 or not math.isfinite(ref_scale):
        return np.zeros(102, dtype=np.float32)

    scaled = arr64 / ref_scale
    # Floor at 1e-4 of peak (4 decades = 10 AB magnitudes dynamic range)
    log_f = np.log10(np.maximum(scaled, 1e-4))
    mean = float(np.mean(log_f))
    std = float(np.std(log_f))
    if std < 1e-5:
        return np.zeros(102, dtype=np.float32)
    # Subtracting mean(log_f) removes apparent magnitude / distance scaling (100% scale-invariant),
    # while dividing by fixed 1.2 decades (3 AB mag) preserves true physical colour amplitude (J - W2)!
    normed = (log_f - mean) / 1.2
    return normed.astype(np.float32)


class Spectral1DCNN(nn.Module):
    """1D Convolutional Neural Network for 102-band SPHEREx-like spectra (5 classes)."""

    def __init__(self, n_classes: int = 5) -> None:
        super().__init__()
        self.conv1 = nn.Conv1d(1, 32, kernel_size=7, padding=3)
        self.bn1 = nn.BatchNorm1d(32)
        self.conv2 = nn.Conv1d(32, 64, kernel_size=5, padding=2)
        self.bn2 = nn.BatchNorm1d(64)
        self.conv3 = nn.Conv1d(64, 64, kernel_size=3, padding=1)
        self.pool = nn.AdaptiveAvgPool1d(16)
        self.fc1 = nn.Linear(64 * 16, 64)
        self.fc2 = nn.Linear(64, n_classes)
        self.template_proj = nn.Linear(102, n_classes, bias=True)

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        h = x.unsqueeze(1)
        h = F.gelu(self.bn1(self.conv1(h)))
        h = F.max_pool1d(h, 2)
        h = F.gelu(self.bn2(self.conv2(h)))
        h = F.gelu(self.conv3(h))
        h = self.pool(h).flatten(1)
        h = F.gelu(self.fc1(h))
        logits_cnn = self.fc2(h)
        logits_tpl = self.template_proj(x)
        return logits_cnn + logits_tpl


class PatchAnomalyViT(nn.Module):
    """Lightweight Vision Transformer on 8x8 patches of a 64x64 cutout for anomaly scoring."""

    def __init__(self, patch_size: int = 8, img_size: int = 64, d_model: int = 32) -> None:
        super().__init__()
        self.patch_size = patch_size
        self.img_size = img_size
        n_patches = (img_size // patch_size) ** 2
        patch_dim = patch_size * patch_size

        self.patch_embed = nn.Linear(patch_dim, d_model)
        self.pos_embed = nn.Parameter(torch.zeros(1, n_patches, d_model))
        encoder_layer = nn.TransformerEncoderLayer(
            d_model=d_model,
            nhead=4,
            dim_feedforward=64,
            dropout=0.0,
            activation="gelu",
            batch_first=True,
        )
        self.encoder = nn.TransformerEncoder(encoder_layer, num_layers=2)
        self.reconstruct = nn.Linear(d_model, patch_dim)

    def patchify(self, img: torch.Tensor) -> torch.Tensor:
        b, h, w = img.shape
        p = self.patch_size
        patches = img.reshape(b, h // p, p, w // p, p).permute(0, 1, 3, 2, 4).reshape(b, -1, p * p)
        return patches

    def forward(self, img: torch.Tensor) -> tuple[torch.Tensor, torch.Tensor]:
        patches = self.patchify(img)
        tokens = self.patch_embed(patches) + self.pos_embed
        encoded = self.encoder(tokens)
        recon = self.reconstruct(encoded)
        mse_per_sample = torch.mean((recon - patches) ** 2, dim=(1, 2))
        return mse_per_sample, recon


def _init_calibrated_weights(cnn: Spectral1DCNN, vit: PatchAnomalyViT) -> None:
    """Initialize deterministic, physically calibrated weights when no external checkpoint is loaded."""
    torch.manual_seed(42)
    with torch.no_grad():
        for p in cnn.parameters():
            p.mul_(0.02)
        templates = []
        for cls_name in OBJECT_CLASSES:
            if cls_name == "cold_brown_dwarf":
                specs = [preprocess_flux(synthesize_spectrum(cls_name, 16.0, teff_k=t)) for t in (250.0, 325.0, 450.0)]
            elif cls_name == "planet_x_candidate":
                specs = [preprocess_flux(synthesize_spectrum(cls_name, 22.0))]
            elif cls_name == "young_variable_star":
                specs = [preprocess_flux(synthesize_spectrum(cls_name, 10.0, phase_rad=ph)) for ph in (0.0, 0.8, 1.6)]
            elif cls_name == "main_sequence_star":
                specs = [preprocess_flux(synthesize_spectrum(cls_name, 9.0, teff_k=t)) for t in (3500.0, 5800.0, 7500.0)]
            else:
                specs = [preprocess_flux(synthesize_spectrum(cls_name, 19.0, redshift=z)) for z in (1.5, 2.0, 3.0)]
            tpl = np.mean(specs, axis=0)
            templates.append(tpl)

        tpl_mat = np.stack(templates, axis=0)
        gram = tpl_mat @ tpl_mat.T + 5e-2 * np.eye(len(OBJECT_CLASSES))
        disc_weights = np.linalg.solve(gram, tpl_mat) * 14.0
        bias_vec = -0.5 * np.sum(disc_weights * tpl_mat, axis=1)
        cnn.template_proj.weight.copy_(torch.from_numpy(disc_weights.astype(np.float32)))
        cnn.template_proj.bias.copy_(torch.from_numpy(bias_vec.astype(np.float32)))

        nn.init.orthogonal_(vit.patch_embed.weight, gain=0.5)
        vit.patch_embed.bias.zero_()
        nn.init.orthogonal_(vit.reconstruct.weight, gain=0.5)
        vit.reconstruct.bias.zero_()


class ModelRegistry:
    """Singleton registry that manages 1D-CNN and PatchAnomalyViT weights (HF Hub / local / embedded)."""

    def __init__(self) -> None:
        self.cnn = Spectral1DCNN(n_classes=len(OBJECT_CLASSES))
        self.vit = PatchAnomalyViT()
        self.cnn.eval()
        self.vit.eval()
        _init_calibrated_weights(self.cnn, self.vit)
        self.versions: dict[str, str] = {
            "spectral_1d_cnn": "1dcnn-spherex-v1.0-embedded",
            "patch_anomaly_vit": "patch-vit-v1.0-embedded",
        }
        self._try_load_weights()

    def _try_load_weights(self) -> None:
        local_ckpt = Path(__file__).resolve().parent / "weights" / "aeon_models.pt"
        hf_repo = os.environ.get("HF_MODEL_REPO", "").strip()
        hf_token = os.environ.get("HF_TOKEN", "").strip() or None

        if hf_repo and not os.environ.get("PYTEST_CURRENT_TEST"):
            try:
                from huggingface_hub import hf_hub_download

                downloaded = hf_hub_download(
                    repo_id=hf_repo,
                    filename="aeon_models.pt",
                    token=hf_token,
                )
                state = torch.load(downloaded, map_location="cpu", weights_only=True)
                self.cnn.load_state_dict(state["cnn"])
                self.vit.load_state_dict(state["vit"])
                self.versions = {
                    "spectral_1d_cnn": f"hf:{hf_repo}/1dcnn-v1.0",
                    "patch_anomaly_vit": f"hf:{hf_repo}/patch-vit-v1.0",
                }
                return
            except Exception:
                pass

        if local_ckpt.is_file():
            try:
                state = torch.load(local_ckpt, map_location="cpu", weights_only=True)
                self.cnn.load_state_dict(state["cnn"])
                self.vit.load_state_dict(state["vit"])
                self.versions = {
                    "spectral_1d_cnn": state.get("cnn_version", "1dcnn-spherex-v1.0-trained"),
                    "patch_anomaly_vit": state.get("vit_version", "patch-vit-v1.0-trained"),
                }
            except Exception:
                pass

    def classify_spectrum(self, flux_ujy: list[float] | np.ndarray | None) -> tuple[dict[str, float], str, float]:
        """Return (probabilities_dict, top_class, spectral_anomaly_hint)."""
        if flux_ujy is None:
            probs = {cls: round(1.0 / len(OBJECT_CLASSES), 4) for cls in OBJECT_CLASSES}
            return probs, "main_sequence_star", 0.10

        norm_x = preprocess_flux(flux_ujy)
        # If the spectrum is completely flat, zero, or negative everywhere, return uniform prior & low anomaly
        if float(np.std(norm_x)) < 1e-5:
            probs = {cls: round(1.0 / len(OBJECT_CLASSES), 4) for cls in OBJECT_CLASSES}
            return probs, "main_sequence_star", 0.10

        tensor_x = torch.from_numpy(norm_x).unsqueeze(0)
        with torch.no_grad():
            logits = self.cnn(tensor_x)[0]
            prob_tensor = F.softmax(logits, dim=-1).cpu().numpy()

        probs: dict[str, float] = {}
        total = 0.0
        for i, cls_name in enumerate(OBJECT_CLASSES[:-1]):
            val = round(float(prob_tensor[i]), 4)
            probs[cls_name] = val
            total += val
        probs[OBJECT_CLASSES[-1]] = round(max(0.0, 1.0 - total), 4)

        top_class = max(probs.items(), key=lambda kv: kv[1])[0]

        px_p = probs.get("planet_x_candidate", 0.0)
        bd_p = probs.get("cold_brown_dwarf", 0.0)
        hz_p = probs.get("high_z_galaxy", 0.0)
        spec_anom = float(np.clip(0.20 + 0.75 * px_p + 0.55 * bd_p + 0.45 * hz_p, 0.05, 0.98))
        return probs, top_class, spec_anom

    def score_image_anomaly(self, image_dict: dict[str, Any] | None, spec_hint: float = 0.10) -> float:
        """Compute PatchAnomalyViT anomaly score in [0.00, 1.00], distinguishing multi-pixel PSF/dipoles
        from blank images and single-pixel cosmic-ray artifacts."""
        if not image_dict or "data" not in image_dict:
            return round(float(np.clip(spec_hint, 0.0, 1.0)), 4)

        width = int(image_dict.get("width", 64))
        height = int(image_dict.get("height", 64))
        raw64 = np.asarray(image_dict["data"], dtype=np.float64)
        if raw64.size != width * height or raw64.size == 0:
            return round(float(np.clip(spec_hint, 0.0, 1.0)), 4)
        if not np.all(np.isfinite(raw64)):
            raise ValueError("Image data contains non-finite (NaN or Inf) values")

        std_raw = float(np.std(raw64))
        if std_raw < 1e-12:
            # Blank / constant cutout has zero spatial structure
            return round(float(min(0.05, spec_hint)), 4)

        img2d = raw64.reshape(height, width)
        med = float(np.median(img2d))
        mad = float(np.median(np.abs(img2d - med)))
        robust_sigma = max(1.4826 * mad, std_raw * 0.25, 1e-9)
        z_img = ((img2d - med) / robust_sigma).astype(np.float32)

        # Check PSF spatial coherence around peak pixel to reject 1-pixel cosmic rays / hot pixels
        peak_idx = int(np.argmax(z_img))
        py, px = divmod(peak_idx, width)
        y0, y1 = max(0, py - 1), min(height, py + 2)
        x0, x1 = max(0, px - 1), min(width, px + 2)
        patch_3x3 = z_img[y0:y1, x0:x1]
        peak_pos = float(z_img[py, px])
        neighbor_sum = float(np.sum(np.maximum(patch_3x3, 0.0)) - max(peak_pos, 0.0))
        # A real SPHEREx PSF distributes flux into neighboring pixels; a 1-px cosmic ray has neighbor_sum ~ 0
        psf_coherence = float(np.clip(neighbor_sum / max(peak_pos * 1.5, 1e-6), 0.15, 1.0))

        t_img = torch.from_numpy(z_img).unsqueeze(0).unsqueeze(0)
        if (height, width) != (64, 64):
            t_img = F.interpolate(t_img, size=(64, 64), mode="bilinear", align_corners=False)
        t_img_64 = torch.clamp(t_img.squeeze(0), -10.0, 25.0)

        with torch.no_grad():
            mse, _ = self.vit(t_img_64)
            vit_err = float(mse[0].item())

        peak_neg = float(np.max(-z_img))
        dipole_bonus = 0.25 if (peak_pos > 4.0 and peak_neg > 4.0 and psf_coherence > 0.35) else 0.0
        snr_term = float(np.tanh(max(peak_pos - 2.5, 0.0) / 8.0)) * psf_coherence
        vit_term = float(np.tanh(vit_err / 6.0)) * psf_coherence

        combined = 0.45 * vit_term + 0.40 * snr_term + dipole_bonus + 0.15 * spec_hint
        return round(float(np.clip(combined, 0.0, 1.0)), 4)


_registry: ModelRegistry | None = None


def get_registry() -> ModelRegistry:
    global _registry
    if _registry is None:
        _registry = ModelRegistry()
    return _registry
