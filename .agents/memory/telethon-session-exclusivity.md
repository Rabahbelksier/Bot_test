---
name: Telethon session exclusivity
description: Telegram MTProto StringSession behavior when multiple workers use the same session.
---

The same Telethon `StringSession` must not be used concurrently from different IP addresses.
Telegram can invalidate the authorization key with `AuthKeyDuplicatedError`; a restart alone
does not repair it.

**Why:** Channel monitoring and source-photo downloads depend on the MTProto user session, while
the Bot API can continue serving users even when that monitor cannot connect.

**How to apply:** Keep one active worker per session. If the authorization key is duplicated,
generate and store a genuinely new session securely, and stop the other worker using the old one
before testing channel history or photo delivery.