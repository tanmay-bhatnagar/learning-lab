# Parser skill provenance and review

Downloaded for future development/agent integration; the chat model is not given these skills or shell tools in this increment. The running upload pipeline calls installed Python libraries directly.

## Firecrawl anydoc — official skill

Repository: https://github.com/firecrawl/anydoc
Pinned revision: `261fc257d17c3eab0f673be31c408fd9fdc2171a`
Path: `skills/convert-documents-to-markdown`
Reviewed: `SKILL.md`, 10 September 2026.

Approved procedure for this product: local library conversion only. Upstream's hosted OCR fallback uploads documents externally and is **not enabled**. Scanned PDFs must return an actionable unsupported/OCR-needed result. Upstream `npx -y` examples are not executed on upload; dependencies are installed during development. The source skill remains preserved verbatim.

## Microsoft MarkItDown — community skill, Microsoft library

Microsoft's MarkItDown repository at `2e71e117eab88d482e3095e6fa4c90ccaeb50e73` does not contain a SKILL.md. The downloaded wrapper is explicitly community-authored, not an official Microsoft skill.

Skill repository: https://github.com/coroboros/agent-skills
Pinned revision: `ae772930794ad46c086f7dafe72113ded420aa35`
Path: `skills/markitdown`
Reviewed: `SKILL.md` and `scripts/markitdown.sh`, 10 September 2026.
Library source: https://github.com/microsoft/markitdown

Approved procedure: local PDF conversion via MarkItDown with PDF extras; plugins, cloud document intelligence, URL inputs, and audio services disabled. The upstream wrapper's optional ~/.agents/output destination lies outside the active learning topic, so the app does not invoke that wrapper. Backend writes the returned Markdown beside the immutable PDF inside the selected topic. No skill instructions grant extra filesystem or network permissions.

Skills are project-local references under Code/skills, not installed globally into Codex and not automatically loaded by the app. This preserves their provenance while runtime behavior remains controlled by reviewed application code.
