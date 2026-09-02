---
name: Gemini quota handling
description: Durable guidance for Gemini model selection and quota failures in this bot.
---

When Gemini returns HTTP 429 for one model, treat it as model-specific quota pressure first: move to a known compatible fallback instead of waiting and retrying the same exhausted model before considering the whole request failed.

**Why:** The configured latest alias resolved to a model whose free-tier request quota was exhausted, while other generateContent models accepted the same API key. Retrying only the alias left channel posts pending and made the user search appear unavailable.

**How to apply:** Keep the default model and fallback list aligned with models confirmed by the Gemini account. If all fallbacks return 429, preserve the source post as retryable and avoid marking it permanently ignored or processed without analysis.