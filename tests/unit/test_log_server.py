from __future__ import annotations

from fastapi.testclient import TestClient

from aivenv.log_server import app, get_log_buffer, main, reset_log_buffers


def teardown_function() -> None:
    reset_log_buffers()


def test_index_returns_sse_log_page() -> None:
    client = TestClient(app)

    response = client.get("/")

    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]
    assert "new EventSource('/stream')" in response.text


def test_stream_returns_message_and_done_events() -> None:
    client = TestClient(app)
    buffer = get_log_buffer()

    async def seed() -> None:
        await buffer.write("hello\n")
        await buffer.done()

    import anyio

    anyio.run(seed)

    with client.stream("GET", "/stream") as response:
        body = response.read().decode("utf-8")

    assert response.status_code == 200
    assert "text/event-stream" in response.headers["content-type"]
    assert "event: message\ndata: hello\n\n" in body
    assert body.endswith("event: done\ndata: \n\n")


def test_raw_returns_execution_log_snapshot_as_text() -> None:
    client = TestClient(app)
    buffer = get_log_buffer("run-1")

    async def seed() -> None:
        await buffer.write("first\n")
        await buffer.write("second\n")

    import anyio

    anyio.run(seed)

    response = client.get("/raw/run-1")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/plain")
    assert response.text == "first\nsecond\n"


def test_main_binds_to_localhost_port_8081(monkeypatch) -> None:
    captured = {}

    def fake_run(target_app, *, host: str, port: int) -> None:
        captured["app"] = target_app
        captured["host"] = host
        captured["port"] = port

    monkeypatch.setattr("aivenv.log_server.uvicorn.run", fake_run)

    main()

    assert captured == {"app": app, "host": "127.0.0.1", "port": 8081}