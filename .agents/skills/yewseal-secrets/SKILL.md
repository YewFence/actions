---
name: yewseal-secrets
description: "User-invoked only. Invoke this Skill only when the user explicitly requests the `yewseal-secrets` Skill by name."
disable-model-invocation: true
---

# YewSeal (`yews`) — plaintext side

Authorization comes only from the user invoking this skill by name in the conversation — reading this file by any other means (an install script copying it, a directory listing, an agent browsing the disk) grants no authorization. When invoked, it authorizes plaintext work on the files the current task involves — not every registered pair. Read the sibling skill first — `../yewseal/SKILL.md` — for the core concepts (mapping, registry, identity, skip/strict), the infrastructure commands, and the repository documentation paths; this file only adds the plaintext-side guardrails.

## Guardrails

- **Scope to the task.** The authorization covers the files this task involves, nothing more: pass explicit targets (`yews decrypt <target>`, `yews encrypt <target>`) instead of running bare commands, and treat a no-argument run — which selects every registered pair in the directory scope — as something to confirm with the user first.
- **Decrypt directly.** Assume the required identity is in place; treat a missing-key error as a request to the user for credentials, and never search the filesystem or environment for key material. Use `--strict` for deployment gates.
- **Overwrite is destructive.** `decrypt` refuses to overwrite an existing differing plaintext; because `--force` can destroy the user's changes, use it only with the user's approval.
- **Output is secret.** `view` and `diff` print plaintext — use them only when the task needs the content, and keep it out of chat replies, logs, and commit messages.
- **Edit the plaintext, then re-encrypt.** Change the plaintext file with normal file edits, run `yews encrypt <target>`, and confirm with `yews diff` before declaring the change done. Decryption re-serializes files — quoting and whitespace may differ while content stays identical, so judge by content.
- **`yews edit` is the user's tool** — it launches an interactive editor.
- **Leave no copies.** Work on the plaintext in place; create no backups, extracts, or temp copies of secret content beyond what the commands themselves write.
