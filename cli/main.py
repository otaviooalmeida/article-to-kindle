"""Create Kindle Reading Copies and manage the local companion."""

from __future__ import annotations

import argparse
import hashlib
import os
import sys
import tempfile
import zipfile
from pathlib import Path

from backend.config import CONFIG_FILE, companion_settings, default_config_path, load_dotenv
from backend.delivery import send_to_kindle, submission_settings
from backend.epub import read_epub_metadata, write_epub
from backend.errors import ArticleError


def fetch_html(url):
    from backend.extractor import fetch_html as fetch
    return fetch(url)


def extract_article(html, url):
    from backend.extractor import extract_article as extract
    return extract(html, url)


def available_output(article, requested: Path | None) -> Path:
    if requested:
        if requested.exists():
            raise ArticleError(f"Output already exists: {requested}")
        if not requested.parent.is_dir():
            raise ArticleError(f"Output directory does not exist: {requested.parent}")
        return requested
    from backend.extractor import slugify
    stem = f"{slugify(article.title)}-{hashlib.sha256(article.source_url.encode()).hexdigest()[:8]}"
    output_dir = Path.cwd() / "outputs"
    output_dir.mkdir(exist_ok=True)
    candidate = output_dir / f"{stem}.epub"
    index = 2
    while candidate.exists():
        candidate = output_dir / f"{stem}-{index}.epub"
        index += 1
    return candidate


def self_test() -> None:
    sample = r'''<html><head><meta property="og:title" content="Hello Kindle"/><meta name="author" content="Ada"/></head><body><article><h1>Hello Kindle</h1><p>This is enough sample text to make the article extractor accept it as a readable article body for the EPUB self-test.</p><p>Formula: \(x^2 + \frac{1}{2}\).</p><p>Fallback: \(\begin{matrix}\).</p><span class="katex"><annotation encoding="application/x-tex">y=\sqrt{x}</annotation></span><figure><img src="data:image/png;base64,invalid"/></figure><h2>Second section</h2><pre><code>print('hello')</code></pre><nav>Ignore this</nav></article></body></html>'''
    article = extract_article(sample, "https://medium.com/example/hello")
    assert "<math" in article.content_html and "<mfrac>" in article.content_html
    assert r"\frac" not in article.content_html and r"\begin{matrix}" in article.content_html
    assert article.warnings == ["1 formula(s) retained as text", "1 image(s) omitted"]
    with tempfile.TemporaryDirectory() as directory:
        epub = Path(directory) / "hello.epub"
        write_epub(article, epub)
        with zipfile.ZipFile(epub) as book:
            assert book.read("mimetype") == b"application/epub+zip"
            assert "OEBPS/article.xhtml" in book.namelist()
    print("self-test passed")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__, epilog="Legacy URL, --serve, and --self-test invocations remain supported.")
    parser.add_argument("--debug", action="store_true", help="Show tracebacks for failures")
    parser.add_argument("--config", type=Path, help="Use this .env file (shell variables take precedence)")
    commands = parser.add_subparsers(dest="command", required=True)
    convert = commands.add_parser("convert", help="Create an EPUB from a public supported article URL")
    convert.add_argument("url", nargs="?", help="Public article URL on a supported host (see README)")
    saved = convert.add_mutually_exclusive_group()
    saved.add_argument("--html", metavar="FILE", help="Saved UTF-8 HTML file, or - for stdin (requires --source-url)")
    saved.add_argument("--capture", metavar="FILE", help="Article Capture JSON file, or - for stdin")
    convert.add_argument("--source-url", help="Original supported article URL for saved HTML and relative assets")
    convert.add_argument("--title", help="Override the Reading Copy title")
    convert.add_argument("--author", help="Override the author")
    convert.add_argument("--no-images", action="store_true", help="Omit images without downloading them")
    convert.add_argument("--no-links", action="store_true", help="Keep article and source-link text without clickable URLs")
    convert.add_argument("-o", "--output", type=Path, help="Where to write the EPUB (never overwrites)")
    delivery = convert.add_mutually_exclusive_group()
    delivery.add_argument("--send", action="store_true", help="Submit the EPUB through SMTP")
    delivery.add_argument("--dry-run", action="store_true", help="Create an EPUB without email; identical to the default")
    convert.add_argument("--to", help="Override KINDLE_EMAIL (requires --send)")
    send = commands.add_parser("send", help="Submit an existing EPUB without fetching its article again")
    send.add_argument("epub", type=Path, help="Existing EPUB file")
    send.add_argument("--to", help="Override KINDLE_EMAIL")
    commands.add_parser("serve", help="Run the authenticated local API on 127.0.0.1:8765")
    commands.add_parser("self-test", help="Run the built-in EPUB check")
    doctor = commands.add_parser("doctor", help="Check dependencies and configuration without sending email")
    doctor.add_argument("--companion", action="store_true", help="Check pairing and authenticated loopback health")
    doctor.add_argument("--smtp", action="store_true", help="Check SMTP configuration and recipient (offline)")
    doctor.add_argument("--smtp-login", action="store_true", help="Explicitly connect with TLS and test SMTP login; never send email")
    doctor.add_argument("--to", help="Recipient for SMTP configuration checks")
    setup = commands.add_parser("setup", help="Interactively create secure companion and optional SMTP configuration")
    setup.add_argument("--force", action="store_true", help="Explicitly permit replacing an existing config file")
    for command in commands.choices.values():
        command.add_argument("--debug", action="store_true", default=argparse.SUPPRESS, help="Show tracebacks for failures")
        command.add_argument("--config", type=Path, default=argparse.SUPPRESS, help="Use this .env file")
    return parser


def normalize_argv(argv: list[str], parser: argparse.ArgumentParser) -> list[str]:
    legacy = [flag for flag in ("--serve", "--self-test") if flag in argv]
    if len(legacy) > 1:
        parser.error("--serve and --self-test cannot be combined")
    if legacy:
        command = legacy[0][2:]
        return [command, *[value for value in argv if value != legacy[0]]]
    index = 0
    while index < len(argv):
        if argv[index] == "--debug":
            index += 1
        elif argv[index] == "--config":
            index += 2
        elif argv[index].startswith("--config="):
            index += 1
        else:
            break
    first = argv[index] if index < len(argv) else None
    if first is None or first in {"-h", "--help", "convert", "send", "serve", "self-test", "doctor", "setup"}:
        return argv
    return ["convert", *argv]


def submit(article, output: Path, recipient: str) -> None:
    print("Submitting to Kindle…", file=sys.stderr)
    try:
        send_to_kindle(article, output, recipient)
    except (ArticleError, OSError, ValueError) as error:
        import shlex
        retry = shlex.join(["article-to-kindle", "send", str(output), "--to", recipient])
        raise ArticleError(
            f"Kindle submission failed. EPUB retained at {output}. {error}\n"
            f"Do not retry blindly: SMTP acceptance may be uncertain. Once safe, retry with:\n{retry}"
        ) from error
    print(f"SMTP accepted for {recipient}; Amazon delivery pending.")


def run(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(normalize_argv(list(sys.argv[1:] if argv is None else argv), parser))
    path = (args.config or default_config_path()).expanduser()
    if args.command == "setup":
        from cli.setup import setup
        setup(path, force=args.force)
        return 0
    if args.config is not None and not path.is_file():
        raise ArticleError(f"Configuration file does not exist: {path}")
    if args.config is not None:
        os.environ[CONFIG_FILE] = str(path.resolve())
    load_dotenv(path)
    if args.command == "doctor":
        if args.to and not (args.smtp or args.smtp_login):
            parser.error("doctor --to requires --smtp or --smtp-login")
        from cli.diagnostics import diagnose
        checks = diagnose(companion=args.companion, smtp=args.smtp or args.smtp_login,
                          smtp_login=args.smtp_login, recipient=args.to)
        print(f"Configuration: {path}")
        for check in checks:
            print(f"{'OK' if check['ok'] else 'FAIL'} {check['name']}: {check['message']}")
        return 0 if all(check["ok"] for check in checks) else 1
    if args.command == "self-test":
        self_test()
        return 0
    if args.command == "serve":
        companion_settings()
        print("Local companion listening on http://127.0.0.1:8765 (Ctrl+C to stop).", file=sys.stderr)
        import uvicorn
        uvicorn.run("backend.api:app", host="127.0.0.1", port=8765, log_level="warning")
        return 0
    if args.command == "send":
        recipient = submission_settings(args.to)[2]
        article = read_epub_metadata(args.epub)
        submit(article, args.epub, recipient)
        return 0
    if sum(bool(value) for value in (args.url, args.html, args.capture)) != 1:
        parser.error("convert requires exactly one URL, --html FILE, or --capture FILE")
    if args.html and not args.source_url:
        parser.error("--html requires --source-url")
    if args.source_url and not args.html:
        parser.error("--source-url is only valid with --html")
    if args.to is not None and not args.send:
        parser.error("--to requires --send")
    recipient = submission_settings(args.to)[2] if args.send else None
    title, author = args.title, args.author
    if args.html or args.capture:
        from cli.sources import read_capture, read_input
        print("Loading saved article…", file=sys.stderr)
        if args.capture:
            capture = read_capture(args.capture)
            page_html, final_url = capture["html"], capture["sourceUrl"]
            title = capture["title"] if title is None else title
            author = capture["author"] if author is None else author
        else:
            page_html, final_url = read_input(args.html), args.source_url
    else:
        print("Fetching article…", file=sys.stderr)
        page_html, final_url = fetch_html(args.url)
    print("Extracting article…", file=sys.stderr)
    from backend.reading_copy import prepare_html
    page_html = prepare_html(page_html, final_url, title=title, author=author,
                             include_images=not args.no_images, include_links=not args.no_links)
    article = extract_article(page_html, final_url)
    output = available_output(article, args.output)
    print("Creating EPUB…", file=sys.stderr)
    write_epub(article, output, include_source_link=not args.no_links)
    print(f"Title: {article.title}\nAuthor: {article.author}\nImages: {len(article.images)}\nCreated: {output}")
    for warning in article.warnings:
        print(f"warning: {warning}", file=sys.stderr)
    if args.send:
        submit(article, output, recipient)
    elif args.dry_run:
        print("Dry run: EPUB created; email not sent (same as the default).")
    return 0


def main(argv: list[str] | None = None) -> int:
    """Run the CLI with concise expected errors, or tracebacks with --debug."""
    argv = list(sys.argv[1:] if argv is None else argv)
    try:
        return run(argv)
    except (ArticleError, OSError, ValueError) as error:
        if "--debug" in argv:
            import traceback
            traceback.print_exc()
        else:
            print(f"error: {error}", file=sys.stderr)
        return 1
    except EOFError:
        print("Setup cancelled: interactive input ended. No configuration was saved.", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("Interrupted.", file=sys.stderr)
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
