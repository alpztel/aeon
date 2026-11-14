# AEON Tasarım Dili — "Gözlemevi"

Bu belge AEON arayüzünün görsel ve etkileşim kurallarını tanımlar. Üç referans sitenin
(100,000 Stars, Vast, NASA Eyes on Exoplanets) tersine mühendislikle çıkarılmış ortak
ilkelerinden türetilmiştir; hiçbirinin varlığını (logo, görsel, yazı tipi, metin) kopyalamaz.

## 1. Referanslardan çıkarılanlar

| Kaynak | Gözlem | AEON'a aktarılan ilke |
|---|---|---|
| 100,000 Stars | Tam ekran siyah sahne; arayüz yalnızca köşelerde ince ikonlar; sağ kenarda dikey ölçek cetveli; anlatım italik serif altyazı, veri etiketleri monospace; "Atla" düğmeli rehberli giriş | **Sahne önce gelir.** Arayüz sahnenin üstünde yüzer, onu kapatmaz. Rehberli tur altyazı olarak anlatılır. |
| Vast | Büyük, sıkı grotesk başlıklar; BÜYÜK HARF, harf aralıklı küçük mono etiketler ("CREW: 4"); sıcak gri palet + tek sinyal turuncusu; hap biçimli düğmeler; ince çizgiler, bol boşluk | **Teknik veri sayfası tipografisi.** Etiket küçük/mono/büyük harf, değer büyük/net. Tek vurgu rengi. |
| NASA Eyes | Nesne merkezli düzen: sol altta nesne adı + özet istatistik, sol kenarda "uzaklık" okuması, sağda dikey araç rayı, tıklayınca açılan bilgi paneli, ilk ziyarette "Keşfet / Turu izle" seçimli karşılama | **Nesne merkezli akış.** Seçili hedef her zaman sol altta; araçlar sağ rayda; ayrıntı tek bir yan panelde. |

## 2. Yerleşim

```
┌───────────────────────────────────────────────────────────────┐
│ AEON   [ ⌕  Hedef veya RA, Dec ara …   ⌘K ]   ● Model  TR│EN ? │  üst çubuk (şeffaf)
│                                                          ┌──┐ │
│                 ·  ·   yıldız alanı (sahne)  ·           │◐ │ │  sağ araç rayı
│        ·              ┌──────────────┐          ·        │≋ │ │  (Fark, Tayf, Sınıf,
│                 ·     │  SPHEREx     │   ·               │⊕ │ │   Çapraz eşleme,
│                       │  kesiti  ◎   │                   │⇶ │ │   Kaydır-yığ, Yörünge,
│      ·                └──────────────┘        ·          │◌ │ │   Aday havuzu)
│ HEDEF · KAHVERENGİ CÜCE                                  └──┘ │
│ WISE 0855−0714                     ── Q1 ── Q2 ─●─ Q3 ── Q4 ──│  dönem şeridi
│ RA 133.79° · DEC −7.24° · 2.28 pc                             │
└───────────────────────────────────────────────────────────────┘
```

- **Sahne:** tam ekran yıldız alanı; ortada SPHEREx kesiti çerçeveli gözlem penceresi olarak durur.
- **Üst çubuk:** sol marka, ortada arama (katalog adı veya `RA, Dec`), sağda veri modu noktası, dil, yardım.
- **Hedef kartı (sol alt):** küçük mono üst etiket + büyük başlık + tek satır veri. Sentetik hedefte kırmızı uyarı.
- **Araç rayı (sağ):** yedi araç; biri seçilince sağdan **denetçi paneli** kayar. Aynı anda bir araç açık.
- **Denetçi:** varsayılan dar (≈ 560 px); "genişlet" ile ekranın %70'i. Mobilde alttan açılan sayfa.
- **Dönem şeridi (alt orta):** 2026-Q1…Q4; tıkla veya ←/→.
- **Tur altyazısı:** rehberli turda alt ortada italik serif anlatım, adım noktaları, ileri/geri.

## 3. Renk

| Belirteç | Değer | Kullanım |
|---|---|---|
| `--aeon-bg` | `#050506` | sahne |
| `--aeon-surface` | `rgba(14,14,16,0.72)` + 20 px bulanıklık | paneller |
| `--aeon-line` | `rgba(236,232,227,0.10)` | ince çizgi |
| `--aeon-text` | `#ECE8E3` | metin (sıcak beyaz) |
| `--aeon-muted` | `#8E877F` | ikincil metin, etiket |
| `--aeon-signal` | `#FF5A1F` | **tek vurgu:** birincil eylem, seçili durum, aday |
| `--aeon-ice` | `#9DB4F0` | bağlantı, ölçüm vurgusu, odak halkası |
| `--aeon-ok` / `--aeon-warn` / `--aeon-danger` | `#5FD39A` / `#F2B544` / `#FF4D5E` | durum |

Kural: bir ekranda en fazla bir turuncu birincil eylem. Bilimsel grafiklerin renkleri (renk
haritaları, tayf çizgileri) bu kuralın dışındadır ama aynı nötr zemin üstünde durur.

## 4. Tipografi

| Rol | Yazı tipi | Örnek |
|---|---|---|
| Başlık / arayüz | Geist (grotesk), sıkı harf aralığı (−0.02em) | **WISE 0855−0714** |
| Veri etiketi | Geist Mono, 10–11 px, BÜYÜK HARF, +0.12em | `RA · DEC · TEFF` |
| Veri değeri | Geist Mono, tablo rakamları | `133.79451°` |
| Anlatım | Instrument Serif italik | *Q1 ile Q3 arasında yıldız yer değiştiriyor…* |

Ölçek: 11 · 13 · 15 · 20 · 28 · 44 px.

## 5. Bileşenler

- **Düğme:** hap biçimli (`border-radius: 999px`). Birincil = turuncu dolgu; ikincil = ince çizgi;
  hayalet = yalnız metin. Yükseklik 32 px (yoğun) / 40 px (birincil).
- **Panel:** 14 px köşe, ince çizgi, cam yüzey. İç içe panel yok; denetçinin içindeki bölümler
  yalnızca ince çizgiyle ayrılır.
- **Veri satırı:** `ETİKET` (mono, soluk) üstte, değer altta; ızgara halinde.
- **Durum rozeti:** nokta + kısa metin (● Fiziksel Model). Sentetik: kırmızı çerçeveli `SENTETİK`.
- **Odak:** tüm etkileşimli öğelerde 2 px buz mavisi odak halkası; klavyeyle tam gezinilebilir.

## 6. Hareket

- Panel açılışı 280 ms `cubic-bezier(.2,.8,.2,1)`; altyazı 400 ms solma.
- Yıldız alanı çok yavaş kayar (paralaks); `prefers-reduced-motion` açıksa tamamen durur.
- Hiçbir animasyon veri göstermeyi geciktirmez.

## 7. UX kuralları

1. **Her özellik iki tıkta:** ray → araç. Klavye: `D` fark, `S` kaydır-yığ, `3` yörünge, `?` kısayollar, `⌘K` Astro-LLM, `P` PDF.
2. **Boş durum dürüsttür:** veri yoksa "—" ve nedeni; uydurma sayı yok (AGENTS.md kural 5).
3. **Yükleme yerinde gösterilir:** panel iskeleti + ince ilerleme çizgisi; tüm ekranı kilitleyen yükleme yok.
4. **İlk ziyaret:** "Keşfet" veya "Rehberli turu başlat" seçimli karşılama; bir daha gösterme seçeneği.
5. **Mobil:** ray alta iner, denetçi alt sayfa olur, arama tam genişlik.
6. **İki dil:** tüm metinler `tr.json` / `en.json`'da.
