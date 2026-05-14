"""FastAPI log viewer server for execution output."""

from __future__ import annotations

from collections.abc import AsyncIterator
from html import escape

import uvicorn
from fastapi import FastAPI, Query
from fastapi.responses import HTMLResponse, JSONResponse, PlainTextResponse, StreamingResponse

from aivenv.logs.log_buffer import LogBuffer

LOCALHOST = "127.0.0.1"
PORT = 8081
DEFAULT_EXECUTION_ID = "default"

app = FastAPI(title="aivenv Log Viewer")
_buffers: dict[str, LogBuffer] = {}
_metadata: dict[str, dict[str, str]] = {}


def get_log_buffer(execution_id: str = DEFAULT_EXECUTION_ID) -> LogBuffer:
    """Return the log buffer for an execution, creating it when needed."""
    buffer = _buffers.get(execution_id)
    if buffer is None:
        buffer = LogBuffer()
        _buffers[execution_id] = buffer
    return buffer


def set_execution_metadata(execution_id: str, instruction: str, code: str) -> None:
    """Store instruction and generated code for an execution."""
    _metadata[execution_id] = {"instruction": instruction, "code": code}


def reset_log_buffers() -> None:
    """Clear registered buffers. Intended for tests and process reset hooks."""
    _buffers.clear()
    _metadata.clear()


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
<html lang="ja">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>aivenv - {escaped_id}</title>
  <style>
    * {{ box-sizing: border-box; margin: 0; padding: 0; }}
    body {{ font-family: ui-monospace, SFMono-Regular, Consolas, monospace; background: #0d1117; color: #e6edf3; height: 100vh; display: flex; flex-direction: column; overflow: hidden; }}
    header {{ padding: 10px 16px; border-bottom: 1px solid #30363d; background: #161b22; flex-shrink: 0; display: flex; align-items: center; gap: 10px; }}
    h1 {{ font-size: 15px; font-weight: 600; }}
    .eid {{ font-weight: normal; color: #8b949e; font-size: 12px; }}
    .panels {{ display: flex; flex: 1; overflow: hidden; gap: 1px; background: #30363d; }}
    .panel {{ display: flex; flex-direction: column; background: #0d1117; overflow: hidden; }}
    .panel:nth-child(1) {{ flex: 0 0 22%; }}
    .panel:nth-child(2) {{ flex: 0 0 40%; }}
    .panel:nth-child(3) {{ flex: 1; }}
    .panel-header {{ padding: 7px 12px; background: #161b22; border-bottom: 1px solid #30363d; font-size: 11px; font-weight: 700; color: #8b949e; text-transform: uppercase; letter-spacing: 0.06em; flex-shrink: 0; }}
    .panel-body {{ flex: 1; overflow-y: auto; padding: 12px; }}
    pre {{ white-space: pre-wrap; word-break: break-word; font-size: 13px; line-height: 1.6; }}
    #instruction {{ font-family: system-ui, -apple-system, sans-serif; font-size: 14px; line-height: 1.7; color: #e6edf3; }}
    .muted {{ color: #8b949e; font-style: italic; }}
  </style>
</head>
<body>
  <header>
    <h1>aivenv</h1>
    <span class="eid">{escaped_id}</span>
  </header>
  <div class="panels">
    <div class="panel">
      <div class="panel-header">指示</div>
      <div class="panel-body"><div id="instruction"><span class="muted">読み込み中...</span></div></div>
    </div>
    <div class="panel">
      <div class="panel-header">コード</div>
      <div class="panel-body"><pre id="code"><span class="muted">読み込み中...</span></pre></div>
    </div>
    <div class="panel">
      <div class="panel-header">出力結果</div>
      <div class="panel-body" id="output-body"><pre id="log"></pre></div>
    </div>
  </div>
  <script>
    const eid = '{escaped_id}';

    fetch('/meta/' + eid)
      .then(r => r.json())
      .then(data => {{
        document.getElementById('instruction').textContent = data.instruction || '(なし)';
        document.getElementById('code').textContent = data.code || '(なし)';
      }})
      .catch(() => {{
        document.getElementById('instruction').textContent = '(取得失敗)';
        document.getElementById('code').textContent = '(取得失敗)';
      }});

    const log = document.getElementById('log');
    const outputBody = document.getElementById('output-body');
    const source = new EventSource('/stream?id=' + eid);
    source.addEventListener('message', (event) => {{
      log.textContent += event.data + '\\n';
      outputBody.scrollTop = outputBody.scrollHeight;
    }});
    source.addEventListener('done', () => {{ source.close(); }});
    source.addEventListener('error', () => {{
      if (source.readyState === EventSource.CLOSED) return;
      source.close();
    }});
  </script>
</body>
</html>
"""
    return HTMLResponse(content=html)


@app.get("/meta/{execution_id}")
async def meta(execution_id: str) -> JSONResponse:
    data = _metadata.get(execution_id, {})
    return JSONResponse({"instruction": data.get("instruction", ""), "code": data.get("code", "")})


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