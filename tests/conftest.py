"""Pytest fixtures and helpers for the test suite."""

from __future__ import annotations

import os
import sys

# Make sure `import grok_web_to_api` works when running `pytest` from the
# project root without installing the package.
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)
