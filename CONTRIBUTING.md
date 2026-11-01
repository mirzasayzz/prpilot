# Contributing to PRPilot

## Setup

1. Use Python 3.11 or 3.12.
2. Create a virtual environment and activate it.
3. Install dependencies:

   ```sh
   pip install -r requirements.txt -r requirements-dev.txt
   ```

4. Copy .env.example to .env and fill in placeholder values only
   for local testing. Never commit a real .env file, a real
   secret, a real token, or a real private key.
5. Run the checks before opening a pull request:

   ```sh
   python -m py_compile api/*.py agents/*.py github/*.py db/*.py tests/*.py
   python -m pytest -q
   ```

## Branch and pull request rules

* Never commit directly to main. Every change goes through a
  pull request.
* Work on a branch named for the change, for example
  `feature/health-check` or `fix/quota-boundary`.
* Keep a pull request focused on one change. If a change touches
  another track's files (for example api/config.py, api/webhook.py,
  api/install.py, api/dashboard.py, api/process.py, or the public
  pages), say so in the pull request description so the owner of
  those files can review it.
* A pull request that changes behaviour should add or update a
  test. A pull request that changes a documented behaviour should
  update the docs in the same pull request.
* Do not add a new dependency without saying why it is needed and
  pinning it in requirements.txt or requirements-dev.txt.

## Code style

* Write plain, readable Python. Keep functions small and avoid
  clever shortcuts that hide a failure.
* Use structured logging from api/logging_util.py in API code.
  Do not log secret values or full exception text.
* Do not use em dashes in code, docs, or messages in this project.
* Do not add a billing claim, a compliance claim, or a metric
  without evidence in the pull request.

## Reporting a security issue

See SECURITY.md. Do not open a public issue with exploit details.
