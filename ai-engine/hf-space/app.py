"""Hugging Face Space demo app for AEON 1D-CNN & PatchAnomalyViT (Gradio / FastAPI compatible)."""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.models import OBJECT_CLASSES, get_registry, synthesize_spectrum  # noqa: E402


def predict_from_json_or_preset(preset_class: str = "cold_brown_dwarf", custom_flux_json: str = "") -> dict:
    reg = get_registry()
    if custom_flux_json.strip():
        flux = json.loads(custom_flux_json)
    else:
        cls_name = preset_class if preset_class in OBJECT_CLASSES else "cold_brown_dwarf"
        flux = synthesize_spectrum(cls_name, mag_ab_w2=16.5).tolist()
    probs, top_class, spec_hint = reg.classify_spectrum(flux)
    anomaly = reg.score_image_anomaly(None, spec_hint=spec_hint)
    return {
        "top_class": top_class,
        "probabilities": probs,
        "anomaly_score": anomaly,
        "model_versions": reg.versions,
        "training_note": "Simüle edilmiş SPHEREx-benzeri 102-bant veriyle eğitildi / Trained on simulated SPHEREx-like 102-band data.",
    }


if __name__ == "__main__":
    try:
        import gradio as gr

        demo = gr.Interface(
            fn=predict_from_json_or_preset,
            inputs=[
                gr.Dropdown(choices=list(OBJECT_CLASSES), value="cold_brown_dwarf", label="Preset SPHEREx Template"),
                gr.Textbox(lines=4, placeholder="[12.3, 14.1, ... 102 flux values in uJy]", label="Custom 102-band Flux JSON (uJy)"),
            ],
            outputs=gr.JSON(label="AEON 1D-CNN + PatchAnomalyViT Output"),
            title="AEON — 102-Band SPHEREx Spectral Classifier & Anomaly Scorer",
            description="Simüle edilmiş SPHEREx-benzeri 102 bantlık yakın-kızılötesi (0.75–5.0 µm) veriyle eğitilmiş 1D-CNN ve PatchAnomalyViT demosu.",
        )
        demo.launch()
    except ImportError:
        print(json.dumps(predict_from_json_or_preset("planet_x_candidate"), indent=2, ensure_ascii=False))
