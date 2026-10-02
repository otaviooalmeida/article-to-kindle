# Article to Kindle

Capture a rendered webpage article (such as Medium and TowardsDataScience), preserve its text, formulas, and editorial images, and turn it into a Kindle-ready EPUB.

## Structure

```text
article_to_kindle.py       # launcher da CLI
cli/main.py                # comandos CLI e --serve
backend/api.py             # API FastAPI autenticada
backend/extractor.py       # captura, sanitização, MathML e imagens
backend/epub.py            # pacote EPUB
backend/delivery.py        # adaptador SMTP
backend/config.py          # ambiente e limites
backend/models.py          # Article e ImageAsset
web_extension/             # extensão Chrome MV3
  popup.*                  # abre a prévia do Article Capture
  preview.*                # revisão, edição e seleção do conteúdo
  preview-core.js          # sanitização e serialização da prévia
  capture-store.js         # transporte temporário da captura para a prévia
  content.js               # captura DOM renderizado
  service-worker.js        # injeta captura após clique
  options.*                # URL e token locais
```

## Install

```bash
python3 -m venv .venv
.venv/bin/pip install .
.venv/bin/article-to-kindle --help
```

The installed `article-to-kindle` command works outside the checkout; `python -m cli` is also supported. For editable development installs, use `.venv/bin/pip install -e .`. Python 3.11+ is required. On Windows, use `.venv\\Scripts\\python.exe` / `.venv\\Scripts\\pip.exe` / `.venv\\Scripts\\article-to-kindle.exe`. The repository launcher remains available and detects either venv layout. `--version` reports the companion version.

The Python package does not install the Chrome extension automatically: load `web_extension/` separately as described below. `requirements.txt` remains available for dependency-only source setups.

## Chrome extension and local server

1. Open `chrome://extensions`, enable Developer mode, choose **Load unpacked**, and select the `web_extension/` directory.
2. Open the extension settings and copy the displayed `chrome-extension://...` origin.
3. Copy `.env.example` to `.env` and fill in the local API and SMTP settings. The extension asks for the Kindle destination email in its Send panel; `KINDLE_EMAIL` remains the CLI `--send` default. The application loads `.env` automatically; shell variables take precedence.

```bash
cp .env.example .env
# Edit .env and replace the placeholder values.
```

4. Put the same token in the extension settings and save.
5. Start the local server and leave it running:

```bash
./article_to_kindle.py --serve
```

6. Visit a supported article and open the extension. The preview shows the article and images; use **Edit** to change text or select sections. The **Include images** and **Permit links** switches control EPUB content. Enter the Kindle destination address in the left Send panel. Before sending, approve `articletokindle@gmail.com` in Amazon Personal Document Settings and ensure the local SMTP `SMTP_FROM` address matches.

The server listens only on `127.0.0.1:8765`. SMTP acceptance is a Kindle Submission, not proof that Amazon has added the document to the Kindle library. Email EPUBs are limited to 50 MiB.

## CLI

```bash
./article_to_kindle.py convert 'https://medium.com/@user/article-slug'
./article_to_kindle.py convert 'https://openai.com/article' -o article.epub --send --to reader@kindle.com
./article_to_kindle.py send article.epub --to reader@kindle.com
./article_to_kindle.py serve
./article_to_kindle.py self-test
./article_to_kindle.py doctor
./article_to_kindle.py doctor --companion --smtp
./article_to_kindle.py setup --config ~/.config/article-to-kindle/.env
```

The original `./article_to_kindle.py URL`, `--serve`, and `--self-test` syntax remains supported. Incompatible modes are rejected rather than ignored. `--dry-run` creates an EPUB without sending; it is an explicit alias for the default conversion behavior, not a no-write simulation. `send` reads metadata from an existing EPUB and never fetches the Article Page again.

Without `--output`, the EPUB is saved under `outputs/`. Use `--output article.epub` for another path, or `--send` to submit it through SMTP. `--to reader@kindle.com` overrides `KINDLE_EMAIL` when sending. Submission configuration is checked before fetching, and EPUB attachments must not exceed 50 MiB.

Progress and content warnings appear on stderr; the title, author, image count, and saved path appear on stdout. `--debug` includes tracebacks. If submission fails, the EPUB is retained. Do not retry blindly after an uncertain SMTP result: Amazon delivery may still be pending.

### Reading Copy preferences and saved inputs

```bash
./article_to_kindle.py convert URL --no-images --no-links --title 'Reading title' --author 'Ada'
./article_to_kindle.py convert --html saved.html --source-url https://openai.com/article -o article.epub
./article_to_kindle.py convert --capture capture.json -o article.epub
./article_to_kindle.py convert --html - --source-url https://openai.com/article --title 'Saved article' < saved.html
```

`--no-images` omits images before extraction, so they are not downloaded. `--no-links` preserves link text and plain-text source attribution without clickable URLs in the article (EPUB navigation still works). Defaults retain images and links. Metadata overrides are also available for saved inputs.

Saved HTML must be UTF-8, within 10 MiB, and supplied with its original supported `--source-url` to resolve relative assets. Article Capture JSON requires non-empty string `title`, `author`, `sourceUrl`, and `html` fields; use `--capture -` for stdin. Its metadata is preserved unless overridden. Extra fields such as `kindleEmail` are ignored: submission always requires explicit CLI intent and local configuration. Image retrieval can still use the network unless `--no-images` is set.

URL conversion fetches public HTML, not a browser-rendered page. For JavaScript-rendered or session-dependent Available Article Content, use browser capture. Neither workflow transfers cookies or bypasses paywalls. Saved capture input is supported, but the extension does not yet provide a capture-JSON export button.

### Setup and diagnostics

`setup` asks for the extension origin, generates a strong pairing token, and optionally collects SMTP settings using a hidden password prompt. It never submits an article or sends a test email. Existing files require explicit `--force`; comments and unrelated settings are preserved. Config files are created with private permissions (0600 on POSIX; protect the containing folder with appropriate ACLs on Windows). Copy the token from the file into extension Settings.

`doctor` checks Python and dependencies offline. Add `--companion` to check pairing and authenticated local health, `--smtp` to validate SMTP configuration and the default recipient, or `--smtp --to reader@kindle.com` to check another recipient. Only `--smtp-login` opens an SMTP connection and tests TLS/login; it never sends email or verifies Amazon sender approval. Tokens and passwords are redacted from diagnostics.

Use `--config FILE` before or after a command, or set `ARTICLE_TO_KINDLE_CONFIG`. Shell settings take precedence. Source checkouts default to the repository's `.env`; installed commands use `$XDG_CONFIG_HOME/article-to-kindle/.env` (normally `~/.config/article-to-kindle/.env`) or `%APPDATA%/article-to-kindle/.env` on Windows. `serve` remains manually started, loopback-only, and protected by the token and extension origin.

## Checks

```bash
.venv/bin/python article_to_kindle.py --self-test
.venv/bin/python -m unittest -v tests.test_api
.venv/bin/python -m unittest -v tests.test_extension
```

The extension fixture check needs Chrome or Chromium. Before using the MVP, manually smoke-test download and Kindle Submission once on Medium and once on Towards Data Science.

Supported article hosts currently include Medium, Towards Data Science, Substack, DEV, Hashnode, KDnuggets, Analytics Vidhya, Machine Learning Mastery, The Gradient, Papers with Code, Hugging Face, The Batch, Google Research, Microsoft Research, Meta AI, and OpenAI.

Extraction is generic: it scores semantic content candidates (`article`, `main`, `role=main`, `articleBody`, and common post-content classes) and reads metadata from JSON-LD, Open Graph, and the rendered DOM. Site-specific adapters are added only when a fixture demonstrates a real exception.
Imagens WebP são convertidas para JPEG durante a geração do EPUB para compatibilidade com Kindle; JPEG, PNG, GIF e SVG são preservadas.

Public pages and content already present in the rendered DOM only; the extension does not bypass paywalls or transfer browser cookies.
