# AEON `ai-engine` (Port 8100)

AEON'un yapay zeka mikroservisi (**Node 3 · Antigravity 2**). `openapi.json` sözleşmesindeki `/api/v1/ai/*` uç noktalarını sunar.

## Uç Noktalar (Endpoints)

- `POST /api/v1/ai/command` — **Astro-LLM Komut Ayrıştırıcı (M8)**
  - `ANTHROPIC_API_KEY` tanımlı olduğunda resmi `anthropic` SDK (`AEON_LLM_MODEL`, varsayılan `claude-opus-5-5`, `tool_choice={"type": "auto"}`, `output_config={"effort": "low"}`) ile çalışır.
  - Anahtar olmadığında veya ağ hatasında deterministik **TR/EN kural tabanlı ayrıştırıcıya** düşer ve 13 `UiAction` tipinin tamamını destekler.
  - Sentetik test hedefi `px-2026-09` için yanıtta açıkça `is_synthetic=true` uyarısı verir.
- `POST /api/v1/ai/classify` — **1D-CNN Tayf Sınıflandırıcı & PatchAnomalyViT (M9)**
  - **1D-CNN:** 102 bantlık SPHEREx-benzeri yakın-kızılötesi akıyı (`flux_ujy`) log-normalize ederek 5 astrofiziksel sınıfa (`cold_brown_dwarf`, `planet_x_candidate`, `young_variable_star`, `main_sequence_star`, `high_z_galaxy`) ayırır.
  - **PatchAnomalyViT:** Görüntü kesitini (`Image`, 8×8 yamalar) inceleyerek `0.00–1.00` aralığında `anomaly_score` üretir.
- `GET /healthz` — Docker sağlık kontrolü.

## Çalıştırma ve Test

```bash
cd ai-engine
pip install -r requirements.txt
pytest -q
uvicorn app.main:app --host 0.0.0.0 --port 8100
```
