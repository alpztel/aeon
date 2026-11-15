# AEON veri çekme — Azure sanal makinesi rehberi

Bu klasör, AEON'un kullandığı gerçek gökyüzü verisini **her hafta kendiliğinden** bir Azure sanal
makinesine (VM) çeken ve Azure Blob Storage'a yedekleyen paketi içerir.

```
 Haftalık zamanlayıcı (systemd, Pazartesi 06:00 UTC)
        │
        ▼
 Azure VM (Ubuntu 24.04) ── ingest.py ─┬─► IRSA SPHEREx  (SIA ile liste, kesit servisi ile küçük FITS)
        │                              ├─► AWS S3 nasa-irsa-spherex  (isteğe bağlı tam dosyalar, ücretsiz)
        │                              └─► MAST Gaia DR3  (yedek: ESA Gaia TAP)
        ▼
 /data/aeon  (VM'in veri diski) ──► Azure Blob Storage "aeon-data"  (yönetilen kimlik, şifre yok)
```

| Dosya | Ne işe yarar | Nerede çalışır |
|---|---|---|
| `provision.sh` | Azure kaynaklarını kurar: kaynak grubu, depolama, VM, yetki | **Azure Cloud Shell** |
| `setup-vm.sh` | VM'in içine kodu, Python ortamını ve zamanlayıcıyı kurar | **VM'in terminali** |
| `ingest.py` | Asıl iş: veriyi çeker, raporlar, Blob'a yükler | VM (zamanlayıcı çalıştırır) |
| `link-backend.sh` | Çalışan backend'i `/data/aeon`'u okuyacak şekilde bağlar (bir kez) | VM |
| `update-api.sh` | Canlı API'yi GitHub `main` ile tek komutta günceller | VM |
| `targets.json` | Hangi gök cisimleri izlenecek | düzenlenebilir |
| `aeon-ingest.service` / `.timer` | Haftalık otomatik çalıştırma | VM (`setup-vm.sh` kurar) |
| `test_ingest.py` | Çevrimdışı testler (CI'da çalışır) | — |

Hiçbir yerde API anahtarı veya şifre yoktur: arşivler herkese açık, Blob'a yazma VM'in yönetilen
kimliğiyle (Managed Identity) yapılır.

---

## 0. Komutları nerede çalıştıracağım?

Bu rehberde komutlar **üç farklı yerde** çalışır. Her kod bloğunun üstünde hangisi olduğu yazıyor.

| Yer | Ne zaman | Nasıl anlarım (komut satırının başı) |
|---|---|---|
| **A. Azure Cloud Shell** — tarayıcıdaki Azure terminali | Kaynakları kurarken (Adım 1–2) ve VM'e bağlanırken | `kullaniciadi@Azure:~$` |
| **B. VM'in terminali** — Cloud Shell'den `ssh` ile girilen makine | Kurulum ve izleme (Adım 3–5) | `aeon@aeon-ingest:~$` |
| **C. Kendi bilgisayarın** (isteğe bağlı) | Cloud Shell yerine yerel terminal kullanmak istersen | — |

**Önerim:** her şeyi **Cloud Shell**'den yap. Azure CLI, `git` ve `ssh` orada hazır kurulu; kendi
bilgisayarına hiçbir şey kurman gerekmez. Windows'un PowerShell'i bu `.sh` betiklerini çalıştıramaz.
Yerelde yapmak istersen Bölüm 9'a bak.

---

## 1. Cloud Shell'i aç  *(yer: tarayıcı)*

1. https://portal.azure.com adresine Azure hesabınla gir. Öğrenciysen **Azure for Students**
   (kredi kartsız, 100 USD kredi) yeterli.
2. Sayfanın en üstündeki çubukta, arama kutusunun sağında **`>_`** simgesine (Cloud Shell) tıkla.
   Sayfanın altında bir terminal açılır.
3. İlk açılışta sorulursa:
   - Ortam olarak **Bash**'i seç (PowerShell değil).
   - Depolama sorusunda **"Mount storage account"** seçeneğiyle küçük bir depolama oluşturmanı öneririm.
     Böylece Cloud Shell'in ev klasörü (ve birazdan oluşacak SSH anahtarın) kalıcı olur. "No storage
     account required" seçersen oturum kapanınca SSH anahtarın silinir (çözümü Bölüm 8'de).
4. Doğru abonelikte olduğunu kontrol et:

*(yer: A — Cloud Shell)*
```bash
az account show --query "{abonelik:name, id:id}" -o table
```

Birden çok aboneliğin varsa doğru olanı seç:

*(yer: A — Cloud Shell)*
```bash
az account set --subscription "Azure for Students"
```

---

## 2. Azure kaynaklarını kur  *(yer: A — Cloud Shell, ~3–5 dk)*

*(yer: A — Cloud Shell)*
```bash
git clone https://github.com/alpztel/aeon.git
```

```bash
bash aeon/deploy/azure/provision.sh
```

Betik şunları kurar (tekrar çalıştırmak güvenli; var olanları bozmaz):

| Kaynak | Ad | Not |
|---|---|---|
| Kaynak grubu | `aeon-rg` | Her şey bunun içinde; silmek tek komut (Bölüm 7) |
| Depolama hesabı | `aeon` + 12 karakter | Herkese kapalı, yalnızca kimlikle erişim |
| VM | `aeon-ingest` | Ubuntu 24.04, `Standard_B2s` (2 vCPU / 4 GB), 64 GB veri diski, East US |
| Yetki | VM → "Storage Blob Data Contributor" | VM yalnızca bu depolamaya yazabilir |
| Yetki | Sen → "Storage Blob Data Reader" | Portalda dosyaları görebilmen için |

Bölge, boyut gibi ayarları değiştirmek istersen başına değişken ekle, örneğin:
`LOCATION=westeurope VM_SIZE=Standard_B2ms bash aeon/deploy/azure/provision.sh`

Betik bitince şuna benzer bir özet yazar. **IP adresini ve Blob adresini bir yere not al:**

```
VM public IP       : 20.115.xx.xx
SSH                : ssh aeon@20.115.xx.xx
Blob account URL   : https://aeon1a2b3c4d5e6f.blob.core.windows.net
```

---

## 3. VM'e bağlan ve paketi kur  *(yer: A'dan B'ye geçiş, ~5–10 dk)*

Cloud Shell'de, not aldığın IP ile VM'e bağlan:

*(yer: A — Cloud Shell)*
```bash
ssh aeon@20.115.xx.xx
```

İlk bağlantıda "Are you sure you want to continue connecting" sorusuna `yes` yaz. Komut satırının
başı `aeon@aeon-ingest:~$` olduysa artık **VM'in içindesin**.

*(yer: B — VM)*
```bash
git clone https://github.com/alpztel/aeon.git
```

Aşağıdaki adresi Adım 2'de not aldığın Blob adresiyle değiştir:

*(yer: B — VM)*
```bash
sudo BLOB_ACCOUNT_URL=https://aeon1a2b3c4d5e6f.blob.core.windows.net bash aeon/deploy/azure/setup-vm.sh
```

Bu betik:
- veri diskini biçimlendirip `/data`'ya bağlar,
- `aeon` adlı ayrıcalıksız bir servis kullanıcısı açar,
- kodu `/opt/aeon/repo`'ya, Python ortamını `/opt/aeon/venv`'e kurar,
- ayarları `/etc/aeon/ingest.env`'e yazar,
- haftalık zamanlayıcıyı etkinleştirir.

---

## 4. İlk çalıştırma ve izleme  *(yer: B — VM)*

Zamanlayıcıyı beklemeden hemen bir kez çalıştır:

```bash
sudo systemctl start aeon-ingest.service
```

Bu komut iş bitene kadar bekler (ilk çalıştırmada birkaç dakika). İkinci bir Cloud Shell sekmesinde
(veya iş bittikten sonra) günlüğü izle:

```bash
journalctl -u aeon-ingest.service -f
```

`Ctrl+C` ile izlemeden çıkılır; iş durmaz. Son satırda şuna benzer bir özet görürsün:

```
[ingest] done in 900.2 s: 1260 new SPHEREx frames, 7/7 Gaia cones
```

Sonucu kontrol et:

```bash
ls /data/aeon/spherex/spherex_dr1/
ls /data/aeon/catalogs/gaia_dr3/
cat /data/aeon/runs/$(ls /data/aeon/runs | tail -1)
systemctl list-timers aeon-ingest.timer
```

İlk çalıştırma, hedef ve koleksiyon başına zamana yayılmış en fazla 80 kesit indirir (8 hedef ×
2 koleksiyon için birkaç GB indirme, diskte birkaç yüz MB). Sonraki çalıştırmalar **yalnızca daha önce
indirilmemiş kareleri** indirir; var olan dosyalar atlanır. Sınırı değiştirmek için
`/etc/aeon/ingest.env`'e `AEON_MAX_FILES=200` (veya sınırsız için `0`) satırı ekle.

> İlk çalıştırmada `[blob] ... AuthorizationPermissionMismatch` görürsen yetki ataması henüz
> yayılmamıştır (Azure'da 5–10 dk sürebilir). Biraz bekleyip `sudo systemctl start aeon-ingest.service`
> komutunu tekrarla; indirilen dosyalar yeniden indirilmez, yalnızca yükleme yapılır.

---

## 5. Verileri portalda gör  *(yer: tarayıcı)*

portal.azure.com → **Storage accounts** → `aeon…` → **Data storage → Containers** → `aeon-data`.
Klasör yapısı VM'dekiyle aynıdır:

```
aeon-data/
├── spherex/spherex_dr1/<hedef>/*.fits + manifest.json   ← SPHEREx kesitleri (AEON backend'in okuduğu düzen)
├── spherex/spherex_qr3/<hedef>/...
├── catalogs/gaia_dr3/<hedef>.json                        ← Gaia DR3, kaynak ve sorgu bilgisiyle
└── runs/<zaman>.json                                     ← her çalıştırmanın raporu
```

---

## 6. Günlük kullanım  *(yer: B — VM)*

**Hedef eklemek veya çıkarmak:** `targets.json`'u GitHub'da düzenle (veya bir PR aç), sonra VM'de:

```bash
cd ~/aeon && git pull && sudo bash deploy/azure/setup-vm.sh
```

`setup-vm.sh`'i yeniden çalıştırmak güvenlidir; Blob adresini önceki kurulumdan hatırlar.
`targets.json`'da bir hedef iki şekilde yazılabilir:

```json
{ "catalog_id": "wise-0855" }
{ "tag": "m101", "ra": 210.80227, "dec": 54.34895, "note": "Pinwheel galaxy" }
```

`catalog_id`, `backend/aeon/catalog.py`'deki bir kayıttır; konumu çalıştırma tarihine özdevinimle
taşınır. Sentetik hedeflerde (`px-2026-09`) yalnızca gerçek arka plan alanı indirilir ve Gaia sorgusu
yapılmaz.

**Zamanlamayı değiştirmek:** `/etc/systemd/system/aeon-ingest.timer` içindeki `OnCalendar=` satırını
düzenle (örneğin her gün için `*-*-* 06:00:00 UTC`), sonra:

```bash
sudo systemctl daemon-reload && sudo systemctl restart aeon-ingest.timer
```

**Elle farklı ayarla çalıştırmak** (örnek: hedef başına 2 tam dosyayı AWS S3'ten de indir):

```bash
sudo -u aeon env $(cat /etc/aeon/ingest.env | xargs) HOME=/data/aeon/.home \
  /opt/aeon/venv/bin/python /opt/aeon/repo/deploy/azure/ingest.py --full 2
```

Diğer seçenekler: `--max-files N` (hedef ve koleksiyon başına en fazla N kesit; 0 = hepsi), `--size-px 96`,
`--collection spherex_dr1` (tekrarlanabilir), `--no-gaia`, `--no-spherex`. Hepsi için `--help`.

---

## 7. Maliyet, durdurma ve silme  *(yer: A — Cloud Shell)*

- Asıl gider VM'dir (`Standard_B2s`, East US: kabaca aylık 30–40 USD; güncel fiyat için Azure fiyat
  hesaplayıcısına bak). Depolama bu veri hacminde birkaç dolardır. IRSA'nın S3 kopyası çıkış ücreti
  almaz; Azure'a gelen trafik ücretsizdir.
- **Kullanmadığında VM'i durdur** (disk ve veri kalır, işlem ücreti durur; zamanlayıcı da çalışmaz):

```bash
az vm deallocate -g aeon-rg -n aeon-ingest
```

```bash
az vm start -g aeon-rg -n aeon-ingest
```

VM yeniden açıldığında kaçırılan haftalık çalıştırmayı kendisi yapar (`Persistent=true`).

- **Her şeyi silmek** (VM, disk, depolama ve içindeki tüm veri — geri alınamaz):

```bash
az group delete -n aeon-rg
```

---

## 8. Sorun giderme

| Belirti | Neden / çözüm |
|---|---|
| `ssh: Permission denied (publickey)` | Cloud Shell geçici oturumdaydı ve SSH anahtarı silindi. Cloud Shell'de yeni anahtarı VM'e yükle: `az vm user update -g aeon-rg -n aeon-ingest -u aeon --ssh-key-value "$(cat ~/.ssh/id_rsa.pub)"` (anahtar yoksa önce `ssh-keygen -t rsa -b 4096`). |
| `ssh: Connection timed out` | VM kapalı olabilir: `az vm start -g aeon-rg -n aeon-ingest`. IP değiştiyse: `az vm show -d -g aeon-rg -n aeon-ingest --query publicIps -o tsv`. |
| `[blob] AuthorizationPermissionMismatch` | Yetki ataması yayılıyor; 5–10 dk bekleyip tekrar çalıştır. Devam ederse `provision.sh`'i yeniden çalıştır. |
| `another ingest run is active` | Bir önceki çalıştırma sürüyor. 12 saatten eski kilit dosyası kendiliğinden temizlenir. |
| `[spherex] ... HTTPError 503` | IRSA geçici olarak meşgul. Diğer hedefler etkilenmez; bir sonraki çalıştırma eksikleri tamamlar. |
| `[gaia] ... via MAST ...` | MAST yanıt vermedi; ESA Gaia TAP'a otomatik geçilir. Rapor hangisinin kullanıldığını yazar. |
| `az: command not found` | Komutu VM'de çalıştırıyorsun; `az` komutları **Cloud Shell**'de çalışır. |
| Disk dolu | `df -h /data`; `--max-files` ile hedef başına kesit sayısını sınırla veya diski büyüt: `az disk update --size-gb 128 ...` |

---

## 9. Cloud Shell yerine kendi bilgisayarından  *(yer: C — isteğe bağlı)*

- **Windows:** Azure CLI'ı kur (`winget install -e --id Microsoft.AzureCLI`), sonra `.sh` betiklerini
  **Git Bash** veya **WSL** (Ubuntu) terminalinde çalıştır; PowerShell'de değil. İlk olarak `az login`.
- **macOS / Linux:** `brew install azure-cli` veya Microsoft'un kurulum betiği; ardından `az login`.
- Geri kalan adımlar aynıdır: `provision.sh` yerelde, `setup-vm.sh` VM'de.

---

## 10. Veri kaynakları ve kullanım kuralları

| Kaynak | Uç nokta | Kullanım |
|---|---|---|
| IRSA SPHEREx SIA | `https://irsa.ipac.caltech.edu/SIA` (`spherex_dr1`, `spherex_qr3`) | Hedefi kapsayan görüntülerin listesi |
| IRSA kesit servisi | dosya adresi + `?center=RA,DEC&size=Npix` | Hedef çevresinden ~100 kB'lık kesit (tam dosya ~65 MB) |
| AWS S3 | `nasa-irsa-spherex` (us-east-1), önekler `dr1/`, `qr3/`, `qr2/`; kimliksiz | `--full` ile tam dosya; S3 yolu bu paketle canlı doğrulandı |
| MAST Gaia | `astroquery.mast.Catalogs` (`catalog="Gaia", version=3`) | Hedef çevresinde Gaia DR3 kaynakları |
| ESA Gaia TAP | `https://gea.esac.esa.int/tap-server/tap/sync` | MAST yanıt vermezse yedek |

Arşivlere saygı: istemci kendini `AEON-azure-ingest` olarak tanıtır, en fazla 4 paralel indirme
yapar, çalıştırma başına boyut sınırı vardır ve zamanlayıcı yükü dağıtmak için rastgele en fazla
30 dk gecikmeyle başlar. Toplu tam dosya ihtiyacı için IRSA'nın önerdiği yol S3'tür.

## 11. Sonraki adım: canlı backend

İndirilen dosyalar AEON backend'in beklediği düzendedir. Aynı VM'de `deploy/docker-compose.yml`
çalıştırılır ve `fits-data` volume'u `/data/aeon`'a bağlanırsa (`AEON_DATA_DIR`), canlı sitede
gerçek SPHEREx görüntüleri ve tayfları görünür.

---

## 12. Canlı API'yi güncellemek  *(yer: A — Cloud Shell)*

Ekip `backend/`, `ai-engine/`, `multi-mission-api/` veya `deploy/` altında bir değişikliği `main`'e
birleştirdiğinde canlı API **kendiliğinden güncellenmez**. Güncellemek için Cloud Shell'de önce
değişkenleri tanımla:

```bash
VM=aeon-api
RG=$(az vm list --query "[?name=='aeon-api'].resourceGroup" -o tsv)
```

Sonra tek komut (5–15 dk; servisler yeniden derlenir):

```bash
az vm run-command invoke -g "$RG" -n "$VM" --command-id RunShellScript --scripts "git -C /root/aeon pull -q && bash /root/aeon/deploy/azure/update-api.sh" --query "value[0].message" -o tsv
```

`update-api.sh` şunları yapar: çalışan compose projesini bulur, kodu `git pull --ff-only` ile
günceller (yerel değişiklik varsa hiçbir şeyi yeniden başlatmadan durur), tüm servisleri yeniden
derleyip başlatır, backend / yapay zekâ motoru / görev API'sinin sağlık kontrollerini bekler,
haftalık çekme işini tazeler ve kullanılmayan imajları siler. `main` değişmemişse yalnızca sağlık
kontrolü yapar; yine de yeniden derlemek için komutta `bash` yerine `FORCE=1 bash` yaz.

Başarılı bitişte son satır `UPDATED: <commit>` olur. Bir servis sağlıklı açılmazsa `FAIL <servis>`
yazar ve hata koduyla çıkar.
