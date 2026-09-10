#!/usr/bin/env python3
"""CLI launcher. The browser extension lives in web_extension/."""

import os
import sys
from pathlib import Path


def use_project_venv() -> None:
    project_python = Path(__file__).with_name(".venv") / "bin" / "python"
    if project_python.exists() and Path(sys.executable).absolute() != project_python.absolute():
        os.execv(str(project_python), [str(project_python), __file__, *sys.argv[1:]])


use_project_venv()

from cli.main import main
from backend.errors import ArticleError


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except ArticleError as error:
        print(f"error: {error}", file=sys.stderr)
        raise SystemExit(1)
