# References

English · [Türkçe](sources.tr.md) · [README](../README.md)

VulnLM scenarios use OWASP risk categories and CWE identifiers to organize security exercises. The scenarios are application-specific training examples. Category mappings describe the relevant trust boundary and do not imply coverage of every risk within a category.

- [OWASP GenAI LLM Top 10 2026](https://genai.owasp.org/resource/owasp-genai-llm-top-10-2026/): reference for LLM risk categories.
- [OWASP Top 10 for Agentic Applications 2026](https://genai.owasp.org/resource/owasp-top-10-for-agentic-applications-for-2026/): reference for agent memory, tool use, and approval boundaries.
- [MCP tools specification](https://modelcontextprotocol.io/specification/2025-11-25/server/tools): reference for tool definitions, `tools/list`, and `tools/call` messages.

## Category mapping

| Category | Lab identifier |
|---|---|
| Excessive agency | LLM03 |
| Data and model poisoning | LLM04 |
| Unbounded consumption | LLM06 |
| Hidden context exposure | LLM08 |
| Vector and embedding weaknesses | LLM09 |
| Improper output handling | LLM10 |

Mappings are maintained by the project and do not represent OWASP endorsement.

## Scope

The lab covers text and optional image-based injection, retrieval, persistent memory, tool execution, authorization, and web application vulnerabilities. Image scenarios require a compatible vision model.

Model/fine-tuning poisoning is demonstrated by the `model-backdoor` scenario through a deliberately backdoored model selected from the catalogue; the model is trained out of band and published to Hugging Face, and the lab itself does not train models. The `agent-covert-channel` scenario models a cross-agent CPU-cache covert channel deterministically for a reproducible switch and tests; `scripts/cache_covert_probe.py` is an opt-in real-timing demonstration and is not a reliable channel. PDF/OCR and reproductions of specific third-party CVEs are outside the lab scope. Python execution uses application process privileges. The `/mcp` endpoint implements the documented training subset of the protocol; supported messages and transport limits are described in the walkthrough.

## Runtime references

- [Ollama FAQ](https://docs.ollama.com/faq): server binding and GPU residency (`ollama ps`).
- [Qwen3-VL 4B Instruct](https://ollama.com/library/qwen3-vl:4b-instruct): model capabilities and Ollama minimum version.
- [Qwen3.8 27B](https://ollama.com/library/qwen3.8:27b): model capabilities and artifact details.
- [Docker Compose GPU reservations](https://docs.docker.com/compose/how-tos/gpu-support/): the NVIDIA device reservation used by the installer.
- [Docker Desktop GPU support](https://docs.docker.com/desktop/features/gpu/): Windows/WSL2 GPU prerequisites.

These references were checked on 2026-10-29. Model tags, artifacts and vendor requirements can change; the installed runtime and a real request determine compatibility.
