# Dağıtım — api.a-eon.engineer (DigitalOcean)

## Bileşenler
| Dosya | Görev |
|-------|-------|
| `docker-compose.yml` | Geliştirme/CI yığını: backend + (profil `full` ile) ai-engine, multi-mission-api + Nginx ağ geçidi (port 80) |
| `docker-compose.prod.yml` | Üretim ekleri: TLS (443), Let's Encrypt `certbot` yenileme, backend sağlık kontrolü |
| `nginx.conf` / `nginx.prod.conf` | Yol yönlendirme: `/api/v1/ai/*` → 8100, `missions|alerts|candidates` → 8200, geri kalanı → 8000 |
| `scripts/bootstrap-droplet.sh` | Droplet'in ilk kurulumu (Docker, güvenlik duvarı, repo, ilk sertifika, yığını başlatma) |
| `e2e/test_gateway.py` | Ağ geçidi üzerinden 11 yolun uçtan uca testi (eksik servisler atlanır) |
| `../.github/workflows/deploy.yml` | `main`'e her birleştirmede droplet'e SSH ile güncelleme + duman testi |
| `../.github/workflows/e2e.yml` | PR'larda yığını Docker ile ayağa kaldırıp e2e testlerini çalıştırır |

## İlk kurulum (lider, bir kez)
1. DigitalOcean'da Ubuntu 24.04 droplet aç (≥ 2 GB RAM; GitHub Student Pack kredisi).
2. DNS: `api.a-eon.engineer` için droplet IP'sine **A kaydı**; `a-eon.engineer` Vercel'e bağlı kalır.
3. Droplet'te root olarak:
   ```bash
   curl -fsSL https://raw.githubusercontent.com/alpztel/aeon/main/deploy/scripts/bootstrap-droplet.sh | bash -s -- <letsencrypt-e-postan>
   ```
4. Gizli bilgiler: `/opt/aeon/deploy/.env` (ANTHROPIC_API_KEY, MONGODB_URI, GITHUB_TOKEN, …). Asla commit'lenmez.
5. GitHub → Settings → Secrets → Actions: `DO_HOST` (IP), `DO_USER` (`root` ya da deploy kullanıcısı),
   `DO_SSH_KEY` (yalnız bu iş için üretilmiş özel anahtar). Bunlar yoksa `deploy` iş akışı kendini atlar.

## Günlük akış
- PR açılınca `ci-guard` + `e2e` çalışır. `main`'e birleştirme → `deploy` iş akışı droplet'i günceller
  ve `https://api.a-eon.engineer/api/v1/health` duman testini yapar.
- Elle: `cd /opt/aeon && docker compose -f deploy/docker-compose.yml -f deploy/docker-compose.prod.yml up -d --build`
- Sertifika yenilemesi otomatik; Nginx'in yeni sertifikayı alması için ayda bir
  `docker compose ... exec nginx nginx -s reload` (ya da cron).

## Yerel uçtan uca test
```bash
docker compose -f deploy/docker-compose.yml up -d --build
pip install pytest httpx jsonschema && AEON_GATEWAY_URL=http://localhost pytest -q deploy/e2e
```

## Bellek ve işçi ayarları (2 GB droplet)

| Değişken | Varsayılan | Not |
|---|---|---|
| `WEB_CONCURRENCY` | 2 | backend web işçisi |
| `AEON_HEAVY_WORKERS` | 1 | işçi başına ağır iş süreci (kör tarama, yörünge uydurma) |
| `AI_WEB_CONCURRENCY` | 1 | AI motoru web işçisi; her ek işçi ~170 MB |
| `OMP_NUM_THREADS` | 1 | AI motorunda torch iş parçacığı; küçük 1D-CNN için fazlası CPU'yu boşa harcar |
| `AEON_CATALOG_CACHE_TTL` | 600 | AI motorunun katalog sorgu önbelleği (s) |
| `AEON_UPSTREAM_BACKOFF_S` | 5 | backend hata/zaman aşımı sonrası AI motorunun bekleme süresi (s) |

Stres testinde (c150) tüm sistemin tepe belleği ~1,8 GB'dır; droplet büyütülürse önce `AI_WEB_CONCURRENCY=2` açın.
