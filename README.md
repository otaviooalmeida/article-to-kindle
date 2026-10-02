# Article to Kindle

Convert supported web articles into EPUB reading copies for Kindle. Use the CLI for URLs and saved content, or the Chrome extension to capture an article already rendered in your browser.

The project is early-stage: extraction depends on publisher markup, and Kindle rendering can vary. It does not bypass paywalls or transfer browser cookies.

## Features

- Preserve article text, headings, code, tables, formulas, and editorial images.
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

Article Capture JSON contains `title`, `author`, `sourceUrl`, and `html` fields. Saved HTML requires `--source-url` so relative links and images can be resolved. Batch input contains one URL per line.

## Chrome extension

1. In `chrome://extensions`, enable **Developer mode** and load `web_extension/` with **Load unpacked**.
2. Copy the extension origin shown in its Settings.
3. Run `article-to-kindle setup`; enter the origin and optionally configure SMTP.
4. Copy `ARTICLE_TO_KINDLE_TOKEN` from the generated configuration into the extension settings.
5. Start the local companion with `article-to-kindle serve`.
6. Open a supported article, launch the extension, and preview or edit the capture. Download the EPUB or submit it to Kindle.

The companion listens only on `127.0.0.1:8765`. Do not expose it to a network. SMTP credentials remain in the local Python configuration, not in Chrome.

## Configuration and email

`article-to-kindle setup` creates the local configuration. Shell environment variables override file values. The companion requires `ARTICLE_TO_KINDLE_TOKEN` and `ARTICLE_TO_KINDLE_ALLOWED_ORIGIN`. Email submission additionally requires `SMTP_HOST`, `SMTP_PORT`, `SMTP_USERNAME`, `SMTP_PASSWORD`, and `SMTP_FROM`; `KINDLE_EMAIL` is an optional CLI default. See [`.env.example`](.env.example).

Approve `SMTP_FROM` in Amazon's [Personal Document Settings](https://www.amazon.com/sendtokindle/email) before sending. SMTP acceptance confirms submission to the mail server, not delivery to the Kindle library. EPUB email attachments are limited to 50 MiB.

## Supported sites and limitations

The current host allowlist includes Medium, Towards Data Science, Substack, DEV, Hashnode, KDnuggets, Analytics Vidhya, Machine Learning Mastery, The Gradient, Papers with Code, Hugging Face, DeepLearning.AI, Google Research, Microsoft, Meta AI, and OpenAI, including subdomains.

URL conversion fetches public HTML and does not execute JavaScript or use your browser session. Use the extension for content already rendered in Chrome. Formula conversion uses MathML where possible; unsupported formulas remain text with a warning. Image and layout compatibility depends on the source site and Kindle software.

## Development and contributions

```bash
python -m unittest discover -s tests -v
article-to-kindle self-test
```

Browser fixture tests require Chrome or Chromium. Report bugs or propose changes through [GitHub Issues](https://github.com/otaviooalmeida/article-to-kindle/issues). Include the source URL when shareable, expected and actual behavior, and relevant warnings. Do not include cookies, private article content, or credentials.

## License

[Apache License 2.0](LICENSE). Source articles remain subject to their authors' rights and terms; use generated copies only where permitted.
