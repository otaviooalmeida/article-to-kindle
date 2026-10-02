"""Allow python -m cli without the repository launcher."""

from .main import main

raise SystemExit(main())
