# Lider (Node 1) Backend Yol Haritası

> Proje tamamlandı (2026-11-15). Tablo, yapılan işlerin son durumunu gösterir.

Durum: ✅ tamam · 🔄 sürüyor · ⏳ sırada

| # | İş | Neden önemli | Durum |
|---|----|--------------|-------|
| 0 | Çekirdek API: 102 bant, FITS hattı, fark, shift-stack, kör tarama, REBOUND, DuckDB | 6 core uç nokta, 21 test | ✅ PR #1 |
| 1 | **Gerçek SPHEREx verisi (IRSA Level-2)**: indirici, çok uzantılı FITS okuma, LVF dalga boyu, gerçek tayf noktaları | "Sahte veri değil" iddiasının kanıtı | ✅ (`irsa.py`, `archive.py`; tayf hızı 28×, PR #28) |
| 2 | **Dünya paralaksına duyarlı Planet X araması (dijital izleme)**: görünür (geosentrik) konumlar, deneme uzaklığı ekseni, uzaklık × hız × KA kör taraması | 520 AU'daki bir cismin görünür hareketine yıllık ~±400″ paralaks hâkimdir; doğrusal shift-stack gerçek gökyüzünde çalışmaz | ✅ PR #3/#4 |
| 3 | Çok dönemli tespitlerden yörünge belirleme (en küçük kareler → REBOUND başlangıç durumu, belirsizlik elipsi) | Keşiften yörüngeye tek tık | ✅ `lider/roadmap` |
| 4 | Performans: işleme/küp önbelleği, gzip, isteğe bağlı float32-base64 görüntü kodlaması | Demo sırasında < 1 sn yanıt | ✅ `lider/roadmap` (gzip + önbellek; base64 kodlama sözleşme önerisi olarak bekliyor) |
| 5 | Üretim dağıtımı: Docker Compose + Nginx TLS (`deploy/`); canlı API Azure VM'de, haftalık SPHEREx/Gaia çekme işi (`deploy/azure/`) | `api.a-eon.engineer` canlı | ✅ hackathon boyunca canlıydı; demo sonrasında kapatıldı |
| 6 | Ağ geçidi uçtan uca testleri (3 servis birlikte) | Entegrasyon güvencesi | ✅ `deploy/e2e`, `e2e` iş akışı |
| 7 | Gerçekçi SPHEREx kadansı (alanın yılda ~2 görünürlük penceresi) | Bilimsel gerçekçilik | ✅ `lider/roadmap` (`cadence: spherex`) |
| 8 | Son entegrasyon, tüm PR'ların birleşmesi, v1.0 sürümü | Jüri teslimi | ✅ PR #35–#36 |
| 9 | En iyi gerçek veri döneminin otomatik seçimi, çeyrek-dönem uyumu, komşu kaynak karışımı tespiti | Doğru dönem, temiz tayf | ✅ PR #31, #33 |
| 10 | Galaktik yörünge (galpy, `MWPotential2014`) ve Güneş'e en yakın geçiş; ölçülmemiş radyal hız için zarf | Yıldız ve kahverengi cücelerin gerçek yörüngesi | ✅ PR #35 |
