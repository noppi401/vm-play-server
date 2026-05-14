"""FastAPI log viewer server for execution output."""

from __future__ import annotations

from collections.abc import AsyncIterator
from html import escape

import uvicorn
from fastapi import FastAPI, Query
from fastapi.responses import HTMLResponse, PlainTextResponse, StreamingResponse

from aivenv.logs.log_buffer import LogBuffer

LOCALHOST = "127.0.0.1"
PORT = 8081
DEFAULT_EXECUTION_ID = "default"

app = FastAPI(title="aivenv Log Viewer")
_buffers: dict[str, LogBuffer] = {}


def get_log_buffer(execution_id: str = DEFAULT_EXECUTION_ID) -> LogBuffer:
    """Return the log buffer for an execution, creating it when needed."""
    buffer = _buffers.get(execution_id)
    if buffer is None:
        buffer = LogBuffer()
        _buffers[execution_id] = buffer
    return buffer


def reset_log_buffers() -> None:
    """Clear registered buffers. Intended for tests and process reset hooks."""
    _buffers.clear()


def _format_sse_event(event: str, data: str = "") -> str:
    lines = data.splitlines() or [""]
    payload = [f"event: {event}"]
    payload.extend(f"data: {line}" for line in lines)
    return "\n".join(payload) + "\n\n"


async def _event_stream(buffer: LogBuffer) -> AsyncIterator[str]:
    yield "retry: 0\n\n"
    async for chunk in buffer.stream():
        yield _format_sse_event("message", chunk)
    yield _format_sse_event("done")


@app.get("/", response_class=HTMLResponse)
async def index(id: str = Query(default=DEFAULT_EXECUTION_ID)) -> HTMLResponse:
    escaped_id = escape(id)
    html = f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>aivenv logs</title>
  <style>
    :root {{ color-scheme: light dark; }}
    body {{ margin: 0; font-family: ui-monospace, SFMono-Regular, Consolas, monospace; background: #101418; color: #e6edf3; }}
    header {{ padding: 12px 16px; border-bottom: 1px solid #30363d; background: #161b22; }}
    h1 {{ margin: 0; font-size: 16px; font-weight: 600; }}
    span.eid {{ font-weight: normal; color: #8b949e; margin-left: 8px; }}
    pre {{ margin: 0; padding: 16px; white-space: pre-wrap; word-break: break-word; }}
  </style>
</head>
<body>
  <header><h1>aivenv logs<span class="eid">{escaped_id}</span></h1></header>
  <pre id="log"></pre>
  <script>
    const log = document.getElementById('log');
    const source = new EventSource('/stream?id={escaped_id}');
    source.addEventListener('message', (event) => {{
      log.textContent += event.data + '\\n';
      window.scrollTo(0, document.body.scrollHeight);
    }});
    source.addEventListener('done', () => {{
      source.close();
    }});
    source.addEventListener('error', () => {{
      if (source.readyState === EventSource.CLOSED) return;
      source.close();
    }});
  </script>
</body>
</html>
"""
    return HTMLResponse(content=html)


@app.get("/stream")
async def stream(id: str = Query(default=DEFAULT_EXECUTION_ID)) -> StreamingResponse:
    return StreamingResponse(
        _event_stream(get_log_buffer(id)),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


@app.get("/raw/{execution_id}", response_class=PlainTextResponse)
async def raw(execution_id: str) -> PlainTextResponse:
    return PlainTextResponse(get_log_buffer(execution_id).snapshot(), media_type="text/plain")


def main() -> None:
    uvicorn.run(app, host=LOCALHOST, port=PORT)


if __name__ == "__main__":
    main()