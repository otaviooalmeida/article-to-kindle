# Article to Kindle

Create Kindle-ready EPUBs from web articles, with optional email submission to Kindle. Use the CLI for public URLs and automation, or the Chrome extension to capture an article already rendered in your browser.

**Status:** early-stage software. Website layouts and Kindle conversion can vary; review the generated reading copy before relying on it. This project does not bypass paywalls or transfer browser cookies.

## Features

- Preserve article text, headings, code, tables, formulas, and editorial images.
- Convert public URLs, saved HTML, or Article Capture JSON into EPUBs.
- Override metadata and omit images or clickable links.
- Process URL lists sequentially, with per-article results and JSON output.
- Submit new or existing EPUBs through your own SMTP configuration.
- Review, edit, and select captured content in the Chrome extension.
- Diagnose dependencies, companion pairing, and SMTP configuration.

SMTP acceptance confirms a **Kindle Submission**, not that Amazon has converted or added the document to your Kindle library.

## Requirements

- Python **3.11+** and pip.
- Internet access for URL conversion and remote images.
- Chrome for the optional browser extension.
- An SMTP account and a Kindle email address for optional email submission.

EPUB creation does not require SMTP configuration. The extension requires the local Python companion; it is not standalone.

## Quickstart

```bash
git clone https://github.com/otaviooalmeida/article-to-kindle.git
cd article-to-kindle
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e .

article-to-kindle self-test
article-to-kindle convert 'https://openai.com/index/chatgpt/' --output chatgpt.epub
```

On Windows, create the environment with `py -3 -m venv .venv`, then activate it in PowerShell with `.venv\Scripts\Activate.ps1`. You can also invoke `.venv\Scripts\article-to-kindle.exe` directly without activation.

Use `python -m pip install .` for a non-editable installation. The installed command works outside the checkout. `python -m cli` and the original `./article_to_kindle.py` launcher are also supported.

## CLI usage

### Convert an article

```bash
article-to-kindle convert 'https://openai.com/index/chatgpt/'
article-to-kindle convert 'https://openai.com/index/chatgpt/' -o article.epub --no-images --no-links
article-to-kindle convert 'https://openai.com/index/chatgpt/' --title 'Custom title' --author 'Custom author'
```

Without `--output`, files are saved in `outputs/` under the current directory, using the title and a source-URL hash. Existing files are not overwritten. An explicit output path requires an existing parent directory.

- `--no-images` removes images before extraction, so they are not downloaded.
- `--no-links` keeps link text and plain-text source attribution; EPUB navigation still works.
- `--dry-run` creates an EPUB without sending email. It is equivalent to the default conversion behavior, **not** a no-write simulation.

Progress and content warnings appear on stderr. Human-readable results appear on stdout. Warnings identify omitted images and formulas retained as text.

### Convert saved content

```bash
article-to-kindle convert --html saved.html --source-url https://openai.com/index/chatgpt/ -o article.epub
article-to-kindle convert --capture capture.json -o article.epub
article-to-kindle convert --html - --source-url https://openai.com/index/chatgpt/ --title 'Saved article' < saved.html
```

Saved HTML must be UTF-8 and no larger than 10 MiB. Its original supported `--source-url` is required to resolve relative assets. Both input formats accept `-` for stdin.

Article Capture JSON requires these non-empty string fields:

```json
{
  "title": "Article title",
  "author": "Author name",
  "sourceUrl": "https://openai.com/index/chatgpt/",
  "html": "<article>...</article>"
}
```

Capture metadata can be overridden with `--title` and `--author`. Extra fields, including `kindleEmail`, are ignored; captured content cannot enable submission or change local settings. Remote images still require network requests unless `--no-images` is set. The extension does not currently expose a capture-JSON export button.

### Submit to Kindle

[Configure SMTP](#configuration) and approve your `SMTP_FROM` address in Amazon's [Personal Document Settings](https://www.amazon.com/sendtokindle/email) first. Use your Kindle destination email, not your Amazon sign-in address.

```bash
article-to-kindle convert 'https://openai.com/index/chatgpt/' --send --to reader@kindle.com
article-to-kindle send article.epub --to reader@kindle.com
```

`--to` overrides the optional `KINDLE_EMAIL` default. Conversion with `--send` validates configuration before fetching. Attachments must not exceed **50 MiB**. SMTP uses implicit TLS on port 465 and STARTTLS on other ports.

A failed submission retains the EPUB and reports its path. `send` reads the existing EPUB without fetching the article again. Do not retry blindly after a connection failure: SMTP acceptance may be uncertain, and another attempt could create a duplicate submission.

### Process a URL list

```bash
article-to-kindle batch urls.txt --output-dir reading-copies --no-images --json
article-to-kindle batch - --send --to reader@kindle.com < urls.txt
```

Provide one URL per line. Blank lines, `#` comment lines, and exact duplicate URLs are skipped. A batch accepts at most **1,000 unique URLs**, creates its output directory, and continues after individual failures. Submission is opt-in; failed submissions are never automatically retried.

JSON results contain per-article paths, warnings, errors, and submission states. Interrupted batches retain completed results. Re-running a batch can resend successful articles; select retries from the results instead.

### Diagnostics and scripting

```bash
article-to-kindle doctor                              # Offline dependency checks
article-to-kindle doctor --companion                  # Pairing and local health
article-to-kindle doctor --smtp --to reader@kindle.com # Offline submission configuration
article-to-kindle doctor --smtp-login                 # Explicit TLS/login test; no email sent
article-to-kindle convert 'https://openai.com/index/chatgpt/' --json
article-to-kindle --version
article-to-kindle convert --help
```

Diagnostics redact tokens and passwords. They cannot verify Amazon sender approval or Kindle Delivery. `--debug` includes tracebacks on stderr; redact sensitive details before sharing logs.

`--json` works before or after `convert`, `batch`, `send`, `doctor`, and `self-test`. Stdout contains one JSON object with `schemaVersion: 1`, `command`, `status`, and `exitCode`, plus command-specific fields. Operational and argument errors include an `error` object; diagnostics report failed checks. Failed submissions preserve the saved output path. Submission states include `not_requested`, `smtp_accepted`, and `unconfirmed`.

Interactive `setup` and long-running `serve` reject `--json`. Help and version output remain plain text.

| Exit code | Meaning |
| --- | --- |
| `0` | Success |
| `1` | Operational or diagnostic failure; all batch articles failed |
| `2` | Invalid arguments |
| `3` | Some batch articles failed |
| `130` | Interrupted |

Legacy `article_to_kindle.py URL`, `--serve`, and `--self-test` invocations remain supported. Incompatible modes are rejected.

## Chrome extension

1. Open `chrome://extensions`, enable **Developer mode**, and choose **Load unpacked** → `web_extension/`.
2. Open the extension's **Settings** and copy its displayed `chrome-extension://…` origin.
3. Run `article-to-kindle setup`. Enter the origin and optionally configure SMTP. Existing configuration requires explicit `--force` to update.
4. Copy `ARTICLE_TO_KINDLE_TOKEN` from the saved file into the extension's bearer-token field. Keep the server URL at `http://127.0.0.1:8765`.
5. Run `article-to-kindle serve` and leave that terminal open. Verify pairing from another terminal with `article-to-kindle doctor --companion`.
6. Open an article, click the extension, and choose **Preview & select content**. Use **Edit** to change metadata/text or omit sections, then download the EPUB or enter your Kindle email and submit it.

The companion binds only to `127.0.0.1:8765` and requires both the shared token and the configured extension origin. SMTP credentials stay in Python configuration, not Chrome. Stop the companion with Ctrl+C.

The extension's Amazon setup guide currently displays `articletokindle@gmail.com`. If you configure another sender, approve your actual `SMTP_FROM` address instead.

## Configuration

Use interactive `article-to-kindle setup`, or copy [`.env.example`](.env.example) and edit its values. Setup generates a strong token, hides password entry, and preserves comments/unrelated settings when updating with `--force`. It never sends a test email.

| Setting | Purpose |
| --- | --- |
| `ARTICLE_TO_KINDLE_TOKEN` | Companion bearer token: at least 32 printable ASCII characters, without whitespace |
| `ARTICLE_TO_KINDLE_ALLOWED_ORIGIN` | Exact `chrome-extension://<32-character-ID>` origin, without a trailing slash |
| `SMTP_HOST` | SMTP hostname, not a URL |
| `SMTP_PORT` | SMTP port; default `587` |
| `SMTP_USERNAME`, `SMTP_PASSWORD` | SMTP credentials |
| `SMTP_FROM` | Sender address approved in Amazon settings |
| `KINDLE_EMAIL` | Optional CLI recipient default; the extension asks for its own destination |

Configuration selection:

1. `--config FILE` before or after the command.
2. The `ARTICLE_TO_KINDLE_CONFIG` environment variable.
3. The checkout's `.env` for source/editable installations; otherwise `$XDG_CONFIG_HOME/article-to-kindle/.env` (normally `~/.config/article-to-kindle/.env`) or `%APPDATA%/article-to-kindle/.env` on Windows.

Shell variables take precedence over file values. The file supports simple `KEY=VALUE` entries and quoted values, not shell expansion. Setup creates private files with mode `0600` on POSIX; protect the containing folder with appropriate ACLs on Windows. Do not commit configuration files, tokens, or SMTP passwords.

## Supported sites and limitations

The current host allowlist includes Medium, Towards Data Science, Substack, DEV, Hashnode, KDnuggets, Analytics Vidhya, Machine Learning Mastery, The Gradient, Papers with Code, Hugging Face, The Batch (`deeplearning.ai`), Google Research Blog (`research.googleblog.com`), Microsoft, Meta AI (`ai.meta.com`), and OpenAI, including their subdomains.

Extraction uses semantic content candidates and JSON-LD/Open Graph/DOM metadata rather than dedicated adapters for every site. An allowed host does not guarantee compatibility with every article or current site layout.

- URL conversion fetches public HTML; it does not execute JavaScript or inherit your browser session. Use browser capture for already-rendered, session-dependent content.
- Only content provided by the source is available. Withheld subscription content is not retrieved.
- Formulas are preserved as MathML where possible. Failed conversions remain identifiable as text with warnings; rendering can vary by Kindle software.
- WebP images are converted to JPEG. JPEG, PNG, GIF, and SVG are otherwise preserved.
- Source HTML is limited to 10 MiB; individual images to 5 MiB; total image assets to 50 MiB before packaging.
- Image requests contact source hosts; optional submission transfers the EPUB through your SMTP provider to Amazon. Local processing is not fully offline processing.
- EPUB language metadata currently defaults to English.

Do not expose the companion over a LAN or the internet. Its authentication and image-fetching model are intended for local use.

## Development and contributing

Install from the checkout with `python -m pip install -e .`, then run:

```bash
python -m unittest discover -s tests -v
article-to-kindle self-test
```

Browser fixture checks, when present, require Chrome or Chromium. Automated checks do not replace manually testing the installed extension, EPUB download, and submission to your own test recipient.

| Path | Responsibility |
| --- | --- |
| `cli/` | Commands, reporting, saved inputs, batch processing, setup, diagnostics |
| `backend/` | Extraction, reading preferences, EPUB packaging, configuration, SMTP, FastAPI |
| `web_extension/` | Chrome MV3 capture, preview/editing, settings |
| `tests/` | CLI and backend regression tests |
| `article_to_kindle.py` | Compatibility launcher with local venv detection |

Report bugs and propose changes through [GitHub Issues](https://github.com/otaviooalmeida/article-to-kindle/issues). For extraction issues, include the source URL when shareable, expected behavior, actual behavior, and a minimal non-sensitive HTML example. Include the Python/application version and relevant warnings for CLI problems.

Keep contributions focused, add regression tests for behavior changes, update affected documentation, and use conventional commit messages. Never attach browser cookies, private article content, `.env` files, or credentials to issues or pull requests.

## License

[Apache License 2.0](LICENSE). Source articles remain subject to their authors' rights and terms; use generated reading copies only where you have permission.
