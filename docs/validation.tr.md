# Doğrulama rehberi

[English](validation.md) · Türkçe · [README](../README.tr.md)

Komutları Python 3.13 ve `requirements-dev.txt` kurulu ortamda, `vulnlm/` dizininden çalıştırın. Uygulama testleri sınırları ve gerçek etkileri doğrular; canlı deneyler belirli bir modelin davranışını ölçer.

## Uygulama ve dokümantasyon testleri

```bash
python -m pytest -q
python -m pytest tests/test_documentation.py -q
```

Varsayılan paket geçici SQLite, gerçek Chroma, geçici dosyalar ve yerel HTTP sunucuları kullanır. Kontrollü model yanıtları gerçek bağlam oluşturma, araç yürütme ve veri değişikliklerini sınar; canlı modelin saldırıya uyduğunu göstermez. Dokümantasyon testleri Python/Bash sözdizimini, yerel bağlantıları ve API yollarını kontrol eder; doğrudan API örneklerini geçici lab verileriyle çalıştırır. Bu örneklerin Türkçe ve İngilizce sürümleri aynı Python semantiğine sahip olmalıdır.

| Alan | Testler |
|---|---|
| Başlangıç davranışı ve uç noktalar | `tests/test_lab.py`, `tests/test_extensions.py` |
| Korumalı modlar ve meşru kullanım | `tests/test_scenario_controls.py` |
| Araç tekrarları ve birbirine bağlı çağrılar | `tests/test_agent_execution.py` |
| Alt ajan yetkisi, handoff, özyineleme ve bağlam | `tests/test_subagents.py` |
| Ajanlar arası gizli kanal (deterministik model) | `tests/test_covert_channel.py` |
| Migration, belge onayı, readiness ve log gizliliği | `tests/test_operations.py` |
| Model ağ geçidi, seçim, indirme ve yeniden deneme | `tests/test_llm_models.py` |
| Arayüzden tam sistem sıfırlaması | `tests/test_system_reset.py` |
| Kurulum kararları ve hata durumları | `tests/test_installer.py` |
| Yayımlanan örnekler, çeviriler ve bağlantılar | `tests/test_documentation.py` |

## PostgreSQL

```bash
VULNLM_TEST_DATABASE_URL=postgresql+asyncpg://USER:PASSWORD@HOST:5432/TEST_DB python -m pytest -q
```

Yalnızca geçici test veritabanı kullanın: testler tabloları silip yeniden doldurur. Aynı DB’de bir lab veya başka test koşusu çalıştırmayın. Farklı event loop’lar arasında asyncpg bağlantısı paylaşılmaması için test altyapısı `NullPool` kullanır. Bu kontrol tarayıcı testlerinin yerine geçmez.

## Tarayıcı testleri

```bash
python -m playwright install --with-deps chromium
RUN_BROWSER_TESTS=1 python -m pytest tests/test_browser.py -q
```

Gerçek Chromium; XSS, aynı site içinde farklı origin’den CSRF, görsel ekleme, ayarlar/model/belge güveni/sıfırlama pencereleri, ilk açılış kontrolleri ve README’deki belge karşılaştırmasını iki dilde sınar. Belirli çıktı gerektiğinde kontrollü model yanıtı kullanılır. Bu, tarayıcı davranışını doğrular; canlı modelin XSS üreteceğini göstermez. Kurulu Chrome için `CHROME_EXECUTABLE` tam dosya yolunu verin. `RUN_BROWSER_TESTS=1` olmadan bu testler atlanır.

## Canlı model testleri

İndirilmiş bir model ve **Python test sürecinden erişilebilen** bir model uç noktası hazırlayın:

```bash
LLM_API_URL=http://127.0.0.1:11434/v1/chat/completions \
LLM_MODEL=qwen2.5:3b RUN_MODEL_TESTS=1 python -m pytest tests/test_model.py -q
```

Varsayılan Compose, Ollama/gateway portunu host’a yayınlamaz. Yukarıdaki komut ayrıca erişilebilir bir host Ollama gerektirir; Compose için `.env` ayarlamak dahili servisi host’a açmaz. İsteğe bağlı görsel test için `VISION_MODEL` ayarlayın. Test uygulamasının verileri geçicidir. Gözlenen saldırı geçer; gözlenmeyen saldırı gerekçesiyle atlanır; entegrasyon hatası başarısızlıktır. Atlanan saldırı güvenlik başarısı değildir.

### Çalışan laboratuvara karşı deney

Bu betikler yayınlanmış uygulama adresini kullanır; o lab’ın belge, bellek ve sohbet kayıtlarını değiştirir. Deney için ayrılmış bir lab ve rehberde belirtilen anahtarlarla başlayın. Portu `LAB_PORT` ile eşleştirin:

```bash
export VULNLM_URL=http://127.0.0.1:8000
python scripts/model_probe.py --url "$VULNLM_URL" --output model-probe-results.json
```

`--prompt-canary-file` olmadan hidden-context deneyi `UNVERIFIED_NO_ORACLE` verir. Docker’da operatörün elindeki bağımsız referansı sağlamak için:

```bash
mkdir -p test-results
docker compose cp app:/data/private/prompt.txt test-results/prompt-canary.txt
python scripts/model_probe.py --url "$VULNLM_URL" \
  --prompt-canary-file test-results/prompt-canary.txt --output model-probe-results.json
```

Beklenen değer kullanıcı promptuna gönderilmez. Her reset sonrası dosyayı yenileyin. Deney çıktıları prompt ve sentetik sır içerebilir; sürüm kontrolüne eklemeyin.

HTTP sonucu, ajan göndericisi ve isteğe bağlı görsel deneyleri için [genişletilmiş rehberi](extended-scenarios.tr.md) kullanın. Saldırgan sayfaları harici siteye `SITE_PORT` üzerinden yayınlanır; uygulama onlara yayınlanmış host portundan bağımsız olarak `http://cyberdes-vulnerable-cloud.example` adresiyle erişir.

Model matrisi büyük modeller dahil **katalogdaki tüm modelleri** seçer ve gerekirse indirir. Hedef lab’ın verilerini ve model seçimini geçici olarak değiştirir; başka deneyle eşzamanlı çalıştırmayın:

```bash
python scripts/model_matrix.py --url "$VULNLM_URL" --output model-matrix.json
```

Çıkışta önceki modeli yeniden seçmeyi dener; hata veya kesinti sonrası aktif modeli kontrol edin. Hata ve kaynak sınırlarını kaydedin; katalogdaki her modelin makinenizde doğrulandığını varsaymayın.

### İzole gerçek araç yürütmesi

`tool_call_probe.py` geçici SQLite/Chroma/dosyalarla izole uygulama başlatır ve gerçek upstream yanıtlarını kaydeder. 12 aracı çıktı veya bağımsız durum değişimleriyle sınar. Aynı sohbet isteğinde tekrarlanan araç önerisi önceki sonucu kullanmalıdır; çok adımlı örnekte tek okuma ve okunan değerin tam bir bellek kaydı gerekir.

Docker lab çalışırken aşağıdaki komut gateway’i kullanır, lab veri volume’unu geçici anonim volume ile değiştirir. Host Python veya yayınlanmış Ollama portu gerekmez:

```bash
mkdir -p test-results
docker compose run --rm --no-deps -T \
  --volume /data --volume "$PWD:/workspace:ro" \
  --volume "$PWD/test-results:/results" --workdir /workspace \
  app python scripts/tool_call_probe.py --model qwen2.5:3b \
  --chain-runs 5 --output /results/tool-calls.json
```

İmaj derlenmiş ve istenen model yapılandırılmış Ollama’da indirilmiş olmalıdır. Yalnız çok adımlı örnek için `--chain-only` ekleyin. Probe gerçek model kaynaklarını tüketir; ana uygulamanın aktif model seçimini değiştirmez.

## Kanıtı kaydetme ve yorumlama

| Sonuç | Anlamı |
|---|---|
| `PASS` / `FAIL` | Belgelenen uygulama akışına ilişkin belirlenimci doğrulama. |
| `OBSERVED` | Bağımsız kayıt, dosya, bağlam veya tarayıcı kanıtıyla gözlenen etki. |
| `NOT_OBSERVED` | Etki bu koşuda görülmedi; koruma kanıtı değildir. |
| `UNVERIFIED_NO_ORACLE` | İfşayı değerlendirmek için gereken bağımsız referans yok. |
| `ERROR` | Sağlayıcı, taşıma veya entegrasyon hatası; model direnci değildir. |
| `SKIPPED` | Test iddiası doğrulanmadı; raporlanan gerekçeyi okuyun. |

Commit/revizyon, OS, Docker/Compose/Ollama sürümleri, image/model digest’leri, anahtarlar, başlangıç verisi, payload, istek kimliği, araç izi ve tekrar sayısını kaydedin. HTTP 200 veya flag biçimli bir metin tek başına kanıt değildir. Model hatasından önce araç işlemi tamamlanmış olabilir; ikisini de kontrol edin. Hash embedding, arama sınırlarını sınar; semantik kaliteyi ölçmez. Tek koşudan başarı oranı çıkarmayın.

Kurulum testleri Linux/WSL2/macOS, NVIDIA erişimi, CPU’ya dönüş ve host/özel Compose tercihlerini sahte CLI ile sınar. Bunlar gerçek GPU çıkarımını doğrulamaz. Donanım ve model sürümü uyumluluğu hedef makinede gerçek istekle doğrulanmalıdır.
