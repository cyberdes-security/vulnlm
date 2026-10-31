# Katkı rehberi

[English](CONTRIBUTING.md) · Türkçe

Komutları `docker-compose.yml`, `backend/`, `frontend/` ve `scripts/` bulunan depo kökünden çalıştırın. Senaryo değiştirmeden önce [kurulum rehberini](docs/installation.tr.md) ve [deney rehberini](docs/walkthrough.tr.md) okuyun. İngilizce ve Türkçe dokümantasyon birlikte güncellenir.

## Sorun bildirme

Varsa deponun issue sistemini kullanın. Şunları ekleyin:

- Commit/revizyon, işletim sistemi, Docker/Compose sürümleri ve Docker veya host Ollama kullanımı.
- Modele bağlı davranışlarda model adı/digest’i ve aktif senaryo ayarları.
- Sorunu yeniden üreten en küçük istek veya arayüz adımları; beklenen ve gerçekleşen durum/etki.
- Kimlik bilgileri, oturum çerezleri ve kişisel bilgiler temizlenmiş log veya araç kanıtları.

Kasıtlı senaryo zafiyetiyle gerilemeyi ayırın. Modelin reddetmesi geçerli bir deney sonucudur; taşıma hatası entegrasyon sorunudur. Raporlarda gerçek hassas veri kullanmayın.

## Senaryo değiştirme

Zafiyetli modu yeniden üretilebilir, korumalı modu meşru işlemler için kullanılabilir tutun. Kontrol ID’sini, etkilenen API/araç/arayüz yolunu, ön koşulları ve gözlemlenebilir etkileri belirtin. Durum değişikliklerini model metniyle değil kayıt veya dosyayla doğrulayın. Deneyle ilgisiz kimlik doğrulama ve ağ sınırlarını koruyun.

Payload, durum kodu, arayüz etiketi, sıfırlama davranışı veya model gereksinimi değiştiğinde iki dildeki rehberleri de güncelleyin. Her iki dilde aynı payload ve beklenen etkileri kullanın. Şema değişiklikleri için yeni migration ekleyin; uygulanmış revizyonları değiştirmeyin.

## Değişikliği doğrulama

Python 3.13 ve geçici test ortamı kullanın:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements-dev.txt
python -m pytest -q
python -m playwright install --with-deps chromium
RUN_BROWSER_TESTS=1 python -m pytest tests/test_browser.py -q
```

Varsayılan testler geçici SQLite/Chroma kullanır. `VULNLM_TEST_DATABASE_URL`, tabloları **silinip yeniden oluşturulan** veritabanını seçer; çalışan lab’a yönlendirmeyin. Canlı model testleri isteğe bağlıdır ve model güvenliği garantisi vermez. PostgreSQL, probe’lar ve kanıt yorumlama için [doğrulama rehberine](docs/validation.tr.md) bakın.

Arayüzün model sorgulama ve oturum davranışı için Node.js 20+ ile, Docker veya model sunucusu olmadan:

```bash
node --experimental-vm-modules --test tests/frontend_polling.test.mjs
```

## Sürekli entegrasyon

[GitHub Actions CI](.github/workflows/ci.yml), push ve pull request’lerde çalışır; elle de başlatılabilir. Kurulum/Compose yapılandırması, SQLite üzerinde Chromium dahil test paketi ve ayrı PostgreSQL testleri kontrol edilir. Gerçek model testleri CI’de kapalıdır; Ollama veya API anahtarı gerekmez. JUnit raporları başarısız koşularda da artifact olarak saklanır. README rozeti bu workflow’un gerçek durumunu gösterir.

## Değişikliği sunma

Değişikliği odaklı tutun. Tetikleyiciyi, sonuç davranışını, yapılan doğrulamayı ve test edilmemiş ortamları açıklayın. Yalnızca birim testlerine dayanarak “güvenli” veya “kurumsal kullanıma hazır” demeyin. Kod ve dokümantasyon mevcut [BSD 3-Clause lisansı](LICENSE) altında dağıtılır; lisans bildirimlerini koruyun.
