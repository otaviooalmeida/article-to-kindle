# Article to Kindle

Capture a rendered Medium or Towards Data Science article, preserve its text, formulas, and editorial images, and turn it into a Kindle-ready EPUB.

## Install

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
```

## Chrome extension and local server

1. Open `chrome://extensions`, enable Developer mode, choose **Load unpacked**, and select the `extension/` directory.
2. Open the extension settings and copy the displayed `chrome-extension://...` origin.
3. Export the settings below. Use `.env.example` as a template; the application does not load `.env` files automatically.

```bash
export ARTICLE_TO_KINDLE_TOKEN="$(python3 -c 'import secrets; print(secrets.token_urlsafe(32))')"
export ARTICLE_TO_KINDLE_ALLOWED_ORIGIN='chrome-extension://your-extension-id'
export KINDLE_EMAIL='your-kindle-address@example.com'
export SMTP_HOST='smtp.example.com'
export SMTP_PORT='587'
export SMTP_USERNAME='your-email@example.com'
export SMTP_PASSWORD='app-password'
export SMTP_FROM='your-email@example.com'
```

4. Put the same token in the extension settings and save.
5. Start the local server and leave it running:

```bash
.venv/bin/python article_to_kindle.py --serve
```

6. Visit a supported article and open the extension. Choose **Download EPUB** or **Send to Kindle**.

The server listens only on `127.0.0.1:8765`. SMTP acceptance is a Kindle Submission, not proof that Amazon has added the document to the Kindle library. Email EPUBs are limited to 50 MiB.

## CLI

```bash
.venv/bin/python article_to_kindle.py 'https://medium.com/@user/article-slug'
```

Without `--output`, the EPUB is saved under `outputs/`. Use `--output article.epub` for another path, or `--send` to submit it through SMTP.

## Checks

```bash
.venv/bin/python article_to_kindle.py --self-test
.venv/bin/python -m unittest -v tests.test_api
.venv/bin/python -m unittest -v tests.test_extension
```

The extension fixture check needs Chrome or Chromium. Before using the MVP, manually smoke-test download and Kindle Submission once on Medium and once on Towards Data Science.

Public pages and content already present in the rendered DOM only; the extension does not bypass paywalls or transfer browser cookies.
