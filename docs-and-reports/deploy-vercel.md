# AEON — Vercel Deployment & `aeon.tech` DNS Guide

Bu kılavuz, `frontend/` dizinindeki Next.js 16 uygulamasının **Vercel** üzerinde `https://aeon.tech` alan adına yayınlanması ve `https://api.aeon.tech` üzerindeki arka uç (FastAPI) servisine bağlanması için gereken adımları içerir.

---

## 1. Vercel Proje Ayarları

1. [Vercel Dashboard](https://vercel.com/new) üzerinden GitHub'daki `alpztel/aeon` deposunu içe aktarın (**Import Project**).
2. **Configure Project** ekranında aşağıdaki ayarları yapın:
   - **Framework Preset:** `Next.js`
   - **Root Directory:** `frontend` *(kritik: monorepo kök dizini değil, `frontend` alt klasörü seçilmelidir)*
   - **Build Command:** `npm run build` (varsayılan)
   - **Output Directory:** `.next` (varsayılan)
   - **Install Command:** `npm ci`

---

## 2. Ortam Değişkenleri (Environment Variables)

Vercel proje ayarlarında (**Settings → Environment Variables**) `Production`, `Preview` ve `Development` ortamları için şu değişkeni tanımlayın:

| Key | Value (Production) | Açıklama |
|---|---|---|
| `NEXT_PUBLIC_API_BASE` | `https://api.aeon.tech` | AEON FastAPI arka uç (`backend/` + `ai-engine/` + `multi-mission-api/`) kök adresi. Sondaki `/` olmadan yazılmalıdır. |

> **Çevrimdışı / Yedekleme Garantisi:** `NEXT_PUBLIC_API_BASE` sunucusuna geçici olarak ulaşılamasa bile `frontend/public/demo-cache/` içindeki önbellek dosyaları sayesinde 3 demo hedefi (`wise-0855`, `rw-aur`, `px-2026-09`) `offline_cache` modunda kesintisiz çalışmaya devam eder.

---

## 3. `aeon.tech` Özel Alan Adı (Custom Domain) ve DNS Kayıtları

1. Vercel'de **Settings → Domains** sekmesine gidin ve `aeon.tech` ile `www.aeon.tech` alan adlarını ekleyin.
2. Alan adı sağlayıcınızın (Registrar / Cloudflare / Route53) DNS yönetim panelinde aşağıdaki kayıtları oluşturun:

| Tür (Type) | Ad (Host / Name) | Değer (Value / Target) | TTL | Hedef |
|---|---|---|---|---|
| `A` | `@` | `76.76.21.21` | `Auto` / `300` | Vercel (`aeon.tech` → `frontend/`) |
| `CNAME` | `www` | `cname.vercel-dns.com.` | `Auto` / `300` | Vercel (`www.aeon.tech` → `aeon.tech`) |
| `A` *(veya `CNAME`)* | `api` | `<BACKEND_VPS_IP>` *(veya Railway/Render CNAME)* | `Auto` / `300` | FastAPI Backend (`https://api.aeon.tech`) |

> **Not (Cloudflare Kullanılıyorsa):** Vercel SSL sertifikasının otomatik doğrulanabilmesi için `@` ve `www` kayıtlarında Cloudflare Proxy (**Turuncu Bulut**) yerine **DNS Only (Gri Bulut)** modunu tercih edin veya SSL/TLS modunu **Full (Strict)** olarak ayarlayın.

---

## 4. Yayın Sonrası Doğrulama (Smoke Test)

Yayın tamamlandıktan sonra terminalden veya tarayıcıdan şu kontrolleri yapın:

```bash
# 1. Ön yüz erişim kontrolü
curl -I https://aeon.tech

# 2. Çevrimdışı demo önbelleği erişim kontrolü
curl -s https://aeon.tech/demo-cache/catalog-demo.json | head -n 20

# 3. Arka uç sağlık kontrolü (CORS dahil)
curl -i -H "Origin: https://aeon.tech" https://api.aeon.tech/api/v1/health
```
