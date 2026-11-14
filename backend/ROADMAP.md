# Lider (Node 1) Backend Yol Haritası

Durum: ✅ tamam · 🔄 sürüyor · ⏳ sırada

| # | İş | Neden önemli | Durum |
|---|----|--------------|-------|
| 0 | Çekirdek API: 102 bant, FITS hattı, fark, shift-stack, kör tarama, REBOUND, DuckDB | 6 core uç nokta, 21 test | ✅ PR #1 |
| 1 | **Gerçek SPHEREx verisi (IRSA Quick Release L2)**: indirici, çok uzantılı FITS okuma, LVF dalga boyu, gerçek tayf noktaları | "Sahte veri değil" iddiasının kanıtı | 🔄 ayrı oturum (`lider-spherex-irsa`) |
| 2 | **Dünya paralaksına duyarlı Planet X araması (dijital izleme)**: görünür (geosentrik) konumlar, deneme uzaklığı ekseni, uzaklık × hız × KA kör taraması | 520 AU'daki bir cismin görünür hareketine yıllık ~±400″ paralaks hâkimdir; doğrusal shift-stack gerçek gökyüzünde çalışmaz | ✅ PR #3/#4 |
| 3 | Çok dönemli tespitlerden yörünge belirleme (en küçük kareler → REBOUND başlangıç durumu, belirsizlik elipsi) | Keşiften yörüngeye tek tık | ✅ `lider/roadmap` |
| 4 | Performans: işleme/küp önbelleği, gzip, isteğe bağlı float32-base64 görüntü kodlaması | Demo sırasında < 1 sn yanıt | ✅ `lider/roadmap` (gzip + önbellek; base64 kodlama sözleşme önerisi olarak bekliyor) |
| 5 | Üretim dağıtımı: DigitalOcean + Docker Compose + Nginx TLS + GitHub Actions deploy (`deploy/`, lead dalı) | `api.aeon.tech` canlı | ⏳ |
| 6 | Ağ geçidi uçtan uca testleri (3 servis birlikte) | Entegrasyon güvencesi | ⏳ |
| 7 | Gerçekçi SPHEREx kadansı (alanın yılda ~2 görünürlük penceresi) | Bilimsel gerçekçilik | ✅ `lider/roadmap` (`cadence: spherex`) |
| 8 | Son entegrasyon, tüm PR'ların birleşmesi, v1.0 sürümü | Jüri teslimi | ⏳ |
