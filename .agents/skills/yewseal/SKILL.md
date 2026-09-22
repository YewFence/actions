---
name: yewseal
description: "Use when a repository uses YewSeal (.yewseal.toml, *.enc.* ciphertext) or the task is managing its encrypted files via YewSeal, the cli `yews`"
---

# YewSeal (`yews`)

YewSeal lets a repository commit encrypted configuration (TOML, YAML, JSON, ENV, INI, binary) while plaintext stays uncommitted. The embedded SOPS engine encrypts every format natively — TOML included, no conversion — with Age keys. The CLI is `yews`; the project config is `.yewseal.toml`.

This skill covers the infrastructure side only: configuration, recipients, encryption, and validation. Decrypting or viewing plaintext secrets is off limits unless the user explicitly authorizes it.

## Core Mental Model

- **Mapping (file pair)** — an `[[encryption.files]]` entry pairing the plaintext side (`config.toml`) with the encrypted side (`config.enc.toml`). YewSeal only ever touches registered pairs; `yews init` scaffolds them.
- **Selection** — command arguments are selectors over registered mappings and only ever narrow. No argument means the current directory scope, never the whole repository.
- **Registry, alias, recipient** — `[recipients.registry]` maps reviewable aliases (`owner`, `teammate`) to public Age keys. Files are encrypted to aliases (file pair > group > `recipients.defaults`); there is no `--public-key` flag, so authorization stays reviewable in code review.
- **Identity** — the private Age key that decrypts: `--key-file` (env `YEWSEAL_KEY_FILE`), then `YEWSEAL_AGE_IDENTITIES`, the compatible `SOPS_AGE_KEY*` sources, and finally `.age/keys.txt` in the working directory. Identities never come from the project config.
- **Protocol file** — encrypted files follow the `.enc.*` naming (`.enc.toml`, …, `.enc.bin`), which keeps group discovery from double-encrypting.
- **Skip, lenient, strict** — "no matching identity" is a skip, not an error (lenient default), so people holding different keys share one repository; `--strict` turns skips into failures for deployment gates.
- **Provenance** — `yews plan` reports where each resolved mapping, format, and authorization came from, exposing config drift before anything is written.
- **SOPS config synchronization** — `encrypt` defaults to generating `.sops.yaml`; it always uses the complete resolved project policy even when its targets select one mapping. It finishes ciphertext work before synchronization, but a synchronization failure still makes the command fail. Use `--sync-sops-config=false` to leave it untouched.

## Help First

Start from the installed CLI, not remembered semantics: read `yews --help` for the command list, then `yews <command> --help` before using any command — the help covers target-selection rules and exit codes. This skill is workflow guidance, not a copy of the parameter reference.

Every YewSeal-defined flag has an environment equivalent shown in its help. Global flags use `YEWSEAL_<FLAG>` and command flags use `YEWSEAL_<COMMAND>_<FLAG>`, with names uppercased and hyphens replaced by underscores; explicit flags take precedence.

Business commands require a project config: without `.yewseal.toml` they fail instead of falling back to defaults. Help, version, and `init` never load the config.

## Essential Workflow

**Setup belongs to the user.** `yews init` generates the owner's private Age key, so it is a user-facing step. When a repository has no `.yewseal.toml`, tell the user to run `yews init` themselves (interactive by default; `--input`/`--output` for scripts) and continue once the config exists.

**Config edits are normal work for you.** `.yewseal.toml` holds no private keys — read it freely, and on the user's request adjust registry aliases and `recipients` (the public-key side). New recipients join by public key only: obtain each `age1...` key through the channel the user provides, or generate the pair when the user asks you to. Finish each edit by validating the file against the config schema (`schema/yewseal.schema.json`) and previewing with plan:

```bash
yews plan                  # preview selection and authorization; writes nothing
yews encrypt               # encrypt in place; commit ciphertext + config
```

**Recipient keypair generation is on-request work.** Run the bundled helper `sh scripts/recipient-keygen.sh <alias>` (relative to this skill). It sends the bare private key to the clipboard, prints the public-key path, and deletes the key file — private key bytes never enter your context. The clipboard is the only copy, so tell the user immediately to save it into their password manager; register the alias from the printed `.pub` file once they confirm.

**Plaintext stays out of scope.** `decrypt`, `view`, and `diff` expose secret content — run them only on the user's explicit authorization. Plaintext files already sitting on disk are equally off limits: general-purpose reads and searches over them leak secrets into your context, so operate through yews subcommands, whose output stays summarized, and read `.yewseal.toml`, never the plaintext. To know which paths to avoid, list them by name with the bundled helper `scripts/plaintext-files.py` (relative to this skill; run it from the repository root or the config directory): it parses `yews plan --json` and prints one registered plaintext path per line — names are safe to see, contents never are.

## Boundaries

- Commit ciphertext, `.yewseal.toml`, and the managed `.sops.yaml`; keep plaintext and `.age/keys.txt` uncommitted (the generated `.gitignore` already excludes them).
- Treat private key material as opaque: never print, output, view, or upload a private key — refer to keys by path or registry alias. `scripts/recipient-keygen.sh` is the one sanctioned way to create a private key file. Backup and distribution are the user's responsibility.
- Treat plaintext content as opaque with the same rigor: no printing, excerpting, or relaying it into chat, logs, or commit messages — plaintext access happens only on the user's explicit authorization.

## Repository Docs

The CLI help is authoritative for flags; the repository markdown is authoritative for concepts and workflows. When this skill's summary is insufficient, read the Markdown in the source repository `github.com/YewFence/YewSeal`:

- Guides: `docs/src/content/docs/guide/` — tutorial, installation, configuration, target-selection, decryption-results, working-with-a-team, private-keys, sops, ci-cd, docker, glossary
- Per-command reference: `docs/src/content/docs/references/` — `yews.md` plus `yews_<command>.md` for encrypt, decrypt, view, diff, edit, plan, init, completion
- Config schema: `schema/yewseal.schema.json` — the quick field-level check for an edited `.yewseal.toml`
- Every-field config example: `schema/example.yewseal.toml`

Fetch a file by whatever route the environment offers: a raw.githubusercontent.com URL for this repository and path, `gh api repos/YewFence/YewSeal/contents/<path>`, or a local checkout.
