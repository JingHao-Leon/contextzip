# Security Policy

## Supported versions

Only the latest release receives security fixes. Run `contextzip update` (or `pip install --upgrade contextzip`) to get it.

| Version | Supported |
| ------- | --------- |
| Latest 0.4.x | ✅ |
| Older | ❌ |

## Reporting a vulnerability

**Please do not report security vulnerabilities through public GitHub issues.**

Email **akadeepesh@gmail.com** with:

- a description of the vulnerability,
- steps to reproduce it,
- the potential impact,
- a suggested fix (optional).

You can expect an acknowledgement within **48 hours** and a full response within **7 days**. If the vulnerability is confirmed, a fix will be released as soon as possible and you will be credited in the release notes, unless you'd rather stay anonymous.

## What contextzip does with your code

contextzip is a local CLI tool. It reads your project and writes ZIP archives that **you** then choose to upload to an AI tool. contextzip never uploads the archive itself.

### Network access

Packaging, `apply-zip`, `watch` and the config UI work entirely offline. Only two features make network requests, and only when you use them:

| Feature | What is sent | Where |
|---|---|---|
| `contextzip --prompt "…"` | Your prompt, plus the **paths and sizes** of files that already passed the exclusion rules. File contents are never sent. | Google Gemini API (`generativelanguage.googleapis.com`) |
| `contextzip update` | A request for the latest version number | PyPI (`pypi.org`) |

There is no telemetry, analytics or background "phone home".

### Secrets

contextzip protects secrets in three layers:

1. **Secret files are excluded by default.** `.env` and `.env.*`, private keys (`*.pem`, `*.key`, `id_rsa`, `id_ed25519`, …), keystores, `.npmrc` / `.netrc` / `.pypirc` / `.pgpass`, Docker auth config, AWS credentials, service-account and `*credentials*.json` files, kubeconfigs and Terraform state are left out of every run, including `--git-changes`. Including a folder (`contextzip include src/`) doesn't bring back the secret files inside it.

2. **Secret files you include on purpose are always redacted.** You can bring one of these files back by naming it explicitly (`contextzip include .env`), listing it under `always_include` in `.contextzip/config.json`, or ticking it in `contextzip config --ui`. This is useful when you want the AI to see which environment variables your app expects. Such a file is never zipped as-is, whatever your other settings say:
   - In `.env` files every key, comment and blank line is kept, and **every value is replaced with `[REDACTED]`**.
   - Other secret files are scanned for private-key blocks, API keys, tokens and similar values, and the matches are replaced with `[REDACTED]`.
   - A secret file that isn't text (for example `.p12` or `.jks`) can't be redacted, so it is left out and listed in the report.

3. **Optional scanning of ordinary files.** Set `"limits": {"redact_secrets": true}` to scan every included text file for hardcoded secrets (AWS, Google, GitHub, Slack, Stripe, Anthropic and OpenAI keys, JWTs, private-key blocks and `password = "…"`-style assignments) and mask them in the ZIP copy. Your files on disk are never modified.

Every run writes a report next to the ZIP listing what was redacted and what was left out.

**Redaction is best-effort.** It catches known formats, not every possible secret. A file other than `.env`, such as a private key in an unusual format, can still slip through the pattern scan. Before uploading an archive from a sensitive project, preview it with `contextzip --dry-run --verbose` and check the report.

### Other safeguards

- **Path handling.** Files outside the project directory are never included, and dangling or looping symlinks are skipped.
- **Local manifests.** The hashes `apply-zip` uses are stored next to the ZIP on your machine, never inside it.
- **`apply-zip` never deletes files** and asks before overwriting anything you've changed since the ZIP was made.
- **Config UI.** `contextzip config --ui` binds to `127.0.0.1` only, requires a random one-time session token on every request and shuts itself down after saving or after a period of inactivity.
- **API key storage.** Your Gemini key is stored in your personal config (`~/.config/contextzip/config.json`, or `%APPDATA%\contextzip\config.json` on Windows), never in the project. You can provide it with the `GEMINI_API_KEY` environment variable instead.

## Scope

In scope:

- secrets ending up in an archive despite the rules above,
- path traversal or symlink escapes when packaging or applying a ZIP,
- `apply-zip` writing outside the project directory,
- the config UI being reachable or controllable by another process or site,
- network requests beyond those listed above.

Out of scope: what an AI tool does with an archive after you upload it, and secrets inside files you have chosen to include that the redaction patterns don't recognise. Please still report the second kind if you think a common format should be covered.
