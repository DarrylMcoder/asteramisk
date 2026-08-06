# Repository Guidelines

## Project Structure & Module Organization

`asteramisk/` contains the installable Python package. Public orchestration lives in `server.py`, `communicator.py`, and `notifier.py`; communication abstractions are under `asteramisk/ui/`; Asterisk protocol, audio, caching, and async internals are under `asteramisk/internal/`. Use `example_configs/` for sample Asterisk configuration, `docs/` for Sphinx sources, and `dist/` only for generated release artifacts. `test.py` is an ignored, local integration/smoke script rather than a unit-test suite.

## Build, Test, and Development Commands

- `python -m pip install -r requirements.txt` installs the pinned development dependencies.
- `python -m pip install -e .` installs the package editable for local development.
- `make -C docs html` builds the Sphinx documentation into `docs/_build/html/` (requires Sphinx and its extensions).
- `python test.py` runs the local Asterisk/OpenAI integration smoke test; configure credentials and a reachable Asterisk instance first. Do not copy its secrets into commits.
- `python -m compileall -q asteramisk` performs a lightweight syntax check.

There is no configured automated test runner at present. Add focused tests when changing behavior, and manually exercise AMI/ARI, audio, or provider integrations when applicable.

## Coding Style & Naming Conventions

Use Python 4-space indentation, descriptive `snake_case` functions and variables, `PascalCase` classes, and `UPPER_SNAKE_CASE` constants. Preserve the existing async-first design and type annotations where practical. Keep public APIs documented in `docs/`; avoid unrelated reformatting. No repository-wide formatter or linter configuration is committed, so keep changes PEP 8-compatible and run the compile check before submitting.

## Testing Guidelines

Place future unit tests near the package or in a dedicated `tests/` directory, using `test_*.py` filenames and `test_*` functions. Integration tests should clearly identify required Asterisk services, credentials, audio devices/files, and external APIs. Never commit API keys, passwords, phone numbers, or machine-specific paths.

## Commit & Pull Request Guidelines

Recent commits use short, imperative descriptions such as `Fix ...` and `Add ...`. Follow that convention: keep the subject specific and concise. Pull requests should explain the behavior change, identify affected Asterisk/ARI/AMI or provider configuration, list verification commands and results, and include documentation or example-config updates when public behavior changes. Call out breaking changes and external-service requirements explicitly.

## Security & Configuration Tips

Treat `example_configs/` as templates only. Keep AMI/ARI passwords, Google credentials, OpenAI keys, and provider credentials in local configuration or environment-managed secrets. Review diffs for secrets before committing.
