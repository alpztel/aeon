# Stres testi

Tüm yığını (backend, ai-engine, multi-mission-api, Nginx) Docker Compose ile kaldırıp ağ geçidi üzerinden
altı aşamada zorlar: temel gecikme, kademeli yük (10/50/150 eşzamanlı), ağır işler, kötüye kullanım,
5 dakika sürekli yük ve ai-engine çökmesi. Konteyner bellek/CPU kullanımı 5 sn'de bir kaydedilir.

- Çalıştırma: GitHub → Actions → **stress** → *Run workflow* (yaklaşık 25 dakika). Rapor `stress-report` artefaktında.
- Yerel: `docker compose -f deploy/docker-compose.yml --profile full up -d --build && bash stress/run.sh`
- Dış arşivler (Gaia, IRSA, MAST) yüke maruz bırakılmaz: çapraz eşleştirme trafiği yalnız fikstür hedeflerinde,
  LLM anahtarı ve GitHub token'ı tanımlı değildir.
- Canlı Vercel sitesine yük testi yapılmaz.

Bellek profili: `deploy/docker-compose.yml` 2 GB'lık droplet hedefiyle çalışır (2 web işçisi × 1 ağır iş süreci,
`AEON_TRACKER_CACHE_MB=64`, `AEON_TILE_SED_CACHE=16`, `MALLOC_ARENA_MAX=2`). Raporun `calibration` satırı,
farklı CI makinelerindeki çalıştırmaları karşılaştırmak için tek çekirdek hız ölçüsüdür.
