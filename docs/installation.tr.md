# Kurulum ve yapılandırma

[English](installation.md) · Türkçe · [README](../README.tr.md) · [Deney rehberi](walkthrough.tr.md)

**Bilgisayarınızda Ollama, model, Python veya PostgreSQL kurulu olmak zorunda değildir.** Varsayılan kurulum bunları Docker içinde hazırlar; ilk açılışta `qwen2.5:3b` modelini otomatik indirir. API anahtarı gerekmez. Host üzerinde çalışan bir Ollama yalnızca isteğe bağlı hızlandırma seçeneğidir.

## 1. Gereksinimleri hazırlayın

| Gereksinim | Açıklama |
|---|---|
| Docker | macOS/Windows için [Docker Desktop](https://docs.docker.com/desktop/); Linux için [Docker Engine](https://docs.docker.com/engine/install/) + [Compose eklentisi](https://docs.docker.com/compose/install/) veya Docker Desktop. Docker çalışır durumda olmalı. |
| İşletim sistemi | macOS, Linux veya Windows üzerinde WSL2 terminali + Docker Desktop WSL entegrasyonu. Windows’ta Linux konteynerleri seçili olmalı; aşağıdaki Bash betiği doğrudan PowerShell için değildir. |
| Bellek | Docker’a en az yaklaşık 8 GB kullanılabilir RAM ayırın; rahat başlangıç için 10–12 GB önerilir. Ollama için sabit konteyner bellek sınırı yoktur; Docker’a ayrılan bellek, diğer servisler ve modelin çalışma belleği birlikte değerlendirilmelidir. Daha büyük modeller daha çok bellek ister. |
| Disk | Varsayılan model yaklaşık 1.9 GB; imajlar, derleme önbelleği ve veriler için ek alan gerekir. Başlangıç için yaklaşık 15 GB boş alan planlayın; bu bir indirme boyutu garantisi değildir. |
| İnternet | İlk imaj/model indirmesinde gerekir. GPU zorunlu değildir; kurulum betiği Linux/WSL2 üzerinde doğrulanmış NVIDIA GPU erişimini seçer, diğer durumlarda CPU kullanır. |

Docker Desktop kullanıyorsanız uygulamayı açıp motorun hazır olmasını bekleyin. Linux’ta Docker servisini başlatın ve hesabınızın Docker’a erişebildiğini doğrulayın:

```bash
docker info
docker compose version
```

## 2. Proje klasörünü açın

Depoyu klonlayın veya tam ZIP içeriğini çıkarın. Terminalde `docker-compose.yml`, `.env.example`, `backend/`, `frontend/` ve `scripts/` bulunan **vulnlm** klasörüne geçin. `backend/` içinden çalıştırmayın.

```bash
cd /projenin/bulundugu/yol/vulnlm
```

Yukarıdaki yolu kendi klasörünüzle değiştirin. Windows kullanıyorsanız bu komutları WSL2 terminalinde çalıştırın; proje klasörünün o terminalden erişilebilir olması gerekir.

## 3. Otomatik kurulum: önerilen yol

```bash
bash scripts/install.sh
```

Betik Docker/Compose ve yapılandırmayı kontrol eder, yoksa `.env.example` dosyasından `.env` oluşturur, imajları derler ve servisleri başlatır. Veritabanı, belge indeksi ve aktif model hazır olana kadar bekler; sonunda **gerçek portuyla** arayüz ve kurulum kontrolü adreslerini yazdırır. Bilgisayarda Ollama aramaz; yeni kurulumda Docker içindeki Ollama’yı kullanır. Mevcut `.env`, lab verileri ve indirilmiş modeller korunur; veri sıfırlama veya volume silme yapmaz.

Önce yalnızca gereksinimleri kontrol etmek için:

```bash
bash scripts/install.sh --check
```

İlk kurulum varsayılan olarak 30 dakika bekler. Yavaş bağlantıda:

```bash
bash scripts/install.sh --timeout 3600
```

İlk imaj/model indirmesi birkaç dakika veya bağlantınıza göre daha uzun sürebilir. Bu sırada `app` servisinin beklemesi normaldir; henüz tarayıcı sayfası açılmayabilir. Betiğin terminal çıktısını izleyin. Süre aşılırsa logları inceleyip aynı komutu tekrar çalıştırın; mevcut indirmeler ve veriler silinmez. Betik Docker’ı sisteme kurmaz ve işletim sistemi izinlerini otomatik değiştirmez.

## Otomatik GPU seçimi

`bash scripts/install.sh` işletim sistemini ve NVIDIA erişimini kontrol eder. GPU adayı bulunduğunda, lab verilerine veya ağa erişmeyen geçici bir Docker konteynerinde `nvidia-smi -L` çalıştırır. Yalnızca bu kontrol başarılıysa GPU’yu **Ollama servisine** açar; `app` ve araçlar GPU erişimi almaz.

| Ortam | Otomatik seçim |
|---|---|
| Linux + NVIDIA | Sürücü ve [NVIDIA Container Toolkit](https://docs.nvidia.com/datacenter/cloud-native/container-toolkit/latest/install-guide.html) Docker için hazırsa GPU. |
| Windows / WSL2 + NVIDIA | [Docker Desktop WSL2 GPU desteği](https://docs.docker.com/desktop/features/gpu/) ve güncel NVIDIA sürücüsü hazırsa GPU. Komutu WSL2 terminalinde çalıştırın. |
| NVIDIA var, Docker erişimi başarısız | Nedenini terminalde gösterir ve CPU ile devam eder. Sürücü/Toolkit kurmaz veya Docker servisini yeniden başlatmaz. |
| AMD / Intel veya GPU yok | Bu sürümün otomatik algılama desteği NVIDIA ile sınırlıdır; CPU seçilir. |
| macOS | Docker içindeki Ollama CPU kullanır. Apple GPU için isteğe bağlı host Ollama kullanabilirsiniz. |
| Host/harici Ollama seçilmiş | Bu tercih korunur; GPU seçimi o Ollama’nın çalıştığı makineye aittir, yerel GPU testi yapılmaz. |

```bash
bash scripts/install.sh --gpu cpu       # GPU olsa da CPU kullan
bash scripts/install.sh --gpu nvidia    # GPU erişimi doğrulanmazsa kurulumu durdur
bash scripts/install.sh --gpu auto      # Varsayılan: kontrol et, gerekirse CPU
```

Seçim Git’e girmeyen `docker-compose.override.yml` dosyasına kaydedilir; sonraki normal `docker compose` komutları da aynı seçimi kullanır. Betiği yeniden çalıştırmak donanımı yeniden kontrol eder. Kendi Compose override dosyanız veya `COMPOSE_FILE` seçiminiz varsa GPU ayarlarınız korunur; otomatik seçim yapılmaz. `--check` salt okunurdur ve GPU test konteyneri başlatmaz. GPU seçimi modelin tamamen VRAM’e sığdığını garanti etmez; sohbette bir yanıt aldıktan sonra `docker compose exec ollama ollama ps` ile `PROCESSOR` alanını kontrol edin (host modunda host üzerinde `ollama ps`).

## 4. İlk açılışı doğrulayın

Yeni kurulumun varsayılan adresi [http://127.0.0.1:8000](http://127.0.0.1:8000). `.env` veya ortam değişkeniyle farklı port seçilmişse betiğin yazdırdığı adresi kullanın.

- **Kurulum ekranı:** [http://127.0.0.1:8000/setup](http://127.0.0.1:8000/setup). Giriş yapmadan DB/şema, Chroma ve aktif model durumunu gösterir. Hazır değilken otomatik yenilenir; model indirmesi sürüyorsa ilerlemeyi gösterir.
- **Hazırlık API’si:** `/ready`; tüm gerekli bağımlılıklar hazırsa HTTP 200, değilse 503 döndürür. Modeli çalıştırarak yanıt kalitesini sınamaz.
- **API belgeleri:** `/docs`. **Uygulama/DB durumu:** `/health`. **Senaryolar:** `/lab/scenarios`.

Giriş ekranından **Alice** kısayoluna, ardından **Giriş** düğmesine basın. Ayarlar için **Admin** hesabını kullanın; aşağıdaki tabloda tüm demo hesapları bulunur. İlk deneme olarak `read_file aracıyla hello.txt dosyasını oku` yazın; işlem kanıtında `read_file` sonucu ve `Public lab file` içeriğini kontrol edin. İlk model yüklemesi CPU’da gecikebilir.

## Ollama ve model yoksa ne olur?

| Durum | Davranış |
|---|---|
| Bilgisayarda Ollama yok | Varsayılan yol etkilenmez: Compose ayrı bir Ollama konteyneri başlatır. |
| Docker’daki varsayılan model yok | `model-init` modeli otomatik indirir; indirme tamamlanmadan app başlamaz. |
| Model daha önce indirilmiş | Mevcut model volume’dan kullanılır; başlangıç betiği modeli tekrar indirmez. |
| Mevcut `.env` bilgisayardaki Ollama’yı seçmiş | Bu tercih korunur. Host Ollama erişilebilir olmalı; gateway eksik aktif modeli ve ayarlıysa görsel modeli sırayla indirir. Başlangıçta host kapalıysa uygulama erişimi tekrar dener. |
| İnternet yok / indirme hatası / disk dolu | Kurulum başarılı sayılmaz. Aşağıdaki logları inceleyip sorunu giderin ve betiği tekrar çalıştırın. Başarısız/iptal edilmiş gateway indirmesi, bağlantı düzeldikten sonra Admin → LLM modellerini yönet bölümünden yeniden başlatılabilir. |

**Docker içindeki Ollama (varsayılan):** `.env` içinde `OLLAMA_URL=` boş kalır. Bilgisayarda Ollama kurulu olsa bile otomatik olarak seçilmez.

**Bilgisayardaki Ollama (isteğe bağlı):** çalışan bir host Ollama için `.env` içinde `OLLAMA_URL=http://host.docker.internal:11434` ayarlayıp betiği tekrar çalıştırın. Erişilemiyorsa host servisini başlatın; Docker yoluna dönmek için bu değeri boşaltıp tekrar çalıştırın. Bu modda kullanılmayan Docker Ollama model indirmesi atlanır. Model host’ta çalışsa da shell/Python gibi araçlar `app` konteynerinde kalır.

Host Ollama varsayılan olarak `127.0.0.1:11434` dinler. Özellikle Linux’ta konteynerden erişim için dinleme adresi ve host güvenlik duvarı ayrıca ayarlanmalıdır; platform adımları [Ollama FAQ](https://docs.ollama.com/faq#how-do-i-configure-ollama-server) içindedir. `OLLAMA_HOST` ile erişilebilir bir adrese bağlayın ve erişimi Docker’dan gelen bağlantılarla sınırlayın. Kimlik doğrulamasız Ollama API’sini internete açmayın. `.env` içindeki `OLLAMA_URL` yalnızca istemci hedefini seçer; host servisini yeniden yapılandırmaz.

## Port değiştirme, yeniden açma ve durdurma

8000 doluysa `.env` içindeki `LAB_PORT=8000` satırını örneğin `LAB_PORT=18000` yapıp betiği yeniden çalıştırın. Adres `http://127.0.0.1:18000` olur. Betik mevcut `.env` dosyasını üzerine yazarak değiştirmez; dışa aktarılmış ortam değişkenlerinin `.env` değerlerini geçersiz kılabileceğini unutmayın.

```bash
# Sonraki açılış; veriler ve modeller korunur.
bash scripts/install.sh

# Durum ve tanılama
docker compose ps --all
docker compose logs --tail 80 model-init model-gateway ollama app

# Verileri silmeden durdurma
docker compose stop
```

Normal kapatma için `down -v` kullanmayın; `-v` model ve lab volume’larını siler. Güncelleme öncesi yedekleme ve şema geçişleri için [işletim rehberine](operations.tr.md) bakın.

## Betiksiz kurulum

Otomatik betik yerine Compose’u doğrudan da kullanabilirsiniz. `.env` zaten varsa ilk komutu **atlayın**:

```bash
cp .env.example .env
docker compose up --build -d
docker compose logs -f model-init model-gateway app
```

`logs -f` ekranından `Ctrl+C` ile çıkmak servisleri durdurmaz. Sonrasında `/setup` ekranını kontrol edin. Diğer modeller **İleri düzey ayarlar → LLM modellerini yönet** bölümünden seçilir (bkz. [LLM model seçimi](#llm-model-seçimi)).

## Sentetik hesaplar

| Hesap | E-posta | Parola | Başlangıç rolü |
|---|---|---|---|
| Alice | `alice@lab.local` | `alice-lab` | user |
| Bob | `bob@lab.local` | `bob-lab` | user |
| Admin | `admin@lab.local` | `admin-lab` | admin |

Her hesap 1.000 sentetik krediyle başlar. Giriş formunda demo hesaplarına ait kısayollar bulunur. API giriş yanıtı bearer token, tarayıcı girişi ayrıca oturum çerezi verir. Parolalar laboratuvar zafiyeti olarak düz metin tutulur; bu düzenek gerçek kimlik yönetimi için kullanılmaz.

## İleri düzey ayarlar

**Admin** demo hesabıyla giriş yapıp üst menüden **İleri düzey ayarlar** bölümünü açın. Her senaryo; LLM, ajan, uygulama ve güven sınırları başlıkları altında ayrı bir anahtarla yönetilir. Panelde serbest SQL aracı ve debug yapılandırma çıktısı için de kontroller bulunur. Senaryo kartındaki **Ayarla** düğmesi ilgili ayarı doğrudan açar.

- **Açık:** kasıtlı olarak zafiyetli davranışı etkinleştirir.
- **Kapalı:** anahtarın yanında açıklanan güvenlik kontrolünü uygular. Araç veya iş akışı kullanılabilir kalır.

Değişiklikleri kaydettiğinizde ayarlar tüm laboratuvarda yeni isteklere uygulanır. `DATA_DIR/private/scenario-settings.json` dosyasında saklanır; yeniden başlatmada ve laboratuvar verileri sıfırlandığında korunur. Başlangıçta tüm zafiyetler açıktır. Diğer demo kullanıcıları ayarları inceleyebilir ancak değiştiremez. Ayar yönetimi güncel bir Admin çerez oturumu gerektirir; imzasız JWT deneyi bu erişimi sağlamaz.

Korumalı MCP araçları listelenmeye ve çağrılmaya devam eder. Araç düzenlemesi onayı geçersiz kılar; çağrı onaylı revizyonla eşleşmeli ve onaylanan varsayılan argümanlar korunmalıdır. Modelin ayrıcalıklı işlemleri, kanıt panelindeki **Onayla ve yürüt** adımıyla kullanıcıya sunulur.

Korumalı araçların kapsamı tanımlıdır: shell, desteklenen komutları argüman listesiyle çalıştırır; Python, public çalışma alanında hesaplama, çıktı, `math`/`json` ve metin dosyası işlemlerini destekler. SQL, kullanıcı kapsamlı bir kopyada salt okunur sorgular çalıştırır. HTTP, genel IP hedeflerine veya `SAFE_HTTP_URLS` içinde tanımlanan tam URL’lere erişir; varsayılan public lab kaynağı `http://internal-service:9000/public` adresidir.

Prompt, bellek, görsel ve araç sonucu kontrolleri güvenilmeyen referans veriyi ayırır; yetki ve işlem onayı uygular. Modelin talimatlara uyma davranışını garanti etmez. Ayarlar laboratuvar süreci içindeki eğitim kontrolleridir; özellikle sınırsız yürütme senaryoları açıkken dağıtım izolasyonunun yerine geçmez.

Ayar sayacı **44 senaryo + 2 ek kontrolü** ayrı gösterir; SQL aracı ve debug yapılandırması katalogdaki senaryo sayısını artırmaz. Her anahtarın ön koşulları, açık/kapalı sonuçları, meşru kullanım, tarayıcı adımları ve sıfırlama gereksinimleri için [karşılaştırma rehberine](walkthrough.tr.md#comparison-cards) bakın.

## Sistemi sıfırla

**İleri düzey ayarlar → Sistemi sıfırla**, laboratuvarı ilk açılış durumuna döndürür; örneğin deneyler arasında kullanılır. Hesaplar, roller ve bakiyeler başlangıç değerlerine döner (her hesap 1.000 kredi). Transferler, belgeler ve RAG indeksi, bellek kayıtları, sohbet geçmişi, onaylar, audit kayıtları ve araç kaydı silinir. Flag, canary değerleri ve JWT imza anahtarı yeniden üretilir; Admin'inki dahil tüm oturumlar ve tokenlar geçersiz olur. Deneylerin lab veri dizinine bıraktığı shell veya Python çıktıları gibi dosyalar silinir. Onay penceresi, zafiyet ayarlarını ve model seçimini de varsayılana döndürebilir; bu seçenek varsayılan olarak işaretlidir. İndirilmiş modeller silinmez. Laboratuvarı yalnızca Admin demo hesabı sıfırlayabilir ve işlem geri alınamaz.

## LLM model seçimi

**İleri düzey ayarlar → LLM modellerini yönet** bölümünü açın. Pencere, katalogdaki her modeli açıklaması, boyutu, yetenekleri ve indirilip indirilmediğiyle listeler. İndirilmiş bir model seçildiğinde laboratuvar hemen o modele geçer. İndirilmemiş bir model seçildiğinde indirme başlar: ana ekran indirme ilerlemesini ve kullanılmaya devam eden modeli gösterir; indirme tamamlanınca laboratuvar yeni modele geçer. İndirme başarısız olursa veya iptal edilirse mevcut model kullanılmaya devam eder. Modeli yalnızca Admin demo hesabı değiştirebilir; diğer kullanıcılar listeyi salt okunur görür.

| Model | Boyut | Not |
|---|---|---|
| `qwen2.5:3b` (varsayılan) | 1.9 GB | Hızlı; CPU veya kurulumun doğruladığı NVIDIA GPU ile çalışır |
| `qwen2.5:7b-instruct` | 4.7 GB | Daha tutarlı araç çağrısı ve JSON |
| `qwen2.5:14b-instruct` | 9.0 GB | Daha büyük Qwen2.5 modeli; yaklaşık 11 GB bellek ister |
| `qwen3:8b` | 5.2 GB | Düşünme modu açılabilir |
| `qwen3:14b` | 9.3 GB | Düşünme modu; yaklaşık 11 GB bellek ister |
| `qwen3-vl:4b-instruct` | 3.3 GB | Görsel kabul eder; araç çağırma; Ollama ≥ 0.12.7 gerekir |
| `qwen3.8:27b` | 17.7 GB | Görsel kabul eder; düşünme modu; yaklaşık 22 GB bellek ve lab ile gelen 0.35.1 gibi güncel bir Ollama gerekir |

Düşünme destekleyen modellerin kartında **Düşünme modu** anahtarı bulunur. Varsayılan olarak kapalıdır; istekler `reasoning_effort: none` ile gider ve yanıtlar hızlı ve modeller arasında karşılaştırılabilir kalır. Açıkken model yanıttan önce akıl yürütür, isteğin token bütçesi büyür ve akıl yürütme metni kanıt panelinde görünür. Korumalı modlar özel bağlamı ve SSN değerlerini yanıtta olduğu gibi akıl yürütme metninde de maskeler.

Seçim yeni model isteklerine laboratuvar genelinde uygulanır ve `DATA_DIR/private/model-settings.json` dosyasında saklanır. Yeniden başlatma ve CLI veri sıfırlaması seçimi korur. UI sistem sıfırlamasında ayarları da sıfırlama kutusu seçiliyse varsayılana döner. `LLM_MODEL` varsayılan model olarak kalır ve yapılandırılan Ollama'da yoksa açılışta indirilir. Görsel sohbet, ayarlıysa `VISION_MODEL` ile; değilse görsel kabul eden aktif modelle yanıtlanır. Katalog `backend/model_catalog.json` dosyasındadır.

Modeller, model ağ geçidinin arkasındaki Ollama'dan gelir. Varsayılan olarak bu, sabit bellek sınırı konmamış lab Ollama konteyneridir (Ollama 0.35.1); kurulum betiği Linux/WSL2 üzerinde doğruladığı NVIDIA GPU erişimini açabilir. Modelin sığması kullanılabilir RAM/VRAM miktarına da bağlıdır. Host'taki Ollama'yı, GPU'su ve orada kurulu modellerle kullanmak için `.env` içinde `OLLAMA_URL=http://host.docker.internal:11434` ayarlayıp stack'i yeniden oluşturun. Bu durumda modellerin host belleğine sığması gerekir.



Model sürüm bilgisi için [Qwen3-VL model sayfası](https://ollama.com/library/qwen3-vl:4b-instruct) ve [Qwen3.8 model sayfası](https://ollama.com/library/qwen3.8:27b) esas alınır (kontrol: 2026-10-29). Qwen3-VL için belirtilen minimum Ollama 0.12.7’dir. İndirilmiş olması modelin bellek ve sürüm açısından çalışabildiğini göstermez. Gerçek sohbet/görsel isteğini ayrıca doğrulayın.

## Görsel model ve arayüz

📎 ile PNG/JPEG eklemek `/chat/image` yolunu kullanır; metin belgeleri RAG'e gitmeye devam eder. Görseller açılmış halinde 1 MB ile sınırlıdır (proxy'nin 2 MiB gövde sınırı da geçerlidir). En kolay yol, **İleri düzey ayarlar → LLM modellerini yönet** bölümünden `qwen3-vl:4b-instruct` gibi görsel kabul eden bir model seçmektir; bu model hem metin hem görsel sohbeti yanıtlar. Ayrı bir metin modeli kullanmak için bunun yerine `.env` içindeki `VISION_MODEL` değerini görsel destekli bir Ollama modeline ayarlayın; `model-init` bu modeli `LLM_MODEL` ile birlikte indirir. Modeli indirin ve app servisini yeniden oluşturun:

```bash
bash scripts/install.sh
```

Model sohbet API'sinin `image_url` girdisini, eylem deneylerinde de araç çağrısını veya lab JSON fallback'ini desteklemelidir. Seçilen modele göre RAM/VRAM ve Docker bellek ayırmasını kontrol edin; projede Ollama için sabit bellek sınırı yoktur. `VISION_MODEL` boşsa ve aktif model görsel kabul etmiyorsa `/chat/image` 503 döndürür. Görsel baytları bilerek açık bırakılan ham audit içinde kalır; kayıtlı sohbet geçmişi yalnızca metni ve görselin çıkarıldığını belirten notu tutar, gerektiğinde görseli yeniden ekleyin. PDF/OCR uygulanmamıştır.

API uç noktaları Swagger üzerinde, senaryo kataloğu ise arayüzde bulunur. Başlangıç işlemi gerekli tabloları oluşturur ve laboratuvar verilerini korur. Tam sıfırlama; diğer laboratuvar kayıtlarıyla birlikte onayları, ajan mesajlarını ve HTTP test içeriklerini temizler. Backend kodunu düzenledikten sonra `docker compose up --build -d app` ile uygulama imajını yeniden derleyin.


## Native geliştirme

Shell araçları native süreçte host kullanıcısının yetkilerini taşır. Native çalışmayı yalnızca tek kullanımlık bir sanal makine veya kontrollü test ortamında tercih edin. Kod testleri kendi geçici dosyalarını kullanır.

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements-dev.txt
export DATABASE_URL=
export MODEL_GATEWAY_URL=
export DATA_DIR="$(mktemp -d /tmp/vulnlm-native.XXXXXX)"
export LLM_API_URL=http://127.0.0.1:11434/v1/chat/completions
export LLM_MODEL=qwen2.5:3b
cd backend
python seed_data.py
uvicorn main:app --host 127.0.0.1 --port 8000 --no-access-log
```

`DATABASE_URL` boşsa SQLite kullanılır. Ollama ve modeli native kurulumda ayrıca hazır etmeniz gerekir. `CHROMA_ENABLED=False` yalnızca RAG dışı geliştirme içindir; RAG rotalarını çalışan senaryo gibi sunmaz.
