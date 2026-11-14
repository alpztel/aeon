# ANTIGRAVITY 2 — AI & ÇOKLU GÖREV AJANI PROMPTU (Node 3 · Ece, Filiz, Asya)

> Bu metnin tamamını Antigravity 2'ye ilk mesaj olarak ver. Ajan her yeni oturumda bu dosyayı,
> `AGENTS.md`, `PROJECT_SPEC.xml`, `openapi.json` ve `docs/agents/CALISMA_SISTEMATIGI.md` dosyalarını yeniden okumalıdır.

---

## 0. Kimliğin ve sınırların

Sen **AEON** projesinin **yapay zeka ve çoklu görev (multi-mission) ajanısın** (Node 3, Antigravity 2).
AEON, NASA Space Apps Challenge 2026 "Planet X and SPHEREx" kategorisi için geliştirilen açık kaynaklı bir
astrofizik keşif işletim sistemidir.

- **Repo:** `https://github.com/alpztel/aeon`
- **Dalın:** `agent/ag2-ai-missions` — yalnız bu dalda çalış, `main`'e asla doğrudan push etme.
- **Yazabileceğin klasörler:** yalnız `ai-engine/` ve `multi-mission-api/`.
- **Dokunmayacağın her şey:** `backend/`, `frontend/`, `docs-and-reports/`, kök dosyalar, `.github/`, `deploy/`, `docs/`.
  Dokunursan CI ("Folder isolation") push'u reddeder. İhtiyaç varsa GitHub Issue aç.
- **Sözleşme:** `openapi.json` donmuştur. Senin yolların: `/api/v1/ai/command`, `/api/v1/ai/classify`
  (ai-engine) ve `/api/v1/missions/crossmatch`, `/api/v1/alerts/gcn`, `/api/v1/candidates` (multi-mission-api).
  Alan adları, birimler (µJy, µm, derece) ve enum'lar birebir aynı olmalı.

## 1. Kurulum

```bash
git clone https://github.com/alpztel/aeon.git && cd aeon
git checkout -b agent/ag2-ai-missions
git push -u origin agent/ag2-ai-missions
python -m venv C:\venvs\aeon-ai        # Windows'ta KISA yol şart (astropy 260 karakter sınırı)
```

İki ayrı FastAPI servisi kuracaksın. Her biri kendi klasöründe şunları içermeli (CI ve `deploy/docker-compose.yml` bunları bekler):

```
ai-engine/                         multi-mission-api/
├── requirements.txt               ├── requirements.txt
├── Dockerfile   (port 8100)       ├── Dockerfile   (port 8200)
├── app/main.py  (FastAPI)         ├── app/main.py
├── tests/       (pytest)          ├── tests/
├── .env.example                   ├── .env.example
└── README.md                      └── README.md
```

- `Dockerfile` son satırı: `CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8100"]` (diğeri 8200).
- CORS: `https://aeon.tech`, `http://localhost:3000`, `https://*.vercel.app`.
- Her servis `GET /healthz` (sözleşme dışı, yalnız Docker sağlık kontrolü için) sunabilir.
- Core backend'e (`backend/`) **HTTP ile** eriş: ortam değişkeni `AEON_CORE_URL` (yerelde `http://localhost:8000`,
  Docker'da `http://backend:8000`). Backend kodunu import etme veya kopyalama.
- Testler **internetsiz ve anahtarsız** geçmeli: dış servisleri (LLM, Gaia, IRSA, MAST, GCN, MongoDB, GitHub) testte
  `respx`/`pytest-httpx`, `mongomock` vb. ile taklit et. CI'da gizli anahtar yoktur.

---

## 2. `ai-engine/` (port 8100)

### 2.1 `POST /api/v1/ai/command` — Astro-LLM (Function Calling)

Kullanıcının TR/EN doğal dil komutunu **UI aksiyonlarına** çevirir. Yanıt: `{reply, lang, actions[]}`.
Aksiyon tipleri `openapi.json` → `UiAction.type` enum'u ile birebir aynıdır:
`FLY_TO, SET_EPOCH, TOGGLE_DIFF, RUN_SHIFT_STACK, RUN_BLIND_SEARCH, OPEN_SPECTRUM, OPEN_3D_ORBIT, OPEN_JWST,
OPEN_CROSSMATCH, SET_COLORMAP, SET_LANG, GENERATE_PDF, START_DEMO_TOUR`.

**LLM sağlayıcısı (önerilen):** Anthropic Claude, resmi `anthropic` Python SDK'sı ile.
- Model: ortam değişkeni `AEON_LLM_MODEL`, varsayılan `claude-opus-5-5`. Anahtar: `ANTHROPIC_API_KEY` (yalnız sunucuda).
- Her UI aksiyonunu bir **tool** olarak tanımla (`input_schema` + `strict: true` + `additionalProperties: false`).
  Ek olarak bilgi araçları ekle: `search_catalog` (→ `AEON_CORE_URL/api/v1/catalog/search`), `get_spectrum`,
  `crossmatch`. Bu bilgi araçlarını sunucuda çalıştırıp sonucu `tool_result` olarak modele geri ver; UI araçlarını
  ise çalıştırmadan `actions` dizisine ekle.
- `tool_choice` için yalnız `{"type": "auto"}` kullan (bu modelde `any`/`tool` zorlaması 400 döner); hangi aracı
  kullanacağını sistem promptunda açıkça yönlendir.
- Hız için `output_config: {"effort": "low"}`; `thinking` parametresini gönderme (varsayılan adaptive).
  `temperature`/`top_p` gönderme.
- Yanıtta önce `stop_reason`'ı kontrol et; `refusal` ise kibar bir TR/EN mesajla boş `actions` döndür.
- SDK fonksiyon adlarını tahmin etme; resmi SDK belgelerine/README'sine bakarak yaz.
- Sistem promptu kısa ve sabit olsun (önbelleğe alınabilir): AEON'un ne olduğu, demo hedefleri
  (`wise-0855`, `rw-aur`, `px-2026-09` = sentetik), koordinat/birim kuralları, "uydurma koordinat verme, önce
  `search_catalog` çağır".

**Anahtarsız yedek (zorunlu):** `ANTHROPIC_API_KEY` yoksa veya LLM hata verirse kural tabanlı bir TR/EN
ayrıştırıcı devreye girer (anahtar kelimeler: "git/uç/fly/go to", "fark/difference", "yığ/stack", "kör tarama/blind",
"tayf/spectrum", "yörünge/orbit/3d", "jwst/hubble", "rapor/pdf/report", "demo/tur", "Q1–Q4", isim veya RA/Dec deseni).
Yanıtta `reply` içinde hangi modun kullanıldığını belirt. En az 20 TR + 20 EN örnek komutla test yaz
(ör. "WISE 0855'e git ve fark modunu aç" → `[FLY_TO, TOGGLE_DIFF]`).

### 2.2 `POST /api/v1/ai/classify` — 1D-CNN + PatchAnomalyViT

- **1D-CNN tayf sınıflandırıcı** (PyTorch): girdi 102 bant akı (µJy) → log-normalize; çıktı 5 sınıf olasılığı
  (`cold_brown_dwarf, planet_x_candidate, young_variable_star, main_sequence_star, high_z_galaxy`).
- **PatchAnomalyViT**: girdi `Image` (ör. 64×64 kesit) → 8×8 yamalar → küçük ViT; çıktı `anomaly_score` 0.00–1.00
  (ör. maskeli yama yeniden-oluşturma hatası veya yoğunluk tahmini).
- **Eğitim verisi:** `AEON_CORE_URL`'deki `/api/v1/spectrum`, `/api/v1/sky/cutout`, `/api/v1/catalog/search?include_field=true`
  ve `/api/v1/analysis/*` uç noktalarından üretilen fiziksel model verisi + gürültü/kırmızıya kayma/sönümleme
  augmentasyonu. Veri üretim script'i `ai-engine/training/` altında, tekrar üretilebilir (seed sabit).
  **Model kartında açıkça yaz:** "simüle edilmiş SPHEREx-benzeri veriyle eğitildi".
- Ağırlıklar küçük tutulsun (< 20 MB); repoda değil **Hugging Face Hub**'da sakla, servis açılışta indirsin
  (`HF_MODEL_REPO`, isteğe bağlı `HF_TOKEN`); indirilemezse testlerde kullanılan küçük gömülü sürüme düş.
  `model_versions` alanında sürümleri döndür.
- **Hugging Face Space:** `ai-engine/hf-space/` altında Gradio/FastAPI tabanlı herkese açık demo (tayf yükle → sınıf).
- Doğruluk raporu: ayrılmış test kümesinde karışıklık matrisi + sınıf başına F1, `ai-engine/MODEL_CARD.md`'ye.

---

## 3. `multi-mission-api/` (port 8200)

### 3.1 `GET /api/v1/missions/crossmatch?ra&dec&radius_arcsec`

- **Gaia DR3** (ESA Gaia arşivi TAP, `astroquery.gaia`): G, BP, RP, paralaks, özdevinim.
- **WISE / CatWISE2020 / AllWISE** (IRSA, `astroquery.ipac.irsa`): W1–W4 (3.4, 4.6, 12, 22 µm).
- **MAST** (`astroquery.mast`): koordinatta JWST/HST gözlemi varsa `mast_overlap[]` (mission, obs_id, instrument,
  filter, preview_url).
- **SED:** Gaia + WISE fotometrisini µJy'ye çevir (Vega→AB sıfır noktalarını belgele), SPHEREx için
  `AEON_CORE_URL/api/v1/spectrum` sonucunu ekle → `sed[]` (survey alanıyla).
- **`unmatched_ir_candidate`:** WISE/SPHEREx'te kaynak var ama `radius_arcsec` içinde Gaia karşılığı yoksa `true`.
- Ağ yavaşsa/yoksa: istek başına zaman aşımı (≤ 8 sn), sonuçları önbelleğe al (diskte JSON, 24 saat). Demo hedefleri
  için **gerçek arşiv sorgularının kaydedilmiş sonuçlarını** `multi-mission-api/fixtures/` altında sakla (kaynak ve
  sorgu tarihi ile). Değer uydurma yok. `px-2026-09` sentetik olduğundan arşiv eşleşmesi beklenmez; bunu yanıtta belirt.

### 3.2 `GET /api/v1/alerts/gcn?limit=20`

- Tercihen **NASA GCN Kafka** (`gcn-kafka` paketi; `GCN_CLIENT_ID`, `GCN_CLIENT_SECRET`) — arka planda dinle,
  son N uyarıyı bellekte tut.
- Kimlik bilgisi yoksa: NASA GCN Circulars arşivini periyodik çek. Hiçbiri yoksa son başarılı kaydı döndür ve
  `title` alanında "önbellek" olduğunu belirt.
- Alanlar: `id, kind (GRB/SN/neutrino/GW…), time_utc, ra, dec, error_radius_deg, title, url`.

### 3.3 `GET`/`POST /api/v1/candidates` — Yurttaş bilimi aday havuzu

- **MongoDB Atlas** (`MONGODB_URI`, veritabanı `aeon`, koleksiyon `candidates`; `motor` veya `pymongo`).
  URI yoksa bellek içi depo (testlerde `mongomock`).
- `GET`: `sort=votes|recent|anomaly`, `limit`. `POST`: `action=submit` (yeni aday) veya `action=vote` (`candidate_id`).
- Aynı koordinata (≤ 3″) ikinci gönderim yeni kayıt açmaz, mevcut kaydı döndürür. IP başına basit hız sınırı.
- Gönderilen adayı `AEON_CORE_URL/api/v1/spectrum` + ai-engine `/api/v1/ai/classify` ile zenginleştir
  (`object_class`, `anomaly_score`).

### 3.4 Otonom GitHub Issue keşif botu

- Koşul: `anomaly_score ≥ 0.90` **ve** `snr ≥ 5` **ve** aynı koordinat için açık issue yok.
- `GITHUB_TOKEN` (yalnız `alpztel/aeon` için *Issues: write* yetkili fine-grained token), `GITHUB_REPO=alpztel/aeon`.
- Issue: başlık `[Keşif adayı] AEON J{ra}{dec} — {sınıf}`, Markdown gövdede koordinat, S/N, anomali skoru, sınıf
  olasılıkları, Gaia/WISE eşleşmesi, AEON bağlantısı; etiketler `discovery`, `automated`.
  Sentetik nesneler için ek etiket `synthetic-test` ve gövdede açık uyarı.
- `GITHUB_TOKEN` yoksa bot yalnız log yazar (hata vermez). Testte GitHub API'si taklit edilir.
- `github_issue_url` aday kaydına yazılır.

---

## 4. Gizli bilgiler

Tüm anahtarlar ortam değişkenidir; `.env.example` dosyalarında yalnız adları listelenir:
`ANTHROPIC_API_KEY, AEON_LLM_MODEL, AEON_CORE_URL, HF_MODEL_REPO, HF_TOKEN, MONGODB_URI, GCN_CLIENT_ID,
GCN_CLIENT_SECRET, GITHUB_TOKEN, GITHUB_REPO`. Sunucuda `deploy/.env` dosyasını lider doldurur. Hiçbir anahtar commit'lenmez.

## 5. Doğrulama ve teslim döngüsü (her değişiklikte)

```bash
cd ai-engine && pytest -q && cd ..
cd multi-mission-api && pytest -q && cd ..
docker build -t aeon-ai ai-engine && docker build -t aeon-missions multi-mission-api   # Docker varsa
git fetch origin && git merge origin/main
git add ai-engine multi-mission-api
git commit -m "feat(ai-engine): <ne yaptın> (M#)"
git push
```

Testlerde her yanıtı `openapi.json`'daki şemaya karşı doğrula (backend'deki `backend/tests/conftest.py`
içindeki `assert_schema` yaklaşımını örnek al ama kopyalamak yerine kendi klasöründe yeniden yaz).
Bir modül grubu bitince `gh pr create --base main --head agent/ag2-ai-missions` ile PR aç. Birleştirmeyi lider yapar.

## 6. Kesin yasaklar

- Uydurma katalog değeri, sahte eşleşme, sahte GCN uyarısı, sahte model doğruluğu.
- Başka klasöre dokunmak, `main`'e push, `openapi.json`'u değiştirmek.
- Anahtar/gizli bilgi commit'lemek; testlerin internete veya gerçek anahtara bağımlı olması.
- Sentetik nesne için gerçek keşif issue'su açmak (her zaman `synthetic-test` etiketi).

## 7. İlk görevin (bugün)

1. İki servisin iskeleti: FastAPI uygulaması, `requirements.txt`, `Dockerfile`, `.env.example`, README, pytest.
2. Sözleşmedeki 5 yolu şemaya uygun yanıtlarla ayağa kaldır: `ai/command` (önce kural tabanlı yedek),
   `ai/classify` (önce basit, belgelenmiş sezgisel temel çizgi; sonra CNN/ViT), `missions/crossmatch`
   (önce demo fikstürleri + canlı Gaia sorgusu), `alerts/gcn`, `candidates` (bellek içi depo).
3. `pytest -q` iki klasörde de yeşil → commit → push → CI yeşil → ilk PR.
