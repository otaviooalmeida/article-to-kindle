import io
import os
import tempfile
import tomllib
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

from backend.config import default_config_path
from cli import __version__
from cli.main import main


class PackagingTest(unittest.TestCase):
    def test_package_contains_only_application_modules(self):
        root = Path(__file__).resolve().parent.parent
        project = tomllib.loads((root / "pyproject.toml").read_text())
        self.assertEqual(["backend", "cli"], project["tool"]["setuptools"]["packages"])
        self.assertEqual("cli.main:main", project["project"]["scripts"]["article-to-kindle"])
        self.assertEqual(set((root / "requirements.txt").read_text().splitlines()), set(project["project"]["dependencies"]))

    def test_version_does_not_load_configuration(self):
        with patch("cli.main.load_dotenv") as load, redirect_stdout(io.StringIO()) as stdout:
            with self.assertRaises(SystemExit) as raised:
                main(["--version"])
        self.assertEqual(0, raised.exception.code)
        self.assertIn(__version__, stdout.getvalue())
        load.assert_not_called()

    def test_installed_config_path_uses_user_directory(self):
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, {"XDG_CONFIG_HOME": directory}, clear=True), \
                patch("backend.config.__file__", str(Path(directory) / "site-packages/backend/config.py")), \
                patch("backend.config.sys.platform", "linux"):
            self.assertEqual(Path(directory) / "article-to-kindle/.env", default_config_path())
        with patch.dict(os.environ, {"APPDATA": "C:/Users/reader/AppData/Roaming"}, clear=True), \
                patch("backend.config.__file__", "/absent/site-packages/backend/config.py"), \
                patch("backend.config.sys.platform", "win32"):
            self.assertEqual(Path("C:/Users/reader/AppData/Roaming/article-to-kindle/.env"), default_config_path())


if __name__ == "__main__":
    unittest.main()
