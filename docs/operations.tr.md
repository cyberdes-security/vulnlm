# İşletim ve bakım

[English](operations.md) · Türkçe · [README](../README.tr.md)

Bu özellikler izole eğitim laboratuvarının bakımını kolaylaştırır. Senaryo anahtarları ve kasıtlı zafiyetler eğitim davranışını korur.

## Şema geçişleri

Başlangıç, `backend/migrations/` altındaki sıralı geçişleri bir transaction içinde uygular. `schema_migrations` tablosu uygulanan revizyonları tutar. `v001_initial` eski şemanın dondurulmuş kopyasıdır; `v002_document_trust` belge onay tablosunu, `v003_subagents` alt ajan delegasyon kayıtlarını, `v004_covert_channel` gizli kanal cache medyumunu ekler. Yeni şema değişiklikleri mevcut revizyonları düzenlemek yerine yeni bir revizyonla yapılır. SQLite ve PostgreSQL desteklenir; eşzamanlı başlangıçlar veritabanı kilidiyle sıralanır.

Mevcut, revizyonsuz bir kurulumun tabloları önce doğrulanır ve kayıtları korunarak geçiş yapılır. Eksik kolonlu uyumsuz şema veya daha yeni bir uygulamaya ait revizyon başlangıcı durdurur. Veri otomatik sıfırlanmaz. Uygulama açılmadan yalnızca geçiş çalıştırmak için backend dizininden:

```bash
python -m migrations
```

Güncellemeden önce PostgreSQL için `pg_dump`, SQLite için uygulama durdurulmuşken veritabanı kopyası alın. Laboratuvarı tam geri yüklemek için `DATA_DIR` içindeki özel yapılandırma, anahtarlar, public dosyalar ve Chroma verisini de aynı durma aralığında yedekleyin. Yedeği ayrı bir kurulumda geri yükleyip `/ready` ile kontrol edin. Otomatik downgrade yoktur; geri dönüş, uyumlu uygulama sürümüyle birlikte yedeği geri yüklemektir. **Sistemi sıfırla**, yedek geri yükleme işlemi değildir; kayıtları siler ve revizyonları yeniden oluşturur.

## Belge güveni ve RAG

**İleri düzey ayarlar → Belge güvenini yönet** yalnızca gerçek Admin demo çerez oturumuyla açılır. Yüklenen her belge onaysızdır; `source: handbook`, belge ID'si veya isteğe eklenen `trusted` alanı güven sağlamaz. Admin onayı SQL'de, arama için kullanılan kopyası Chroma metadata'sında tutulur. Başlangıçta oluşturulan eğitim belgelerine onay açıkça verilir.

Eski kurulumdan geçişte mevcut belgeler **otomatik onaylanmaz**. Geçişten sonra sıralama deneyinde referans olarak kullanacağınız Cedar dahil belgeleri bu panelden inceleyip onaylayın. Yeniden başlatma, Chroma metadata'sını SQL'deki onaylardan tekrar oluşturur. Onay güncellemesinde indeks hatası alınırsa işlemin tamamlandığını varsaymayın; depolama sorununu giderip yeniden başlatın ve paneli/aramayı kontrol edin.

- `rag-rank-crowding` **açıkken:** mevcut zafiyet korunur; yalnızca benzerlik sıralaması kullanılır. Onaylı bir belge de saldırgan belgelerle ilk üç sonuçtan çıkarılabilir.
- **Kapalıyken:** kullanıcı kapsamı uygulandıktan sonra onaylı ve onaysız adaylar ayrı sorgulanır. Her gruptan en fazla `min(100, 8 × sonuç sayısı)` aday alınır; onaylı grup önceliklendirilir ve büyük/küçük harf ile boşluk farkları normalize edilerek kopyalar ayıklanır. Çok sayıda kopyada daha az sonuç dönebilir.
- Onay, sahiplik filtresini aşmaz ve belge içindeki talimatları güvenli yapmaz. Prompt injection ve sahiplik senaryoları kendi anahtarlarıyla devam eder. Hash embedding yaklaşımı eğitim içindir; semantik arama kalite ölçümü değildir.

API: `GET /lab/documents`, `PUT /lab/documents/{id}/trust` ve `{"trusted": true|false}`. İki uç da Admin demo çerez oturumu gerektirir; JWT veya rol yükseltme deneyi bu operatör yetkisini sağlamaz.

## Sağlık, metrikler ve hata takibi

- `GET /health`: mevcut uygulama/DB kontrolü; modeli çalıştırarak sınamaz.
- `GET /ready`: şema revizyonu, etkinse Chroma erişimi ve aktif modelin indirildiği/erişilebilir olduğu kontrol edilir. Başarı 200, bir bağımlılık hazır değilse 503. Model inference veya saldırı başarı garantisi vermez. Native çalıştırmada model sunucusunun `/models` uç noktası kullanılır.
- `GET /lab/metrics`: Admin demo çerez oturumuyla alınan Prometheus metni; HTTP istek sayıları, toplam süre/sayı ve süreç çalışma süresi. Her worker'ın sayaçları ayrıdır ve yeniden başlatmada sıfırlanır. Scraper aynı origin üzerinde geçerli operatör oturumu kullanmalı ve süresi dolan oturumu yenilemelidir; metrik uç noktası internete açılmamalıdır.

Operasyon logları stdout'a JSON olarak yazılır. Her HTTP yanıtı `X-Request-ID` taşır; aynı ID log kaydında bulunur. Uygulama hataları, model izleyici hataları ve başarısız readiness kontrolleri statik olay adı, bileşen ve hata türüyle kaydedilir. Log toplayıcınızda `level=ERROR`, 5xx artışı veya sürekli `/ready` 503 için alarm tanımlayabilirsiniz. Harici izleme servisine otomatik veri gönderilmez.

Operasyon logları sorgu parametrelerini, ham URL parametrelerini, parola/çerez/tokenları, gövdeleri, promptları veya hata mesajlarını kaydetmez. Eğitimdeki `/audit` kayıtları ayrı kalır ve kendi zafiyet anahtarlarına tabidir. Docker komutu ham URL'leri yazabilen Uvicorn access logunu kapatır. Native başlatmada da aynı seçenek kullanılmalıdır:

```bash
uvicorn main:app --host 127.0.0.1 --port 8000 --no-access-log
```

## Kod organizasyonu

`main.py` yalnızca uygulamayı birleştirir. `routes/` HTTP uyarlayıcılarını; `chat_service.py` model bağlamını ve ajan döngüsünü; `observability.py` işletim telemetrisini; `migrations/` şema geçişlerini içerir. Frontend build gerektirmeyen ES modülleridir: `app.js` oturum/sohbeti, `frontend/js/` ise dil, API, katalog, ayarlar, modeller ve belge onayını yönetir. Tarayıcıdan HTTP üzerinden açılır; dosyaya çift tıklayarak çalıştırılmaz.

Doğrulama: varsayılan `pytest` koşusuna migration, veri koruma, onay, zafiyetin tekrar açılması, readiness ve log gizliliği testleri dahildir. `RUN_BROWSER_TESTS=1` modül yükleme, TR/EN metinleri ve belge onayını Chromium ile sınar. PostgreSQL koşusu yalnızca ayrı bir test veritabanında yapılmalıdır.

## Ajan çağrılarında tekrar yürütme

Her `/chat` veya `/chat/image` isteği kendi araç makbuzlarını tutar. Aynı araç ve aynı argümanlar yeni bir model çağrısı kimliğiyle tekrar gelirse araç yeniden çalışmaz; önceki sonuç veya hata modele geri verilir. JSON anahtar sırası ve eşdeğer sayı yazımları (ör. `7` / `7.0`) aynı işlem sayılır. Hatalar da saklanır; bir araç yan etkiyi kaydettikten sonra hata vermiş olabilir.

Tek model yanıtında en fazla bir yeni işlem yürütülür. Diğer yeni çağrılar kanıt izinde `deferred` olarak tutulur ve model geçmişine alınmaz; böylece eski, tahmini argümanlar sonraki isteği yönlendirmez. Model ilk sonucun gerçek içeriğini gördükten sonra sonraki eylemi tekrar planlar. Bu, örneğin dosya okunmadan onun yerine uydurulmuş bir metnin belleğe yazılmasını önler. `MAX_AGENT_STEPS` sınırı geçerlidir; çok uzun planlar sınıra takılabilir.

Kanıt izindeki `executed`, `reused`, `deferred` alanları gerçek yürütmeyi sonuç tekrarından ayırır. Yanıttaki `tool_executions`, `tool_reuses`, `tool_deferred` sayaçları ve arayüzdeki yürütme sayısı buna göre hesaplanır. Makbuz kapsamı tek HTTP isteğidir: sonraki sohbet isteği yeni işlem başlatır. Doğrudan API/MCP çağrıları, ayrı isteklerdeki mükerrer transfer zafiyeti ve mevcut onay kontrolleri kendi davranışını korur.

## Arayüz oturum günlüğü

Model durum sorgusu normalde 15 saniyede bir, indirme sırasında 1.5 saniyede bir çalışır. Bağlantı hatasında aynı durum yalnızca bir kez yazılır; yeniden denemeler 15, 30 ve en fazla 60 saniyeye çıkar. Bağlantı düzelince tek toparlanma kaydı oluşur. HTTP 401, geçersiz oturumu sonlandırıp sorgulamayı durdurur ve giriş ekranını gösterir; ağ kesintisi mevcut oturumu tek başına sonlandırmaz. Bu arayüz davranışı, sunucudaki audit kayıtlarını veya senaryo kontrollerini değiştirmez.
