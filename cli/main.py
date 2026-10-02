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
from cli import __version__
from cli.output import Reporter, UsageError


class CliParser(argparse.ArgumentParser):
    def error(self, message):
        raise UsageError(message, self.format_usage())


def fetch_html(url):
    from backend.extractor import fetch_html as fetch
    return fetch(url)


def extract_article(html, url):
    from backend.extractor import extract_article as extract
    return extract(html, url)


def available_output(article, requested: Path | None, output_dir: Path | None = None) -> Path:
    if requested:
        if requested.exists():
            raise ArticleError(f"Output already exists: {requested}")
        if not requested.parent.is_dir():
            raise ArticleError(f"Output directory does not exist: {requested.parent}")
        return requested
    from backend.extractor import slugify
    stem = f"{slugify(article.title)}-{hashlib.sha256(article.source_url.encode()).hexdigest()[:8]}"
    output_dir = output_dir or Path.cwd() / "outputs"
    output_dir.mkdir(parents=True, exist_ok=True)
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


def build_parser() -> argparse.ArgumentParser:
    parser = CliParser(description=__doc__, epilog="Legacy URL, --serve, and --self-test invocations remain supported.")
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    parser.add_argument("--debug", action="store_true", help="Show tracebacks for failures")
    parser.add_argument("--config", type=Path, help="Use this .env file (shell variables take precedence)")
    parser.add_argument("--json", action="store_true", help="Write one structured result to stdout (not setup/serve)")
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
    batch = commands.add_parser("batch", help="Convert a URL list sequentially, continuing after individual failures")
    batch.add_argument("input", help="UTF-8 URL list file, or - for stdin; one URL per line")
    batch.add_argument("--output-dir", type=Path, default=Path("outputs"), help="Directory for generated EPUBs (default: outputs)")
    batch.add_argument("--no-images", action="store_true", help="Omit images without downloading them")
    batch.add_argument("--no-links", action="store_true", help="Keep link text without clickable URLs")
    batch_delivery = batch.add_mutually_exclusive_group()
    batch_delivery.add_argument("--send", action="store_true", help="Explicitly submit each generated EPUB")
    batch_delivery.add_argument("--dry-run", action="store_true", help="Create EPUBs without email; identical to the default")
    batch.add_argument("--to", help="Override KINDLE_EMAIL (requires --send)")
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
        command.add_argument("--json", action="store_true", default=argparse.SUPPRESS, help="Write one structured result to stdout")
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
        if argv[index] in {"--debug", "--json"}:
            index += 1
        elif argv[index] == "--config":
            index += 2
        elif argv[index].startswith("--config="):
            index += 1
        else:
            break
    first = argv[index] if index < len(argv) else None
    if first is None or first in {"-h", "--help", "--version", "convert", "batch", "send", "serve", "self-test", "doctor", "setup"}:
        return argv
    return ["convert", *argv]


def submit(article, output: Path, recipient: str, reporter: Reporter) -> None:
    reporter.result.update(output=str(output), recipient=recipient, submission="unconfirmed")
    reporter.progress("Submitting to Kindle…")
    try:
        send_to_kindle(article, output, recipient)
    except (ArticleError, OSError, ValueError) as error:
        import shlex
        retry = shlex.join(["article-to-kindle", "send", str(output), "--to", recipient])
        raise ArticleError(
            f"Kindle submission failed. EPUB retained at {output}. {error}\n"
            f"Do not retry blindly: SMTP acceptance may be uncertain. Once safe, retry with:\n{retry}"
        ) from error
    reporter.result["submission"] = "smtp_accepted"
    reporter.notice(f"SMTP accepted for {recipient}; Amazon delivery pending.")


def run(argv: list[str], reporter: Reporter) -> int:
    parser = build_parser()
    args = parser.parse_args(normalize_argv(argv, parser))
    reporter.json_mode = args.json
    reporter.result["command"] = args.command
    if args.json and args.command in {"setup", "serve"}:
        parser.error("--json is not supported for interactive setup or the long-running serve command")
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
        reporter.result.update(configuration=str(path), checks=checks)
        reporter.notice(f"Configuration: {path}")
        for check in checks:
            reporter.notice(f"{'OK' if check['ok'] else 'FAIL'} {check['name']}: {check['message']}")
        ok = all(check["ok"] for check in checks)
        reporter.result["status"] = "ok" if ok else "error"
        return 0 if ok else 1
    if args.command == "self-test":
        self_test()
        reporter.notice("self-test passed")
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
        reporter.result.update(title=article.title, author=article.author, sourceUrl=article.source_url)
        submit(article, args.epub, recipient, reporter)
        return 0
    if args.command == "batch":
        if args.to is not None and not args.send:
            parser.error("--to requires --send")
        recipient = submission_settings(args.to)[2] if args.send else None
        return convert_batch(args, reporter, recipient)
    if sum(bool(value) for value in (args.url, args.html, args.capture)) != 1:
        parser.error("convert requires exactly one URL, --html FILE, or --capture FILE")
    if args.html and not args.source_url:
        parser.error("--html requires --source-url")
    if args.source_url and not args.html:
        parser.error("--source-url is only valid with --html")
    if args.to is not None and not args.send:
        parser.error("--to requires --send")
    if args.title is not None and (not args.title.strip() or any(char in args.title for char in "\r\n")):
        parser.error("--title must be a non-empty single-line title")
    recipient = submission_settings(args.to)[2] if args.send else None
    convert_one(args, reporter, recipient)
    return 0


def convert_one(args, reporter: Reporter, recipient: str | None = None, output_dir: Path | None = None) -> None:
    title, author = args.title, args.author
    if args.html or args.capture:
        from cli.sources import read_capture, read_input
        reporter.progress("Loading saved article…")
        if args.capture:
            capture = read_capture(args.capture)
            page_html, final_url = capture["html"], capture["sourceUrl"]
            title = capture["title"] if title is None else title
            author = capture["author"] if author is None else author
        else:
            page_html, final_url = read_input(args.html), args.source_url
    else:
        reporter.progress("Fetching article…")
        page_html, final_url = fetch_html(args.url)
    reporter.progress("Extracting article…")
    from backend.reading_copy import prepare_html
    page_html = prepare_html(page_html, final_url, title=title, author=author,
                             include_images=not args.no_images, include_links=not args.no_links)
    article = extract_article(page_html, final_url)
    output = available_output(article, args.output, output_dir)
    reporter.progress("Creating EPUB…")
    write_epub(article, output, include_source_link=not args.no_links)
    reporter.article(article, output)
    if args.send:
        submit(article, output, recipient, reporter)
    elif args.dry_run:
        reporter.notice("Dry run: EPUB created; email not sent (same as the default).")


def convert_batch(args, reporter: Reporter, recipient: str | None) -> int:
    from cli.batch import read_urls
    urls = read_urls(args.input)
    output_dir = args.output_dir.expanduser()
    output_dir.mkdir(parents=True, exist_ok=True)
    results = []
    reporter.result.update(results=results, total=len(urls), succeeded=0, failed=0)
    for index, url in enumerate(urls, start=1):
        reporter.progress(f"Article {index}/{len(urls)}: {url}")
        item = Reporter(json_mode=reporter.json_mode)
        item.result.update(command="convert", input=url)
        results.append(item.result)
        options = argparse.Namespace(url=url, html=None, capture=None, title=None, author=None,
                                     no_images=args.no_images, no_links=args.no_links,
                                     output=None, send=args.send, dry_run=args.dry_run)
        try:
            convert_one(options, item, recipient, output_dir)
            item.result["exitCode"] = 0
            reporter.result["succeeded"] += 1
        except (ArticleError, OSError, ValueError, ImportError) as error:
            item.error(error)
            item.result["exitCode"] = 1
            reporter.result["failed"] += 1
            if args.debug:
                import traceback
                traceback.print_exc()
        except KeyboardInterrupt:
            item.error(ArticleError("Interrupted."), code="interrupted")
            item.result["exitCode"] = 130
            reporter.result["failed"] += 1
            raise
    succeeded, failed = reporter.result["succeeded"], reporter.result["failed"]
    reporter.notice(f"Batch complete: {succeeded} succeeded, {failed} failed.")
    reporter.result["status"] = "partial" if succeeded and failed else "error" if failed else "ok"
    return 3 if succeeded and failed else 1 if failed else 0


def main(argv: list[str] | None = None) -> int:
    """Run the CLI with concise expected errors, or tracebacks with --debug."""
    argv = list(sys.argv[1:] if argv is None else argv)
    reporter = Reporter(json_mode="--json" in argv)
    try:
        code = run(argv, reporter)
    except UsageError as error:
        reporter.error(error, code="invalid_arguments")
        code = 2
    except (ArticleError, OSError, ValueError, ImportError) as error:
        reporter.error(error)
        if "--debug" in argv:
            import traceback
            traceback.print_exc()
        code = 1
    except EOFError:
        reporter.error(ArticleError("Setup cancelled: interactive input ended. No configuration was saved."), code="input_ended")
        code = 1
    except KeyboardInterrupt:
        reporter.error(ArticleError("Interrupted."), code="interrupted")
        code = 130
    reporter.emit(code)
    return code


if __name__ == "__main__":
    raise SystemExit(main())
