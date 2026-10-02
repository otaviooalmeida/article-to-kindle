import io
import os
import stat
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest.mock import patch
from urllib.error import HTTPError

from backend.config import ALLOWED_ORIGIN, API_TOKEN, CONFIG_FILE, companion_settings, load_dotenv, read_dotenv
from backend.errors import ArticleError
from cli.diagnostics import check_health, diagnose
from cli.main import main
from cli.setup import save_config, setup

ORIGIN = "chrome-extension://" + "a" * 32
TOKEN = "private-token-" + "x" * 32


class ConfigurationTest(unittest.TestCase):
    def setUp(self):
        environment = patch.dict(os.environ, {}, clear=True)
        environment.start()
        self.addCleanup(environment.stop)

    def test_dotenv_quotes_and_shell_precedence(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / ".env"
            path.write_text('SMTP_PASSWORD="a\'b\"c"\nKINDLE_EMAIL=file@example.com\n')
            os.environ["KINDLE_EMAIL"] = "shell@example.com"
            load_dotenv(path)
            self.assertEqual('a\'b"c', os.environ["SMTP_PASSWORD"])
            self.assertEqual("shell@example.com", os.environ["KINDLE_EMAIL"])

    def test_setup_generates_private_config_without_echoing_secrets(self):
        with tempfile.TemporaryDirectory() as directory, patch("builtins.input", side_effect=[ORIGIN, "n"]):
            path = Path(directory) / ".env"
            stdout = io.StringIO()
            with redirect_stdout(stdout):
                setup(path)
            values = read_dotenv(path)
            self.assertGreaterEqual(len(values[API_TOKEN]), 32)
            self.assertEqual(ORIGIN, values[ALLOWED_ORIGIN])
            self.assertNotIn(values[API_TOKEN], stdout.getvalue())
            if os.name != "nt":
                self.assertEqual(0o600, stat.S_IMODE(path.stat().st_mode))

    def test_setup_requires_force_and_preserves_unknown_settings(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / ".env"
            original = f'# Preserve me\nCUSTOM=value\n{API_TOKEN}="{TOKEN}"\n{ALLOWED_ORIGIN}="{ORIGIN}"\n'
            path.write_text(original)
            with patch("builtins.input") as prompt, self.assertRaises(ArticleError):
                setup(path)
            prompt.assert_not_called()
            self.assertEqual(original, path.read_text())
            with patch("builtins.input", side_effect=["", "n"]), redirect_stdout(io.StringIO()):
                setup(path, force=True)
            self.assertIn("# Preserve me\nCUSTOM=value", path.read_text())
            self.assertEqual(TOKEN, read_dotenv(path)[API_TOKEN])

    def test_setup_cancellation_and_invalid_input_do_not_write(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / ".env"
            with patch("builtins.input", side_effect=EOFError), redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
                self.assertEqual(1, main(["setup", "--config", str(path)]))
            self.assertFalse(path.exists())
            with patch("builtins.input", return_value="https://attacker.example"), redirect_stdout(io.StringIO()):
                with self.assertRaises(ArticleError):
                    setup(path)
            self.assertFalse(path.exists())

    def test_no_clobber_and_symlink_protection(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / ".env"
            save_config(path, {"KEY": "value"}, force=False)
            with self.assertRaises(ArticleError):
                save_config(path, {"KEY": "changed"}, force=False)
            link = Path(directory) / "link"
            link.symlink_to(path)
            with self.assertRaises(ArticleError):
                save_config(link, {"KEY": "changed"}, force=True)
            self.assertEqual("value", read_dotenv(path)["KEY"])

    def test_doctor_defaults_offline_and_redacts_secrets(self):
        with patch("cli.diagnostics.check_health") as health, patch("cli.diagnostics.smtp_connection") as smtp:
            checks = diagnose()
        self.assertTrue(all(check["ok"] for check in checks))
        health.assert_not_called()
        smtp.assert_not_called()
        os.environ.update({API_TOKEN: TOKEN, ALLOWED_ORIGIN: ORIGIN})
        with patch("cli.diagnostics.check_health") as health:
            checks = diagnose(companion=True)
        health.assert_called_once_with(TOKEN, ORIGIN)
        self.assertNotIn(TOKEN, str(checks))

    def test_doctor_runs_when_conversion_dependency_is_missing(self):
        import importlib
        real_import = importlib.import_module
        def importing(name):
            if name == "bs4":
                raise ImportError("missing")
            return real_import(name)
        with patch("cli.diagnostics.importlib.import_module", side_effect=importing):
            checks = diagnose()
        self.assertFalse(next(check["ok"] for check in checks if check["name"] == "bs4"))

    def test_health_rejection_is_actionable_and_bounded(self):
        with patch("cli.diagnostics.build_opener") as opener:
            opener.return_value.open.side_effect = HTTPError("http://127.0.0.1:8765/health", 401, "secret", {}, None)
            with self.assertRaisesRegex(ArticleError, "Pairing token rejected"):
                check_health(TOKEN, ORIGIN)
            request = opener.return_value.open.call_args.args[0]
            self.assertEqual("Bearer " + TOKEN, request.get_header("Authorization"))

    def test_invalid_tokens_are_rejected_without_echoing_them(self):
        os.environ[ALLOWED_ORIGIN] = ORIGIN
        for token in ("short", "🙂" * 32, "x" * 32 + "\x00", "x" * 32 + "\n"):
            with self.subTest(token=repr(token)):
                with patch("backend.config.os.environ", {API_TOKEN: token, ALLOWED_ORIGIN: ORIGIN}):
                    with self.assertRaises(ArticleError) as raised:
                        companion_settings()
                self.assertNotIn(token, str(raised.exception))

    def test_missing_environment_selected_config_is_not_ignored(self):
        os.environ[CONFIG_FILE] = "/absent/config.env"
        with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()) as stderr:
            self.assertEqual(1, main(["doctor"]))
        self.assertIn("Configuration file does not exist", stderr.getvalue())

    def test_global_and_command_config_options(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / ".env"
            path.write_text("")
            for args in (["--config", str(path), "doctor"], ["doctor", "--config", str(path)]):
                with redirect_stdout(io.StringIO()):
                    self.assertEqual(0, main(args))
            self.assertEqual(str(path.resolve()), os.environ[CONFIG_FILE])


if __name__ == "__main__":
    unittest.main()
