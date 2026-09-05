---
name: AI intent composition
description: Design rule for interpreting Telegram product-search requests with a primary goal plus independent filters.
---

The AI search intent is compositional: `trending`, `product_best`, and the other request types describe the primary goal, while category, product keywords, price bounds, RAM, and storage remain independent filters. Never discard those filters just because the primary type is `trending`.

**Why:** A request such as “today’s trending phone offers only” was previously treated as a broad trending query, allowing unrelated products to reach the result list.

**How to apply:** Preserve every explicit constraint in the normalized intent, apply category/product/specification matching before ranking or deduplicating trending results, and keep unsupported requests on the existing supported-capabilities response.