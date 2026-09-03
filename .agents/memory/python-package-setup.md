---
name: Python package setup
description: Workspace side effects to watch for when installing Python dependencies.
---

Package installation may rewrite `requirements.txt` and reconcile workspace files as part of dependency setup. Always inspect `git status` and the relevant diffs after package operations, then re-check that the intended application edits are still present.

**Why:** Installing the Telegram dependencies introduced a conflicting `telegram` package and temporarily changed the dependency file, while application edits needed to be verified again afterward.

**How to apply:** Finish package setup before the main code-editing pass when possible. If installation is needed mid-task, treat it as a state boundary and re-verify/reapply code changes before testing or delivery.