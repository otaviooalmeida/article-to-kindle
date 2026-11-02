# Article to Kindle

Convert supported web articles into EPUB reading copies for Kindle. Use the CLI for URLs and saved content, or the Chrome extension to capture an article already rendered in your browser.

The project is early-stage: extraction depends on publisher markup, and Kindle rendering can vary. It does not bypass paywalls or transfer browser cookies.

## Features

- Analyze rendered pages with the Standard extractor or explicitly selected AI labeling while preserving original article HTML, code, tables, formulas, and images.
- Compare Standard and AI extraction from the same snapshot; restore AI-excluded blocks in the preview before exporting.
- Extract structured publication dates and include them in the preview and EPUB metadata.
- Convert URLs, saved HTML, Article Capture JSON, or URL lists.
- Preview, edit, and select captured sections in Chrome.
- Optionally submit EPUBs through your SMTP account.

## Install

Requires Python 3.11+. Chrome is needed only for the extension.

```bash
git clone https://github.com/otaviooalmeida/article-to-kindle.git
cd article-to-kindle
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e .
```

On Windows, create the environment with `py -3 -m venv .venv` and activate it with `.venv\Scripts\Activate.ps1`.

## CLI

```bash
# Convert a public article URL
article-to-kindle convert 'https://openai.com/index/chatgpt/' -o article.epub

# Convert saved content
article-to-kindle convert --html saved.html --source-url 'https://openai.com/index/chatgpt/'
article-to-kindle convert --capture capture.json

# Process URL lists and submit an existing EPUB
article-to-kindle batch urls.txt --output-dir reading-copies
article-to-kindle send article.epub --to reader@kindle.com

# Check configuration and dependencies
article-to-kindle doctor
```

Without `-o`, EPUBs are written to `outputs/`. Existing files are not overwritten. Use `--no-images` or `--no-links` to omit images or clickable links. Run `article-to-kindle <command> --help` for options.

Article Capture JSON contains `title`, `author`, `sourceUrl`, and `html` fields. Its HTML is treated as already selected article content: conversion preserves reader selections and intentional repetitions while still sanitizing unsafe markup. Saved HTML requires `--source-url` so relative links and images can be resolved. Batch input contains one URL per line.

## Chrome extension

1. In `chrome://extensions`, enable **Developer mode** and load `web_extension/` with **Load unpacked**.
2. Copy the extension origin shown in its Settings.
3. Run `article-to-kindle setup`; enter the origin and optionally configure SMTP.
4. Copy `ARTICLE_TO_KINDLE_TOKEN` from the generated configuration into the extension settings.
5. For AI mode, install your SSH public key on the GPU host (for example, `ssh-copy-id agrisat@10.230.102.83`). The companion manages a loopback-only SSH tunnel; passwords are never stored in the extension or `.env`.
6. Start the local companion with `article-to-kindle serve`. It preloads `qwen2.5:3b` on the configured Ollama server and keeps it warm.
7. Open an article, launch the extension, select Standard or AI-assisted extraction, then review the result. Use **Compare with AI/standard** to open an independent preview of the same page snapshot. Edit or restore sections before downloading or submitting.

The companion listens only on `127.0.0.1:8765`. Do not expose it to a network. SMTP credentials remain in the local Python configuration, not in Chrome. SSH forwarding targets only the GPU host's `127.0.0.1:11434` Ollama listener and binds locally on `127.0.0.1:11435`; the remote inference server is not exposed publicly. The companion requires working OpenSSH key authentication and strict host-key verification for AI mode.

## Configuration and email

`article-to-kindle setup` creates the local configuration. Shell environment variables override file values. The companion requires `ARTICLE_TO_KINDLE_TOKEN` and `ARTICLE_TO_KINDLE_ALLOWED_ORIGIN`. Email submission additionally requires `SMTP_HOST`, `SMTP_PORT`, `SMTP_USERNAME`, `SMTP_PASSWORD`, and `SMTP_FROM`; `KINDLE_EMAIL` is an optional CLI default. See [`.env.example`](.env.example).

Approve `SMTP_FROM` in Amazon's [Personal Document Settings](https://www.amazon.com/sendtokindle/email) before sending. SMTP acceptance confirms submission to the mail server, not delivery to the Kindle library. EPUB email attachments are limited to 50 MiB.

## Supported pages and limitations

The project accepts HTTP(S) pages from any publisher; it no longer requires a host to be listed in the source code. Outbound requests require public DNS addresses, and local/private destinations and redirects are blocked. This does not mean every page contains an extractable article: the page still needs readable article content, and extraction quality varies by publisher.

CLI URL conversion fetches the page's public HTML but does not execute JavaScript or use browser sessions; use the extension for JavaScript-rendered content already visible in Chrome. The extension accepts public HTTP(S) pages and sends an inert DOM snapshot to the authenticated loopback companion before preview. Standard mode uses Readability with a selector fallback. Opt-in AI mode labels numbered source blocks using `qwen2.5:3b`, preserves their original markup and order, and keeps excluded blocks available for restoration. Long pages are processed in overlapping chunks without truncation; 15 seconds is a performance target, not a timeout. If AI inference fails, the preview is clearly labeled and Standard extraction is shown instead.

AI mode sends article text, small structural labels, and title/author hints through the SSH tunnel to the GPU for inference; it does not send the source URL, link/image addresses, cookies, or browser credentials. Article content is not written to remote files or logged by this application. The model remains loaded while in use. An unusually long article may take longer; readers can switch to Standard extraction or compare both results from the same snapshot. Publication dates come from structured metadata or explicit date metadata, not guesses from article prose. Neither path bypasses paywalls or transfers browser cookies.

Formula conversion uses MathML where possible; unsupported formulas remain text with a warning. Image and layout compatibility depends on the source site and Kindle software.

## Development and contributions

```bash
python -m unittest discover -s tests -v
article-to-kindle self-test
```

Browser fixture tests require Chrome or Chromium. Report bugs or propose changes through [GitHub Issues](https://github.com/otaviooalmeida/article-to-kindle/issues). Include the source URL when shareable, expected and actual behavior, and relevant warnings. Do not include cookies, private article content, or credentials.

## License

[Apache License 2.0](LICENSE). Source articles remain subject to their authors' rights and terms; use generated copies only where permitted.
