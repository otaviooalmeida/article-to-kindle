import json
import threading
import time
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from unittest.mock import patch

from bs4 import BeautifulSoup

from backend.api import app


class FakeOllamaHandler(BaseHTTPRequestHandler):
    requests = []
    invalid_response = False
    slow_response = False
    media_as_noise = False
    stream_started = threading.Event()
    release_stream = threading.Event()
    lock = threading.Lock()

    def log_message(self, _format, *_args):
        pass

    def respond(self, value):
        body = json.dumps(value).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        self.respond({"version": "0.9.6"})

    def do_POST(self):
        length = int(self.headers.get("Content-Length", "0"))
        request = json.loads(self.rfile.read(length))
        if self.path.endswith("/generate"):
            self.respond({"response": "", "done": True})
            return

        payload = json.loads(request["messages"][-1]["content"])
        blocks = payload["blocks"]
        with self.lock:
            self.requests.append(payload)
            invalid = self.invalid_response
        labels = {}
        for block in blocks:
            context = f"{block.get('context', '')} {block['text']}".casefold()
            label = "body"
            if FakeOllamaHandler.media_as_noise and block.get("tag") in {"figure", "img", "pre"}:
                label = "noise"
            elif "avatar" in context or "you may also want" in context or "site navigation" in context or "related stories" in context:
                label = "noise"
            elif "feature title" in context:
                label = "title"
            elif "feature subtitle" in context:
                label = "subtitle"
            elif "by ada lovelace" in context or "byline" in block.get("context", "").casefold():
                label = "author"
            labels[str(block["id"])] = label
        if invalid and labels:
            labels.pop(next(reversed(labels)))
        content = json.dumps({"labels": labels})
        response = json.dumps({
            "model": "qwen2.5:3b",
            "message": {"role": "assistant", "content": content},
            "done": True,
        }).encode() + b"\n"
        if self.slow_response:
            self.send_response(200)
            self.send_header("Content-Type", "application/x-ndjson")
            self.send_header("Content-Length", str(len(response)))
            self.end_headers()
            self.stream_started.set()
            self.release_stream.wait(5)
            try:
                self.wfile.write(response)
            except OSError:
                pass
            return
        self.send_response(200)
        self.send_header("Content-Type", "application/x-ndjson")
        self.send_header("Content-Length", str(len(response)))
        self.end_headers()
        self.wfile.write(response)


async def request(method, path, headers=None, body=b""):
    messages = []
    received = False

    async def receive():
        nonlocal received
        if not received:
            received = True
            return {"type": "http.request", "body": body, "more_body": False}
        return {"type": "http.disconnect"}

    async def send(message):
        messages.append(message)

    scope = {
        "type": "http", "asgi": {"version": "3.0"}, "http_version": "1.1",
        "method": method, "scheme": "http", "path": path, "raw_path": path.encode(),
        "query_string": b"", "root_path": "", "client": ("test", 1),
        "server": ("test", 80), "state": {},
        "headers": [(key.lower().encode(), value.encode()) for key, value in (headers or {}).items()],
    }
    await app(scope, receive, send)
    start = next(message for message in messages if message["type"] == "http.response.start")
    content = b"".join(message.get("body", b"") for message in messages if message["type"] == "http.response.body")
    return start["status"], content


class AiAnalysisApiTest(unittest.IsolatedAsyncioTestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), FakeOllamaHandler)
        cls.server_thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.server_thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.server_thread.join(timeout=2)

    def setUp(self):
        FakeOllamaHandler.requests = []
        FakeOllamaHandler.invalid_response = False
        FakeOllamaHandler.slow_response = False
        FakeOllamaHandler.media_as_noise = False
        FakeOllamaHandler.stream_started = threading.Event()
        FakeOllamaHandler.release_stream = threading.Event()
        self.environment = patch.dict("os.environ", {
            "ARTICLE_TO_KINDLE_TOKEN": "test-token",
            "ARTICLE_TO_KINDLE_ALLOWED_ORIGIN": "chrome-extension://test-extension",
            "ARTICLE_TO_KINDLE_AI_SSH_TARGET": "",
            "ARTICLE_TO_KINDLE_AI_OLLAMA_URL": f"http://127.0.0.1:{self.server.server_port}",
            "ARTICLE_TO_KINDLE_AI_MODEL": "qwen2.5:3b",
        })
        self.environment.start()
        self.addCleanup(self.environment.stop)

    async def create_job(self, html, mode="ai"):
        status, body = await request("POST", "/analysis-jobs", {
            "Authorization": "Bearer test-token",
            "Origin": "chrome-extension://test-extension",
            "Content-Type": "application/json",
        }, json.dumps({
            "sourceUrl": "https://publisher.example.org/article",
            "html": html,
            "mode": mode,
        }).encode())
        self.assertEqual(202, status, body)
        return json.loads(body)["jobId"]

    async def wait_for_job(self, job_id):
        for _ in range(500):
            status, body = await request("GET", f"/analysis-jobs/{job_id}", {
                "Authorization": "Bearer test-token",
                "Origin": "chrome-extension://test-extension",
            })
            self.assertEqual(200, status, body)
            result = json.loads(body)
            if result["status"] in {"completed", "failed", "cancelled"}:
                return result
            time.sleep(0.01)
        self.fail("Article analysis did not finish within five seconds")

    async def test_analysis_jobs_require_the_configured_bearer_token(self):
        status, body = await request("POST", "/analysis-jobs", {
            "Authorization": "Bearer wrong-token",
            "Origin": "chrome-extension://test-extension",
            "Content-Type": "application/json",
        }, json.dumps({
            "sourceUrl": "https://publisher.example.org/article",
            "html": "<article>Private page content</article>",
            "mode": "ai",
        }).encode())

        self.assertEqual(401, status)
        self.assertNotIn(b"Private page content", body)

    async def test_ai_analysis_keeps_article_content_and_makes_excluded_blocks_restorable(self):
        html = '''<html><head><meta property="og:title" content="Metadata title"></head><body>
        <nav><p>Site navigation with links to sections and account settings.</p></nav>
        <article><header><h1>Feature title</h1><p>Feature subtitle clarifies the article's scope.</p>
        <p class="byline">By Ada Lovelace · Email ada@example.com · @adalovelace</p><img class="avatar" src="/ada.jpg" alt="Ada portrait"></header>
        <p>The opening paragraph preserves the argument and all its original wording for readers.</p>
        <p>Article evidence quotes report@example.org and @fieldnotes as part of the original text.</p>
        <figure><img src="/chart.png" alt="Editorial chart"><figcaption>Chart caption preserves context.</figcaption></figure>
        <p>This paragraph retains a formula and code, including x squared and exact syntax.</p>
        <pre><code>answer = 42</code></pre>
        <p>The conclusion is the final genuine paragraph and must survive recommendation cleanup.</p>
        <section class="related"><h2>Related stories</h2><p>You may also want to read this unrelated promotion.</p></section>
        </article></body></html>'''

        job_id = await self.create_job(html)
        result = await self.wait_for_job(job_id)

        self.assertEqual("completed", result["status"])
        article = result["result"]
        self.assertEqual("Feature title", article["title"])
        self.assertEqual("ai", article["analysisMode"], article.get("fallbackReason"))
        self.assertEqual("Ada Lovelace", article["author"], article.get("fallbackReason"))
        self.assertNotIn("@", article["author"])
        self.assertNotIn("example.com", article["author"])
        self.assertEqual("ai", article["analysisMode"])
        self.assertIn("Feature subtitle", article["html"])
        self.assertIn("opening paragraph", article["html"])
        self.assertIn("report@example.org", article["html"])
        self.assertIn("@fieldnotes", article["html"])
        self.assertIn("Editorial chart", article["html"])
        self.assertIn("Chart caption", article["html"])
        self.assertIn("answer = 42", article["html"])
        self.assertIn("final genuine paragraph", article["html"])
        preview_blocks = BeautifulSoup(article["html"], "html.parser")
        recommendation = preview_blocks.find(string=lambda text: text and "You may also want" in text)
        self.assertEqual("true", recommendation.find_parent("div", attrs={"data-article-to-kindle-excluded": True}).get("data-article-to-kindle-excluded"))
        self.assertIn('data-article-to-kindle-excluded="true"', article["html"])
        self.assertIn("Ada portrait", article["html"])
        self.assertGreater(article["analysisTimeMs"], 0)

    async def test_cookie_dialog_and_post_article_cards_are_excluded_but_references_survive(self):
        html = '''<html><body>
        <main><article>
          <div class="privacy-center-floating" role="dialog" aria-modal="true" aria-label="Customize consent preferences">
            <h1>Customize Consent Preferences</h1>
            <p>Necessary storage controls are required for basic functionality and consent choices.</p>
            <p>Optional analytics measure visits, sessions, and site interaction.</p>
          </div>
          <h1>How calibration changes the forecast</h1>
          <p>The opening explains the measurement process and preserves the original argument for the reader.</p>
          <p>The conclusion summarizes the findings while noting limitations that remain important.</p>
          <p class="cookie-history">Cookie consent policies affect this research topic and belong in the article.</p>
          <section class="article-references"><h2>References</h2>
            <p>Reference one supports the article's claims and belongs after the conclusion.</p>
          </section>
        </article>
        <section class="editors-picks"><h2>More from the publication</h2>
          <a href="/another-story"><h3>Another story for you</h3><p>Read this separate feature about an unrelated topic.</p></a>
          <a href="/sponsored-story"><h3>Partner spotlight</h3><p>Explore this promoted product and learn more today.</p></a>
        </section></main></body></html>'''

        job_id = await self.create_job(html)
        result = await self.wait_for_job(job_id)

        self.assertEqual("completed", result["status"])
        article = result["result"]
        self.assertEqual("How calibration changes the forecast", article["title"])
        self.assertEqual("ai", article["analysisMode"], article.get("fallbackReason"))
        blocks = BeautifulSoup(article["html"], "html.parser").select("[data-article-to-kindle-excluded]")
        excluded = [block for block in blocks if block["data-article-to-kindle-excluded"] == "true"]
        included = [block for block in blocks if block["data-article-to-kindle-excluded"] == "false"]
        excluded_text = " ".join(block.get_text(" ", strip=True) for block in excluded)
        included_text = " ".join(block.get_text(" ", strip=True) for block in included)
        self.assertIn("Customize Consent Preferences", excluded_text)
        self.assertIn("Partner spotlight", excluded_text)
        self.assertIn("Reference one supports", included_text)
        self.assertIn("conclusion summarizes", included_text)
        self.assertIn("Cookie consent policies affect this research topic", included_text)
        title_entry = next(
            block for payload in FakeOllamaHandler.requests for block in payload["blocks"]
            if "How calibration changes the forecast" in block["text"]
        )
        self.assertNotIn("Customize Consent Preferences", title_entry["nearby"])
        self.assertNotIn("Another story for you", json.dumps(FakeOllamaHandler.requests))

    async def test_author_byline_does_not_absorb_publication_date_or_read_time(self):
        html = '''<article><h1>Feature title</h1>
        <p class="byline">Spyros Georgopoulos October 30, 2026 9 min read</p>
        <p>This complete article paragraph retains enough original wording to create a valid reading copy.</p>
        <p>This second complete article paragraph also preserves enough text to pass article validation.</p>
        </article>'''

        job_id = await self.create_job(html)
        result = await self.wait_for_job(job_id)

        self.assertEqual("completed", result["status"])
        self.assertEqual("Spyros Georgopoulos", result["result"]["author"])

    async def test_editorial_figures_and_code_stay_in_place_when_model_calls_them_noise(self):
        FakeOllamaHandler.media_as_noise = True
        html = '''<article><h1>Feature title</h1>
        <p>The article explains how random choices can mislead readers and preserves the key result.</p>
        <p>It's half right, which is the most dangerous way to be right.</p>
        <figure><img src="/first-chart.png" alt=""></figure>
        <figure><img src="/credited-chart.png" alt="Photo by the author"></figure>
        <h2>How I made this chart</h2>
        <p>This section describes assumptions before showing the code example.</p>
        <pre><code>distribution = [0.02, 0.30]</code></pre>
        <p>The conclusion summarizes why these assumptions affect the result.</p>
        <figure><img src="/author.png" alt="Author portrait"></figure></article>'''

        job_id = await self.create_job(html)
        result = await self.wait_for_job(job_id)

        self.assertEqual("completed", result["status"])
        article = result["result"]
        self.assertEqual("ai", article["analysisMode"], article.get("fallbackReason"))
        markers = BeautifulSoup(article["html"], "html.parser").select(
            "[data-article-to-kindle-excluded]"
        )
        figure = next(marker for marker in markers if marker.find("img", alt=""))
        credited_figure = next(marker for marker in markers if marker.find("img", alt="Photo by the author"))
        portrait = next(marker for marker in markers if marker.find("img", alt="Author portrait"))
        code = next(marker for marker in markers if marker.find("pre"))
        self.assertEqual("false", figure["data-article-to-kindle-excluded"])
        self.assertEqual("false", credited_figure["data-article-to-kindle-excluded"])
        self.assertEqual("true", portrait["data-article-to-kindle-excluded"])
        self.assertEqual("false", code["data-article-to-kindle-excluded"])
        model_tags = [
            block["tag"] for payload in FakeOllamaHandler.requests for block in payload["blocks"]
        ]
        self.assertIn("figure", model_tags)
        self.assertIn("pre", model_tags)
        included_html = "".join(
            str(marker) for marker in markers
            if marker["data-article-to-kindle-excluded"] == "false"
        )
        fragments = (
            "It's half right", "first-chart.png", "credited-chart.png",
            "How I made this chart", "distribution =",
        )
        positions = [included_html.index(fragment) for fragment in fragments]
        self.assertEqual(sorted(positions), positions)

    async def test_oversized_articles_are_labeled_in_overlapping_complete_chunks(self):
        paragraphs = "".join(
            f"<p>Section {index} preserves its complete original article wording for evaluation.</p>"
            for index in range(60)
        )
        html = f"<article><h1>Long article title</h1>{paragraphs}</article>"

        job_id = await self.create_job(html)
        result = await self.wait_for_job(job_id)

        self.assertEqual("completed", result["status"])
        self.assertEqual("ai", result["result"]["analysisMode"], result["result"].get("fallbackReason"))
        self.assertEqual(60, result["result"]["html"].count("preserves its complete original"))
        self.assertGreater(len(FakeOllamaHandler.requests), 1)
        windows = [
            {block["id"] for block in payload["blocks"]}
            for payload in FakeOllamaHandler.requests
        ]
        self.assertTrue(any(windows[index] & windows[index + 1] for index in range(len(windows) - 1)))

    async def test_article_aside_and_footer_are_excluded_without_losing_epilogue_or_references(self):
        html = '''<html><body><article><h1>How calibration changes the forecast</h1>
        <div class="article-copy">
          <p>The article explains the calibration method and retains the important experimental context.</p>
          <h2>Epilogue</h2><p>The epilogue concludes the author's argument without ending the references.</p>
          <section class="references"><h2>References</h2>
            <p>This reference supports the article's final claims and must remain after the conclusion.</p>
          </section>
        </div>
        <aside class="not-prose flex items-center"><p>Learn this step by step with the interactive Data Analyst roadmap.</p><a href="/course">View the promoted course</a></aside>
        <footer><p>Written By Ada Lovelace</p><p>Ada is a data scientist and writes about other topics on social media.</p>
          <p>Share This Article</p><p>Submit your insights to our global publication.</p>
        </footer>
        </article></body></html>'''

        job_id = await self.create_job(html)
        result = await self.wait_for_job(job_id)

        self.assertEqual("completed", result["status"])
        article = result["result"]
        blocks = BeautifulSoup(article["html"], "html.parser").select("[data-article-to-kindle-excluded]")
        excluded_text = " ".join(
            block.get_text(" ", strip=True) for block in blocks
            if block["data-article-to-kindle-excluded"] == "true"
        )
        included_text = " ".join(
            block.get_text(" ", strip=True) for block in blocks
            if block["data-article-to-kindle-excluded"] == "false"
        )
        for phrase in ("Data Analyst roadmap", "Written By Ada Lovelace", "Share This Article", "global publication"):
            self.assertIn(phrase, excluded_text)
        self.assertIn("epilogue concludes", included_text)
        self.assertIn("reference supports", included_text)

    async def test_related_card_widget_inside_article_is_excluded_after_references(self):
        html = '''<article><h1>Forecast calibration</h1>
        <p>This article introduction describes how calibration is performed and provides enough detail to be readable.</p>
        <p>Its conclusion describes the methods and their limitations while preserving all important information.</p>
        <section class="references"><h2>References</h2>
          <p>The first reference supports the article and is genuine end matter after the conclusion.</p>
        </section>
        <section class="editors-picks-widget"><h2>More from this publication</h2>
          <a href="/one"><h3>Another story</h3><p>A separate article card with sufficient text to look like a recommendation.</p></a>
          <a href="/two"><h3>Partner story</h3><p>A promoted partner story in a second card.</p></a>
        </section>
        <div class="bottom-promo"><p>Explore this product today in a post-article promotion.</p></div>
        </article>'''

        job_id = await self.create_job(html)
        result = await self.wait_for_job(job_id)

        self.assertEqual("completed", result["status"])
        article = result["result"]
        blocks = BeautifulSoup(article["html"], "html.parser").select("[data-article-to-kindle-excluded]")
        excluded_text = " ".join(
            block.get_text(" ", strip=True) for block in blocks
            if block["data-article-to-kindle-excluded"] == "true"
        )
        included_text = " ".join(
            block.get_text(" ", strip=True) for block in blocks
            if block["data-article-to-kindle-excluded"] == "false"
        )
        self.assertIn("Another story", excluded_text)
        self.assertIn("post-article promotion", excluded_text)
        self.assertIn("first reference supports", included_text)
        self.assertIn("Its conclusion describes", included_text)

    async def test_embedded_media_is_reduced_to_static_fallbacks_with_warnings(self):
        html = '''<article><h1>Static media article</h1>
        <p>This article explains static media fallbacks and preserves enough complete prose to pass content validation.</p>
        <video poster="/method-poster.jpg" aria-label="Calibration demonstration"></video>
        <canvas aria-label="Interactive chart"></canvas></article>'''

        job_id = await self.create_job(html)
        result = await self.wait_for_job(job_id)

        self.assertEqual("completed", result["status"])
        article = result["result"]
        self.assertIn('src="https://publisher.example.org/method-poster.jpg"', article["html"])
        self.assertIn("Video poster", article["html"])
        self.assertNotIn("<video", article["html"])
        self.assertIn("Interactive canvas omitted", article["html"])
        self.assertGreaterEqual(len(article["warnings"]), 2)

    async def test_reader_can_cancel_a_slow_ai_job(self):
        FakeOllamaHandler.slow_response = True
        html = "<article><h1>Cancel article</h1>" + "".join(
            f"<p>This article paragraph {index} is preserved while the slow model is running.</p>"
            for index in range(5)
        ) + "</article>"
        job_id = await self.create_job(html)
        self.assertTrue(FakeOllamaHandler.stream_started.wait(timeout=2))

        status, body = await request("DELETE", f"/analysis-jobs/{job_id}", {
            "Authorization": "Bearer test-token",
            "Origin": "chrome-extension://test-extension",
        })
        FakeOllamaHandler.release_stream.set()

        self.assertEqual(200, status)
        self.assertEqual("cancelled", json.loads(body)["status"])

    async def test_invalid_ai_labels_fall_back_to_standard_extraction_with_a_reason(self):
        FakeOllamaHandler.invalid_response = True
        html = "<article><h1>Fallback article</h1>" + "".join(
            f"<p>This complete article paragraph {index} contains enough words to remain readable in the capture.</p>"
            for index in range(5)
        ) + "</article>"

        job_id = await self.create_job(html)
        result = await self.wait_for_job(job_id)

        self.assertEqual("completed", result["status"])
        self.assertEqual("standard", result["result"]["analysisMode"])
        self.assertTrue(result["result"]["fallbackReason"])
        self.assertIn("Fallback article", result["result"]["title"])
        self.assertTrue(any("AI analysis unavailable" in warning for warning in result["result"]["warnings"]))


if __name__ == "__main__":
    unittest.main()
