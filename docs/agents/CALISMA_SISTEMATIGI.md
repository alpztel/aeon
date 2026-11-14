# AEON — Çok Ajanlı Çalışma Sistematiği

Bu belge, 3 bilgisayar ve 3 AI ajanının **aynı repoda çakışmadan** nasıl çalışacağını adım adım
tanımlar. Kurallar `AGENTS.md`'de, teknik sözleşme `openapi.json`'da, kapsam `PROJECT_SPEC.xml`'dedir.
Bu belge "kim, nerede, ne zaman, nasıl" sorusunu cevaplar.

---

## 1. Kim, hangi dalda, hangi klasörde?

| Node | Kişi(ler) | Ajan | Git dalı | Yazabileceği klasörler | Servis / port |
|------|-----------|------|----------|------------------------|---------------|
| 1 | Alperen (`@alpztel`, lider) | Claude Code | `agent/claude-leader-backend` | `backend/` | core API · `8000` |
| 2 | Mucteba Özdemir | Antigravity 1 | `agent/ag1-frontend` | `frontend/`, `docs-and-reports/` | Next.js · `3000` (Vercel) |
| 3 | Ece, Filiz, Asya | Antigravity 2 | `agent/ag2-ai-missions` | `ai-engine/`, `multi-mission-api/` | `8100` ve `8200` |
| — | Lider | — | `lead/*` | kök dosyalar, `.github/`, `deploy/`, `docs/` | — |

**Repo:** `https://github.com/alpztel/aeon` · **Ana dal:** `main` (korumalı)

### Klasör ağacı ve sahiplik

```
aeon/
├── AGENTS.md, PROJECT_SPEC.xml, openapi.json, README.md   ← Lider (yalnız PR ile)
├── .github/ (CODEOWNERS, workflows/ci-guard.yml)          ← Lider
├── deploy/ (docker-compose.yml, nginx.conf)                ← Lider
├── docs/agents/ (bu belge ve ajan promptları)              ← Lider
├── backend/            ← Node 1 · Claude Code
├── frontend/           ← Node 2 · Antigravity 1
├── docs-and-reports/   ← Node 2 · Antigravity 1
├── ai-engine/          ← Node 3 · Antigravity 2
└── multi-mission-api/  ← Node 3 · Antigravity 2
```

---

## 2. `openapi.json` uç noktaları kimin?

| # | Yol | Sahip | Kullanan |
|---|-----|-------|----------|
| 1 | `GET /api/v1/health` | backend | frontend |
| 2 | `GET /api/v1/catalog/search` | backend | frontend, ai-engine |
| 3 | `GET /api/v1/sky/cutout` | backend | frontend, ai-engine (ViT) |
| 4 | `GET /api/v1/spectrum` | backend | frontend, ai-engine (CNN) |
| 5 | `POST /api/v1/analysis/{difference\|shift-stack\|blind-search}` | backend | frontend, ai-engine |
| 6 | `POST /api/v1/orbit/simulate` | backend | frontend |
| 7 | `POST /api/v1/ai/command` | ai-engine | frontend |
| 8 | `POST /api/v1/ai/classify` | ai-engine | frontend, multi-mission-api |
| 9 | `GET /api/v1/missions/crossmatch` | multi-mission-api | frontend |
| 10 | `GET /api/v1/alerts/gcn` | multi-mission-api | frontend |
| 11 | `GET`/`POST /api/v1/candidates` | multi-mission-api | frontend |

Tek bir ağ geçidi (`deploy/nginx.conf`) yolları servislere dağıtır:
`/api/v1/ai/*` → ai-engine:8100 · `/api/v1/missions|alerts|candidates` → multi-mission-api:8200 · geri kalanı → backend:8000.

---

## 3. Her ajanın günlük döngüsü

```bash
# 0) İlk kez (bir defa)
git clone https://github.com/alpztel/aeon.git && cd aeon
git checkout -b agent/<kendi-dalın>          # ör. agent/ag1-frontend
git push -u origin agent/<kendi-dalın>

# 1) Her çalışma oturumunun başında: main'deki yenilikleri al
git fetch origin
git merge origin/main                         # (çakışma olmaz: başkasının klasörüne dokunmuyorsun)

# 2) Yalnız kendi klasöründe kod yaz

# 3) Doğrula (exit code 0 olmadan commit YOK)
#    frontend:  cd frontend && npm run lint && npm run build
#    python:    cd <klasör> && pytest -q

# 4) Commit + push (kendi dalına)
git add <kendi-klasörün>/
git commit -m "feat(frontend): ..."           # conventional commits
git push

# 5) Bir özellik bittiğinde: PR aç
gh pr create --base main --head agent/<kendi-dalın> --title "feat(...): ... (M#)"
```

**Birleştirme:** PR'ları yalnız lider `main`'e birleştirir. Bir PR'ın birleşebilmesi için ci-guard'ın
6 kontrolünün tamamı yeşil olmalı ve dal `main` ile güncel olmalıdır ("Update branch" ya da `git merge origin/main`).

---

## 4. Otomatik koruma (CI) ne yapar?

`.github/workflows/ci-guard.yml` her `agent/**` push'unda ve her `main` PR'ında çalışır:

| Kontrol | Ne yapar | Ne zaman kırmızı olur |
|---------|----------|------------------------|
| Folder isolation | Değişen dosyaları dalın izinli klasörleriyle karşılaştırır | Başka ekibin klasörüne veya kök dosyaya dokunduysan |
| openapi.json is valid | Sözleşmeyi doğrular, tam 11 yol olmasını kontrol eder | Sözleşme bozulduysa |
| backend pytest | `backend/` testleri | Backend testi kırıldıysa |
| frontend lint + build | `npm ci && npm run lint && npm run build` | `frontend/package.json` varsa ve derleme başarısızsa |
| ai-engine pytest | `ai-engine/requirements.txt` varsa `pytest -q` | Test kırıldıysa |
| multi-mission-api pytest | aynısı | Test kırıldıysa |

Bilinmeyen bir `agent/*` dal adı CI'da reddedilir. Yeni dal gerekiyorsa liderden `ci-guard.yml`'ye eklemesini iste.

---

## 5. Ekipler arası iletişim

- **Sözleşme değişikliği gerekiyorsa** (yeni alan, yeni parametre): kod yazmadan önce GitHub'da
  `contract` etiketli bir Issue aç. Lider `lead/contract-*` dalında `openapi.json`'u günceller, PR ile `main`'e alır,
  sonra herkes `git merge origin/main` yapar.
- **Başka ekibin servisi henüz yoksa:** sözleşmedeki örnek şemaya uyan bir yerel taklit (mock) yaz,
  ama bunu yalnız geliştirme/test için kullan ve arayüzde "çevrimdışı" rozetiyle göster.
- **Hata bulduysan başka ekibin kodunda:** düzeltme. Issue aç, ilgili ekibi etiketle.

---

## 6. Ortak sözlük (her ajan aynı birimleri kullanır)

- Koordinat: ICRS derece (`ra` 0–360, `dec` −90…+90). Özdevinim ″/yıl, konum açısı kuzeyden doğuya derece.
- Dönemler: `2026-Q1`…`2026-Q4` = 2026.125 / .375 / .625 / .875 ondalık yıl.
- Akı: µJy · dalga boyu: µm · uzaklık: AU (Güneş Sistemi) veya pc (yıldız).
- JSON görüntü: satır-öncelikli düz dizi, 0. satır = güney kenarı, kuzey yukarı, doğu solda.
- Sınıflar: `cold_brown_dwarf`, `planet_x_candidate`, `young_variable_star`, `main_sequence_star`, `high_z_galaxy`.
- Demo hedef kimlikleri: `wise-0855`, `rw-aur`, `px-2026-09` (**sentetik** — her yerde öyle etiketlenir).

---

## 7. Zaman çizelgesi (önerilen)

| Aşama | Node 1 (backend) | Node 2 (frontend) | Node 3 (AI + görevler) |
|-------|------------------|-------------------|------------------------|
| 1 | ✅ Çekirdek API (birleşti) · Gerçek SPHEREx verisi (IRSA) | İskelet, tasarım sistemi, TR/EN, harita + zaman çizelgesi | ai-engine + multi-mission-api iskeletleri, Dockerfile'lar, testler |
| 2 | DigitalOcean kurulumu, `api.aeon.tech` | Tayf paneli, fark modu, shift-stack paneli | Gaia/WISE/MAST eşleştirme, GCN, aday havuzu |
| 3 | Performans, önbellek | 3D sahne, JWST PiP, Cmd+K | Astro-LLM, 1D-CNN, ViT, HF Space |
| 4 | Entegrasyon testleri, tüm PR'lar | PDF rapor, Jüri Demo Turu, Vercel | GitHub Issue botu, son testler |

Her aşamanın sonunda ilgili dal için bir PR açılır; lider birleştirir; herkes `main`'i kendi dalına alır.
