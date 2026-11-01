"""Shared helpers for PRPilot tests.

These tests use only the standard library, pytest, and
unittest.mock. They make no network calls.

Import strategy: the repo layout puts code in api/, agents/,
github/, and db/ without a package __init__ in every folder, and
Vercel imports those modules by file path. The helpers here
therefore look for a source file in several places, in order:

1. The draft directory (the parent of tests/, when the drafts
   are checked out as a repo root).
2. The current working directory.
3. The directory named by the PRPILOT_REPO_ROOT environment
   variable, if set (used when running the drafts standalone).

If a real source file cannot be found, the test that needs it is
skipped with a clear reason instead of failing or testing a
made-up copy silently. Tests that define their own small spec
functions say so in their docstring.
"""

import importlib.util
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.getcwd())


def draft_root():
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def find_repo_file(relative_path):
    """Return the first existing path for a repo-relative file, or None."""
    candidates = [
        os.path.join(draft_root(), relative_path),
        os.path.join(os.getcwd(), relative_path),
    ]
    repo_root = os.environ.get("PRPILOT_REPO_ROOT")
    if repo_root:
        candidates.append(os.path.join(repo_root, relative_path))
    for candidate in candidates:
        if os.path.isfile(candidate):
            return candidate
    return None


def load_module_from_path(module_name, path):
    """Load a single .py file as a module, without a package."""
    spec = importlib.util.spec_from_file_location(module_name, path)
    if spec is None or spec.loader is None:
        raise ImportError("Cannot load module from " + path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module
