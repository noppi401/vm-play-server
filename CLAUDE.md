# CLAUDE.md

AIvenv is a Phase 1 CLI-based virtual code execution environment. It accepts natural-language instructions over HTTP, generates executable code with the OpenAI API, runs that code inside a Docker container, and exposes execution logs through an ngrok URL.

Development commands:

- pip install -e .[dev]
- pytest
- ruff check src tests
- ruff format src tests
- mypy

Architectural boundaries:
- aivenv.cli owns CLI parsing, configuration validation, process lifecycle, and signal handling.
- aivenv.execution owns execution state, code generation orchestration, container startup, and cleanup.
- aivenv.logs owns log buffering and the local log viewer server.
- aivenv.tunnel owns ngrok authentication, tunnel startup, URL retrieval, and shutdown.

Security notes:

Generated code must never run on the host. Containers should use resource limits, a dedicated output volume, and no write access to unrelated host paths. Secrets must come from environment variables or CLI flags and must not be logged.
