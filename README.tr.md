# VulnLM

[![CI](https://github.com/cyberdes-security/vulnlm/actions/workflows/ci.yml/badge.svg)](https://github.com/cyberdes-security/vulnlm/actions/workflows/ci.yml)

[English](README.md) · Türkçe

LLM uygulamaları ve ajanlar için kasıtlı olarak zafiyetli bir eğitim laboratuvarı. 44 senaryo; prompt injection, RAG, kalıcı bellek, araç yürütme, alt ajan delegasyonu, ajanlar arası gizli kanallar ve web uygulaması güvenliğini kapsar. FastAPI, PostgreSQL/SQLite, Chroma ve Ollama kullanır. Arayüz Türkçe ve İngilizcedir.

> Yalnızca size ait, izole bir ortamda ve sentetik verilerle çalıştırın. Shell/Python araçları gerçekten kod yürütür; diğer araçlar dosya ve veritabanı kayıtlarını değiştirir. İnternete açmayın; gerçek hesap, anahtar veya belge eklemeyin.

[Kurulum](#hızlı-başlangıç) · [Senaryolar](#senaryo-kataloğu) · [Deney rehberi](docs/walkthrough.tr.md) · [İşletim](docs/operations.tr.md) · [Katkı rehberi](CONTRIBUTING.tr.md)

![VulnLM çalışma alanı: 44 senaryo, canlı read_file araç çağrısı ve yürütme kanıtı](docs/images/workspace-tr.png)

## Hızlı başlangıç

Docker Engine + Compose v2 veya Docker Desktop çalışır durumda olmalıdır. Windows’ta komutları Docker Desktop entegrasyonu açık **WSL2 terminalinde** çalıştırın. Projenin tamamını indirin; aşağıdaki komutların çalışma dizini `docker-compose.yml`, `backend/`, `frontend/` ve `scripts/` bulunan **vulnlm/** dizinidir.

```bash
cd /projenin/bulundugu/yol/vulnlm
bash scripts/install.sh
```

Yerel Ollama, Python, PostgreSQL veya API anahtarı gerekmez. Betik `.env` yoksa `.env.example` üzerinden oluşturur; mevcut ayarlara ve verilere dokunmaz. Docker imajlarını hazırlar ve varsayılan `qwen2.5:3b` modelini indirir. İlk kurulum için internet, yaklaşık 15 GB boş disk ve Docker’a ayrılmış yaklaşık 8 GB RAM planlayın; 10–12 GB daha rahat çalışır. Büyük modeller daha fazla bellek ister.

Linux/WSL2’de NVIDIA GPU erişimi bir test konteynerinde doğrulanırsa Ollama GPU kullanır; aksi halde CPU seçilir. Mac, AMD ve Intel için bu betiğin varsayılanı CPU’dur. Host Ollama yalnızca `.env` içinde açıkça seçilmişse kullanılır.

Betik hazır olduğunda adresi yazdırır. Varsayılan: **http://127.0.0.1:8000**; ilk kontrol: **http://127.0.0.1:8000/setup**. İlk model indirilirken sayfa henüz açılmayabilir. Portu `.env` içindeki `LAB_PORT` ile değiştirin. Yalnızca ön kontrol için `bash scripts/install.sh --check`; yavaş indirme için `bash scripts/install.sh --timeout 3600` kullanın.

GPU önkoşulları, host Ollama, eksik model, görsel model, betiksiz kurulum ve native geliştirme için [ayrıntılı kurulum rehberine](docs/installation.tr.md) bakın.

## İlk deney

Başlangıçta bütün zafiyetler açıktır. **Açık = zafiyet etkin; kapalı = ilgili koruma etkin.** Ayar değişikliği tamamlanmış işlemleri geri almaz. Deneyler arasında [sıfırlama adımlarını](#sıfırlama-ve-verinin-korunması) uygulayın.

| Hesap | E-posta | Parola | ID / rol |
|---|---|---|---|
| Alice | `alice@lab.local` | `alice-lab` | 1 / user |
| Bob | `bob@lab.local` | `bob-lab` | 2 / user |
| Admin | `admin@lab.local` | `admin-lab` | 3 / admin |

Her hesap 1.000 sentetik krediyle başlar. Aynı origin’deki sekmeler çerez paylaşır; eşzamanlı kullanıcılar için ayrı tarayıcı profilleri kullanın.

### Arayüzden

1. Alice kısayolunu seçip **Giriş** düğmesine basın.
2. Aynı tarayıcıda lab adresinin sonuna `/doc/1337` ekleyip açın (varsayılan: `http://127.0.0.1:8000/doc/1337`). İsterseniz **API belgeleri** → `GET /doc/{doc_id}` → **Try it out** yoluyla da aynı isteği gönderebilirsiniz.
3. HTTP 200, `owner_id: 2` ve Bob’un belgesini görün. Alice’in başka kullanıcının belgesini okuması kanıttır; model gerektirmez.
4. Korumalı karşılaştırma için Admin ile giriş → **İleri düzey ayarlar** → `document-idor` araması → anahtarı kapat → **Ayarları kaydet**. Alice ile yeniden giriş yapıp aynı isteği tekrarlayın: 404 beklenir. Alice’in `/doc/1` belgesi 200 dönmeye devam eder.

Sohbet/araç akışını ayrıca sınamak için `read_file aracıyla hello.txt dosyasını oku` yazın. **İşlem kanıtı** panelinde gerçek `read_file` çağrısını ve `Public lab file` çıktısını arayın. Modelin yalnızca “okudum” demesi kanıt değildir.

### API üzerinden

Aşağıdaki örnek varsayılan zafiyetli başlangıç içindir. `BASE` değerini kurulum betiğinin yazdığı adresle eşleştirin; `curl` ve Python 3 bu örneği terminalden çalıştırmak için gerekir, Docker kurulumu için gerekmez.

```bash
BASE=http://127.0.0.1:8000
COOKIE_JAR=$(mktemp)
curl --fail-with-body -sS -c "$COOKIE_JAR" \
  -H 'Content-Type: application/json' \
  -d '{"email":"alice@lab.local","password":"alice-lab"}' "$BASE/auth/login"
curl --fail-with-body -sS -b "$COOKIE_JAR" "$BASE/doc/1337" \
  | python3 -c 'import json,sys; d=json.load(sys.stdin); assert d["owner_id"] == 2; print("Alice read Bob document", d["id"])'
rm -f "$COOKIE_JAR"
```

Diğer deneylerde aynı istek, temiz veriyle zafiyet açıkken ve kapalıyken karşılaştırılır. [Deney rehberi](docs/walkthrough.tr.md) her senaryo için API örneğini, tarayıcı yolunu, beklenen korumayı ve meşru kullanım kontrolünü verir.

## Senaryo kataloğu

**LLM/ASI etiketleri 2026 sürümüne göredir.** Bir eşleştirme, ilgili kategorinin tüm alt risklerinin uygulandığı anlamına gelmez.

| Senaryo | Giriş / akış | Doğrulanabilir etki |
|---|---|---|
| Prompt injection · LLM01 | `/chat` | Modelin uygulama politikasını aşan yanıt veya araç çağrısı üretmesi |
| Hidden context · LLM08 | `/chat` | Rastgele üretilmiş özel bağlam canary'sinin açıklanması |
| Dolaylı RAG injection · LLM01 | `/upload_doc` → `/chat` | Belgedeki talimatın ajan eylemini değiştirmesi |
| Vektör tenant sızıntısı · LLM09 | `/rag/search` | Alice'in Bob'a ait özel belgeyi alması |
| Kalıcı bellek zehirleme · ASI06 | `/memory` veya `remember` → `/chat` | Kayıtlı talimatın sonraki kullanıcı/oturum bağlamına taşınması |
| Araç açıklaması zehirleme · ASI02 | `/registry/tools/{name}` → onay → `/chat` | Güvenilmeyen açıklamanın model araç tanımına girmesi |
| Onay sonrası araç değiştirme · ASI04 | registry → approve → update → execute | Aynı onay altında yeni hedefin çalışması |
| Excessive agency · LLM03 | `/chat`, `/tool/transfer_funds` | Başka kullanıcının bakiyesinin veya rolünün değişmesi |
| Kota eksikliği · LLM06 | `/chat/batch` | Tek kullanıcı adına tekrarlanan gerçek model çağrıları |
| DOM XSS · LLM10 | model yanıtı → UI | Olay işleyicisinin tarayıcıda çalışması |
| PII sızıntısı · LLM02 | `/chat` + PII filtresi | Maskelenmiş yanıta rağmen diğer kanallarda PII bulunması |
| Sohbet geçmişi IDOR · LLM08 | `/chat` + `conversation_id` | Başka kullanıcı geçmişinin modele taşınması |
| Shell RCE · CWE-78 | `/shell_tool` | Süreç yetkileriyle komut ve gerçek dosya yan etkisi |
| Python yürütme · CWE-94 | `/tools/python_tool` | Ayrı Python sürecinde gerçek kod yürütme |
| SQL injection · CWE-89 | `/users/search`, `/reports/{id}/run` | Anlık veya saklanmış girdinin sorgu sonucunu genişletmesi |
| SSRF · CWE-918 | `/http_tool` | `http://internal-service:9000/private` yanıtına erişim |
| Path traversal · CWE-22 | `/tools/read_file` | Public dizini dışındaki özel fixture'ın okunması |
| Mass assignment · CWE-915 | `/user/update` | Kendi rolünü güncelleyip yönetici erişimi kazanma |
| JWT none · CWE-347 | bearer token, `/auth/validate` | İmzasız gerçek JWT ile ayrıcalık kazanma |
| CSRF · CWE-352 | `/tool/transfer_funds/form` | Kurbanın çereziyle kredi transferi |
| Belge IDOR · CWE-639 | `/doc/1337` | Bob belgesini Alice oturumundan okuma |
| Ping command injection · CWE-78 | `/tools/ping` | Host girdisinin ek kabuk işlemi çalıştırması |
| Audit sızıntısı · LLM02 | `/audit` | Ham prompt ve başka kullanıcı verilerinin okunması |
| Onaylı araç parametresini aşma · Lab trust boundary | `/tools/execute`, `/mcp` | Registry revision değişmeden gizli doc_id varsayılanının değiştirilmesi |
| Belge/bellek sahipliği sahteciliği · Lab trust boundary | `/upload_doc`, `/memory` | Alice girdisinin Bob sahipliği ve sahte source ile SQL/Chroma içine kaydedilmesi |
| JWT içinde eski yönetici rolü · Lab trust boundary | `/admin/users` | DB rolü düşürüldükten sonra gerçek imzalı JWT ile admin erişiminin sürmesi |
| Eksik oturum iptali ve süre kontrolü · Lab trust boundary | `/auth/logout`, `/me` | Logout sonrası JWT kullanımı; çerez kaydında sunucu taraflı son kullanma süresinin olmaması |
| İşlem sonrası audit boşluğu · Lab trust boundary | `/chat`, `/audit` | İkinci model isteği hata verince transfer kalır, sohbet audit kaydı oluşmaz; doğrudan araçlar da kaydetmez |
| Tekrar denemede mükerrer transfer · Lab trust boundary | `/tool/transfer_funds` | Aynı istek ve Idempotency-Key iki ayrı işlem ve iki bakiye değişikliği üretir |
| Negatif tutar ve yetersiz bakiye · Lab trust boundary | `/tool/transfer_funds` | Negatif tutar para akışını tersine çevirir; bakiyeyi aşan transfer negatif bakiye üretir |
| Belleğin doğrudan kullanıcılar arası okunması · Lab trust boundary | `/memory` | Alice oturumunun Bob tarafından yazılmış bellek içeriğini API üzerinden alması |
| Başka konuşmanın geçmişine yazma · Lab trust boundary | `/chat` | Bilinen conversation_id içine saldırgan turu eklenir; asıl sahibin sonraki model bağlamına girer |
| Sohbet ve araç eyleminde CSRF · Lab trust boundary | `/chat/form` | Same-site cross-origin form kurban çereziyle model çağrısı yapar; araç etkisi model seçimine bağlıdır |
| Araç sonucundan dolaylı injection · Lab trust boundary | `external-site` → `http_tool` → `/chat` | Gerçek HTTP yanıtındaki talimat sonraki model isteğine girer; seçilen araç gerçek bellek kaydı oluşturur |
| İnsan onayı ve yürütme uyuşmazlığı · Lab trust boundary | `/approvals/{id}` | Onaylanan alıcı/tutar saklanırken değişen öneri yürütülür; snapshot ve DB etkisi karşılaştırılır |
| RAG sıralamasını saldırgan belgelerle doldurma · Lab trust boundary | `/upload_doc` → `/rag/search` | Üç saldırgan belge ilk üç sonucu doldurup güvenilir Cedar belgesini dışarı iter |
| Ajanlar arası gönderici sahteciliği · Lab trust boundary | `/agents/messages`, `/agents/research` | Araştırmacı için reddedilen rol değişimi, doğrulanmayan supervisor göndericisiyle kabul edilir |
| Görsel içerikten injection · Lab trust boundary | `/chat/image` | PNG/JPEG gerçek image_url içeriğiyle görsel modele iletilir; saldırı başarısı bağımsız araç/DB etkisiyle ölçülür |
| Model/ince ayar backdoor’u · LLM04 | `/chat` (backdoorlu model) → `training_marker` | Trigger’a bağlı ince ayarlı model, masum bir `please` mesajında zararsız `training_marker` çağrısını üretir ve bayraklı sonuca çalıştırılır; temiz model üretmez |
| Alt ajan yetki yükseltmesi · ASI03 | `spawn_agent`, `/agents/subagents` → `/tools` | Orkestratörün admin rolüyle `change_role` yetkisi verilen researcher alt ajanı Alice'i admin yapar |
| Alt ajan raporu ile handoff enjeksiyonu · ASI07 | `spawn_agent`, `/agents/subagents/{id}/report` | Salt okunur researcher'ın önerdiği transfer Alice'in yetkisiyle yürütülür ve gerçek kredi taşır |
| Sınırsız özyinelemeli alt ajan üretimi · ASI08 | `spawn_agent` → `spawn_agent` | Alt ajanlar laboratuvar devre kesicisine kadar alt ajan doğurur ve tek istekte model çağrılarını katlar |
| Alt ajana aşırı bağlam aktarımı · LLM02 | `spawn_agent` → `/agents/subagents/{id}` | Alt ajanın saklanan bağlamı, ana ajan promptundaki özel canary'yi ve Alice'in SSN'sini taşır |
| Ajanlar arası gizli kanal (CPU cache) · Lab güven sınırı | `/agents/relay`, `/agents/channel` | Ağ üzerinde yalıtılmış iki ajan, doğrudan mesajlaşma reddedilirken ortak CPU cache'i üzerinden bir sırrı sızdırır |

`/sql_tool` ayrıca doğrudan serbest SQL çalıştırır. Bu, klasik string birleştirme SQLi senaryosundan ayrı, aşırı yetkili bir araçtır. `/tool/change_role` ve `/tool/delete_hr` gerçek DB mutasyonu yapar. `/debug/config` sentetik yapılandırma değerleri sızdırır.

**Yürütme kapsamı:** Python kodu, uygulama sürecinin yetkileriyle çalışır. Görsel injection için görsel destekli bir model gerekir. `model-backdoor` senaryosu, katalogdan seçilen kasıtlı backdoorlu bir modelle model/ince ayar zehirlenmesini kapsar; laboratuvar bu modeli sunar ancak kendisi eğitim yapmaz (model harici olarak eğitilip Hugging Face'e yayımlanır). Sohbet ajanı alt görevleri `spawn_agent` aracıyla devreder; her alt ajan kendi rolü, araç yetkisi ve `sub_agent_runs` kanıt kaydı olan ayrı bir model döngüsüdür ve `/agents/subagents` aynı sınırları modelsiz olarak sunar ([alt ajan delegasyonu](docs/walkthrough.tr.md#subagent-delegation)). Ağ üzerinde yalıtılmış iki ajan, deterministik olarak modellenmiş bir CPU cache yan kanalı üzerinden koordine olur ([ajanlar arası gizli kanal](docs/walkthrough.tr.md#control-agent-covert-channel)); `scripts/cache_covert_probe.py` opt-in gerçek-zamanlama karşılığıdır. PDF/OCR ve belirli üçüncü taraf CVE yeniden üretimleri laboratuvar kapsamı dışında kalır.

## Mimari

```mermaid
flowchart LR
    Client[Tarayıcı / API] --> Edge[Nginx: loopback port]
    subgraph AppContainer [app konteyneri]
        App[FastAPI / ajan yürütücüsü]
        Tools[Shell / Python / dosya araçları]
        Index[("Chroma (gömülü)")]
    end
    Edge --> App
    App --> Tools
    App --> Index
    App --> DB[(PostgreSQL)]
    App --> Internal[Dahili HTTP servisi]
    Edge --> Site[Harici site: saldırgan sayfaları]
    App --> Site
    App --> Gateway[Model ağ geçidi]
    Gateway --> Ollama[Docker veya host Ollama]
    Ollama -. model indirme .-> Registry[Ollama kayıt deposu]
```

Araçlar ve Chroma dizini `app` konteynerinin içinde, onun yetkileriyle çalışır; Chroma gömülüdür ve verisini lab volume'ünde tutar. Uygulama yalnızca `internal` olan `lab` Docker ağındadır ve internete erişemez. Yalnızca Nginx loopback port yayınlar: lab için `LAB_PORT`, saldırgan web sitesinin yerini tutan harici site için `SITE_PORT`; başka hiçbir servis host portu açmaz. Uygulama Ollama’ya yalnızca sohbet ve katalog modeli indirme işlemlerini ileten model ağ geçidi üzerinden erişir. Ağ geçidi ve Ollama ayrıca indirmeler için internete çıkabilen ayrı bir `model-download` ağını paylaşır; dahili Ollama kullanılırken tek seferlik `model-init` servisi ilk açılışta varsayılan modeli bu ağ üzerinden indirir. Host Ollama seçimi araçları host’a taşımaz. Docker izolasyonu uygulamadaki eğitim zafiyetlerinden ayrıdır; daha güçlü ayrım için ayrı bir sanal makine kullanın.

Arayüz, FastAPI’nin sunduğu HTML/CSS/JavaScript modülleridir; ayrı frontend sunucusu veya derleme adımı yoktur. [İşletim rehberi](docs/operations.tr.md) şema geçişlerini, belge kaynağı onaylarını ve metrikleri açıklar.

## Ayarlar ve model seçimi

Admin → **İleri düzey ayarlar** içinde 44 senaryo ve 2 ek kontrol (`sql-tool`, `debug-config`) ayrı ayrı yönetilir. Ayarlar tüm laboratuvara uygulanır ve yeniden başlatmada korunur. Ayar, model ve belge güveni yönetimi gerçek Admin demo çerez oturumu gerektirir; JWT sahteciliği bu operatör erişimini sağlamaz.

**LLM modellerini yönet** bölümünden indirilmiş modeli seçin veya katalogdan indirin. İndirme bitene kadar mevcut model kullanılır. Görsel deneyler PNG/JPEG kabul eden bir model gerektirir; varsayılan `qwen2.5:3b` görsel kabul etmez. Ollama için projede sabit bir bellek sınırı yoktur; kullanılabilir RAM/VRAM ve Docker kaynak ayarları belirleyicidir. Model ve bellek ayrıntıları [kurulum rehberindedir](docs/installation.tr.md#llm-model-seçimi).

## Test ve doğrulama

Python 3.13 ile proje kökünde:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements-dev.txt
python -m pytest -q
```

Varsayılan testler geçici bir SQLite veritabanı ve gerçek Chroma kullanır. SQL, dosya, oturum, HTTP ve araç etkileri gerçektir. Testlere özel LLM yanıtları kullanıldığında modelin saldırıya direnç gösterip göstermediği ölçülmez; test yalnızca uygulama akışını doğrular. Loopback HTTP testleri yerel port açabilmelidir. `VULNLM_TEST_DATABASE_URL` verilirse testler o DB'yi sıfırlar; yalnızca test için ayrılmış bir veritabanı kullanın.

Gerçek Chromium testleri:

```bash
python -m playwright install --with-deps chromium
RUN_BROWSER_TESTS=1 python -m pytest -q
```

Bu koşu XSS'nin çalışmasını ve başka origin'deki formun oturum çereziyle işlem yapmasını doğrular. Kurulu Chrome kullanmak için `CHROME_EXECUTABLE` ortam değişkenini tam executable yoluna ayarlayabilirsiniz. `RUN_BROWSER_TESTS=1` ayarlanmadığında tarayıcı testleri atlanır.

Gerçek Ollama modeliyle testler (opt-in, olasılıksal):

```bash
RUN_MODEL_TESTS=1 python -m pytest tests/test_model.py -q
```

Yapılandırılan `LLM_API_URL`/`LLM_MODEL`'i (varsayılan yerel Ollama `qwen2.5:3b`) kullanır. Bu testler canlı model isteklerini ve yürütülen araçların veritabanı etkilerini kontrol eder. Saldırı sonucu gözlemlendiğinde test geçer; gözlemlenmediğinde gerekçesiyle atlanır. Entegrasyon hataları test başarısızlığı olarak raporlanır. Araç çağrısı gerektiren testler tool-desteği olmayan modelde atlanır; görsel testi için `VISION_MODEL` ayarlayın. Varsayılan `pytest` koşusunda tüm model testleri `SKIPPED` görünür.

### Deney sonucunu yorumlama

API/DB/dosya kontrolleri uygulama davranışını doğrular; kontrollü model yanıtları gerçek modelin saldırıya uyduğunu göstermez. Canlı modelde `OBSERVED` bağımsız kanıt bulunan etkiyi, `NOT_OBSERVED` etkinin görülmediğini, `ERROR` entegrasyon hatasını belirtir. `SKIPPED` bir güvenlik başarısı değildir. Model adı/digest’i, ayarlar, başlangıç verisi, istek ve tekrar sayısını kaydedin.

Gerçek model probe’ları çalıştıkları laboratuvara belge, bellek ve sohbet kaydı ekler; boş bir deney ortamı kullanın. Model matrisi büyük modelleri indirebilir ve kaynak kullanımını artırır. Komutlar ve kanıt ölçütleri [doğrulama rehberindedir](docs/validation.tr.md). RAG, 256 boyutlu deterministik hash embedding kullanır; semantik arama kalitesini ölçmez.

## Sıfırlama ve verinin korunması

En hızlı yol **İleri düzey ayarlar → Sistemi sıfırla** düğmesidir (ayrıntılar [kurulum rehberinde](docs/installation.tr.md#sistemi-sıfırla)). Normal yeniden başlatma verileri korur:

```bash
docker compose restart app
```

SQL, Chroma, oturum ve canary'leri açıkça sıfırlamak için **aktif deney yokken**:

```bash
docker compose stop edge app
docker compose run --rm --no-deps app python seed_data.py --reset --confirm DELETE-LAB-DATA
docker compose up --no-deps -d app edge
```

Uygulama ve giriş proxy’si reset boyunca kapalı tutulur; yeniden açılış PostgreSQL/Chroma bağlantı önbelleklerini de yeniler. Reset, sentetik tabloları siler ve yeniden kurar. Uygulama klasöründeki rastgele kullanıcı dosyalarını silmez; yalnızca kendi özel fixture dosyalarını yeniler. Model volume'u korunur. UI'deki “Yeni sohbet” bu reset işlemi değildir.

HTTP `/lab/reset` varsayılan olarak kapalıdır. Kullanılacaksa `LAB_RESET_TOKEN` tanımlayın ve istekte `X-Lab-Reset-Token` gönderin. Sıfırlama anahtarı bu uç noktaya operatör erişimini kontrol eder. Uygulama sürecinde kod yürütülmesi yapılandırma değerlerini açığa çıkarabilir.

## Sorun giderme

| Belirti | Kontrol |
|---|---|
| UI var, sohbet 502 | Ana ekrandaki model durumu; `docker compose logs model-gateway ollama model-init`; `OLLAMA_URL` |
| Model indirilemiyor | `model-download` ağından internet erişimi; boş disk alanı; `backend/model_catalog.json` içindeki model etiketi |
| Uygulama başlamıyor | DB healthcheck, şema uyumsuzluğu, model indirme sonucu |
| Eski konuşma yeni sohbette etkili | Kalıcı bellek senaryosu; tam reset gerekir |
| Bir flag göründü ama başarı belirsiz | Veri sahibini, DB değişimini, tarayıcı veya araç kanıtını inceleyin |
| Model araç çağrısı yapmıyor | Modelin tool desteğini kontrol edin; JSON/tek fonksiyon fallback'i var |
| Komut timeout veriyor | Lab süresi 3 saniye; sınırsız döngü deneyi yürütme sınırında durdurulur |
| API 401 | `/auth/login` ile çerez veya bearer token alın |
| XSS testinde hiçbir şey olmadı | `innerHTML` ile eklenen script etiketi yürümeyebilir; test gerçek `onerror` olayını kullanır |

## Dosya düzeni

```text
backend/       API, auth, araçlar, veri modelleri, seed/reset, Chroma, model ağ geçidi ve katalog
frontend/      Giriş formu, sohbet, senaryo kataloğu ve işlem izi
tests/         Davranış, loopback HTTP ve gerçek tarayıcı testleri
scripts/       Kurulum, gerçek model deneyleri ve model test matrisi
docs/          Senaryo adımları, kaynaklar ve doğrulama rehberi
```

Bağımlılıklar `backend/requirements.lock` içinde sürüm bazında sabittir; Docker da aynı dosyayı kurar. Docker/model tag’leri değişebilir; ortamı yeniden kurarken commit ile gerçek image/model digest’lerini kaydedin. Sürümlerin eşleşmesi model örneklemesini deterministik yapmaz. Eğitim zafiyetleri uygulama davranışlarında tanımlanmış ve kaynak kodunda işaretlenmiştir.

[Kaynaklar](docs/sources.tr.md) · [Lisans](LICENSE)

Katkı, hata raporu ve dokümantasyon değişiklikleri için [CONTRIBUTING.tr.md](CONTRIBUTING.tr.md).

## Yasal Uyarı

Yalnızca eğitim ve araştırma amaçlıdır. İzole, kullanım yetkinizin olduğu ortamlarda ve sentetik verilerle kullanın. Herhangi bir garanti verilmez; kullanım riski size aittir.
