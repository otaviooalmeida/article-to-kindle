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
.venv/bin/pip install -r requirements.txt
```

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
./article_to_kindle.py 'https://medium.com/@user/article-slug'
```

Without `--output`, the EPUB is saved under `outputs/`. Use `--output article.epub` for another path, or `--send` to submit it through SMTP.

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
