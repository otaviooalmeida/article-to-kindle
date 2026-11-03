import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path


class AiExtensionPreviewTest(unittest.TestCase):
    def test_ai_capture_snapshot_preserves_images_for_model_selection(self):
        self.assert_browser_fixture_passes("ai-capture.html")

    def test_ai_exclusions_are_unchecked_and_restorable_in_original_order(self):
        self.assert_browser_fixture_passes("ai-preview.html")

    def test_review_flow_restores_exclusions_and_opens_an_independent_comparison(self):
        self.assert_browser_fixture_passes("preview-workflow.html")

    def assert_browser_fixture_passes(self, fixture):
        chrome = shutil.which("google-chrome") or shutil.which("chromium")
        if not chrome:
            self.skipTest("Chrome is not installed")
        path = Path(__file__).parent / "fixtures" / fixture
        uri = path.resolve().as_uri() + ("?id=test-capture" if fixture == "preview-workflow.html" else "")
        with tempfile.TemporaryDirectory() as profile:
            result = subprocess.run(
                [chrome, "--headless", "--no-sandbox", "--disable-gpu", "--disable-dev-shm-usage",
                 "--virtual-time-budget=3000",
                 f"--user-data-dir={profile}", "--dump-dom", uri],
                capture_output=True, text=True, timeout=20, check=True,
            )
        self.assertIn("<title>PASS</title>", result.stdout, fixture)


if __name__ == "__main__":
    unittest.main()
