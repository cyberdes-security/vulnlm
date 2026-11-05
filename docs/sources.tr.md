# Kaynaklar

[English](sources.md) · Türkçe · [README](../README.tr.md)

VulnLM, güvenlik deneylerini düzenlemek için OWASP risk kategorileri ve CWE kimliklerini kullanır. Senaryolar uygulamaya özgü eğitim örnekleridir. Eşleştirme ilgili güven sınırını belirtir; kategorinin tüm risklerinin kapsandığı anlamına gelmez.

- [OWASP GenAI LLM Top 10 2026](https://genai.owasp.org/resource/owasp-genai-llm-top-10-2026/): LLM risk kategorileri.
- [OWASP Top 10 for Agentic Applications 2026](https://genai.owasp.org/resource/owasp-top-10-for-agentic-applications-for-2026/): ajan belleği, araç kullanımı ve onay sınırları.
- [MCP araç belirtimi](https://modelcontextprotocol.io/specification/2025-11-25/server/tools): araç tanımları, `tools/list` ve `tools/call` mesajları.

## Kategori eşleştirmesi

| Kategori | Lab kimliği |
|---|---|
| Aşırı yetkili ajan davranışı | LLM03 |
| Veri ve model zehirlenmesi | LLM04 |
| Sınırsız kaynak tüketimi | LLM06 |
| Gizli bağlamın açığa çıkması | LLM08 |
| Vektör ve embedding zayıflıkları | LLM09 |
| Uygun olmayan çıktı işleme | LLM10 |

Eşleştirmeleri proje yönetir; OWASP onayı anlamına gelmez.

## Kapsam

Lab; metin ve isteğe bağlı görsel injection, bilgi getirme, kalıcı bellek, araç yürütme, yetkilendirme ve web uygulama zafiyetlerini kapsar. Görsel senaryolar uyumlu bir görsel model gerektirir.

Model/ince ayar zehirlenmesi, `model-backdoor` senaryosunda katalogdan seçilen kasıtlı backdoorlu bir modelle gösterilir; model harici olarak eğitilip Hugging Face'e yayımlanır ve laboratuvar kendisi model eğitmez. PDF/OCR ve belirli üçüncü taraf CVE’lerinin yeniden üretimi kapsam dışıdır. Python, uygulama süreci yetkileriyle çalışır. `/mcp`, protokolün belgelenen eğitim alt kümesini uygular; desteklenen mesajlar ve taşıma sınırları [deney rehberindedir](walkthrough.tr.md#mcp-eğitim-alt-kümesi).

## Çalışma ortamı kaynakları

- [Ollama FAQ](https://docs.ollama.com/faq): sunucu dinleme adresi ve GPU kullanımı (`ollama ps`).
- [Qwen3-VL 4B Instruct](https://ollama.com/library/qwen3-vl:4b-instruct): model yetenekleri ve minimum Ollama sürümü.
- [Qwen3.8 27B](https://ollama.com/library/qwen3.8:27b): model yetenekleri ve model dosyaları.
- [Docker Compose GPU ayırma](https://docs.docker.com/compose/how-tos/gpu-support/): kurulum betiğinin kullandığı NVIDIA cihaz ayarı.
- [Docker Desktop GPU desteği](https://docs.docker.com/desktop/features/gpu/): Windows/WSL2 GPU ön koşulları.

Kaynaklar 2026-10-29 tarihinde kontrol edildi. Model etiketleri, dosyaları ve üretici gereksinimleri değişebilir; uyumluluğu kurulu çalışma ortamı ve gerçek istek belirler.
