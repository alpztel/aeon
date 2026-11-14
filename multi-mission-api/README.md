# AEON `multi-mission-api` (Port 8200)

AEON'un çoklu görev çapraz eşleştirme, NASA GCN uyarı akışı, yurttaş bilimi aday havuzu ve otonom GitHub Issue keşif botu servisi (**Node 3 · Antigravity 2**).

## Uç Noktalar (Endpoints)

- `GET /api/v1/missions/crossmatch?ra&dec&radius_arcsec` — **Gaia DR3 + WISE + MAST Eşleştirme ve SED (M6 & M7)**
  - Gaia DR3 ($G, G_{\text{BP}}, G_{\text{RP}}$) ve WISE ($W1\text{–}W4$) Vega büyüklüklerini belgelenmiş sıfır noktalarıyla AB büyüklüğüne ve $\mu\text{Jy}$ akıya çevirir; `AEON_CORE_URL/api/v1/spectrum` verisiyle birleştirerek `0.4–22 µm` `sed[]` dizisini oluşturur.
  - WISE/SPHEREx'te kaynak olup `radius_arcsec` içinde Gaia DR3 karşılığı yoksa `unmatched_ir_candidate: true` döndürür.
  - JWST ve HST arşiv çakışmalarını `mast_overlap[]` içinde döndürür.
  - Demo hedefleri (`wise-0855`, `rw-aur`, sentetik `px-2026-09`) için gerçek arşiv sorgu kayıtları `fixtures/crossmatch_fixtures.json` altındadır.
- `GET /api/v1/alerts/gcn?limit=20` — **NASA GCN Uyarı Akışı (M10)**
  - GCN Kafka / Circulars uyarılarını sunar; çevrimdışı durumda `fixtures/gcn_alerts.json` önbelleğine düşer ve `title` alanında önbellek olduğunu belirtir.
- `GET` / `POST /api/v1/candidates` — **Yurttaş Bilimi Aday Havuzu & Otonom GitHub Issue Botu (M10 & M11)**
  - `MONGODB_URI` tanımlıysa MongoDB Atlas (`aeon.candidates`), değilse `mongomock` bellek içi koleksiyon kullanır.
  - $\le 3''$ açısal uzaklıktaki mükerrer gönderimleri tekilleştirir.
  - `anomaly_score >= 0.90` ve `snr >= 5.0` koşulunu sağlayan adaylar için `alpztel/aeon` reposunda otomatik GitHub Issue açar (`discovery`, `automated` etiketleri; sentetik adaylar için zorunlu `synthetic-test` etiketi).

## Çalıştırma ve Test

```bash
cd multi-mission-api
pip install -r requirements.txt
pytest -q
uvicorn app.main:app --host 0.0.0.0 --port 8200
```
