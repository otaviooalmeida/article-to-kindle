# Article to Kindle

Turn a public Medium or Towards Data Science article into a Kindle-ready EPUB.

```bash
cd /home/otavio/article-to-kindle
./article_to_kindle.py 'https://medium.com/@user/article-slug' --output article.epub
```

`beautifulsoup4` is the only non-standard dependency:

```bash
python3 -m pip install beautifulsoup4
```

Run the local check without making a network request:

```bash
./article_to_kindle.py --self-test
```

To email the generated EPUB to Kindle, configure an approved sender and run with `--send`:

Use [.env.example](.env.example) as a template. The application reads these values from the process environment; it does not load `.env` files automatically.

```bash
export KINDLE_EMAIL='your-kindle-address@example.com'
export SMTP_HOST='smtp.example.com'
export SMTP_PORT='587'
export SMTP_USERNAME='your-email@example.com'
export SMTP_PASSWORD='app-password'
export SMTP_FROM='your-email@example.com'

./article_to_kindle.py 'https://towardsdatascience.com/article-slug' --send
```

The command writes the EPUB locally before attempting delivery. `--dry-run` explicitly creates the EPUB without email. Public pages only; it does not bypass paywalls or run a browser.
