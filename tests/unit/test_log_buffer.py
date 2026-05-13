import asyncio
import threading

import pytest

from aivenv.logs.log_buffer import LogBuffer



async def acollect(stream, limit: int):
    result = []
    async for item in stream:
        result.append(item)
        if len(result) >= limit:
            break
    return result



@pytest.mark.asyncio
async def test_snapshot_and_bounded_retention():
    buffer = LogBuffer(max_lines=2)

    await buffer.write("one\n")
    await buffer.write("two\n")
    await buffer.write("three\n")

    assert await buffer.snapshot() == "two\nthree\n"


@pytest.mark.asyncio
async def test_catch_up_and_live_stream_delivery():
    buffer = LogBuffer()
    await buffer.write("boot\n")

    async def reader():
        items = []
        async for line in buffer.stream():
            items.append(line)
            if line == "live\n":
                break
        return items

    task = asyncio.create_task(reader())
    await asyncio.sleep(0)
    await buffer.write("live\n")

    assert await asyncio.wait_for(task, 1) == ["boot\n", "live\n"]



@pytest.mark.asyncio
async def test_done_terminates_active_stream():
    buffer = LogBuffer()

    task = asyncio.create_task(acollect(buffer.stream(), 1))
    await asyncio.sleep(0)
    await buffer.write("log\n")
    await buffer.done()

    assert await asyncio.wait_for(task, 1) == ["log\n"]
    with pytest.raises(RuntimeError):
        await buffer.write("not allowed\n")


@pytest.mark.asyncio
async def test_clear_resets_buffer_and_closes_stream():
    buffer = LogBuffer()
    await buffer.write("old\n")

    task = asyncio.create_task(acollect(buffer.stream(), 10))
    await asyncio.sleep(0)
    await buffer.clear()
    await buffer.write("new\n")

    assert await buffer.snapshot() == "new\n"
    assert await asyncio.wait_for(task, 1) == ["old\n"]


@pytest.mark.asyncio
async def test_write_can_fan_out_to_subscriber_on_another_thread():
    buffer = LogBuffer()
    ready = threading.Event()
    result: list[str] | None = None

    def run_reader() -> None:
        nonlocal result
        async def reader() -> list[str]:
            items: list[str] = []
            async for line in buffer.stream():
                ready.set()
                items.append(line)
                if line == "from main\n":
                    break
            return items

        result = asyncio.run(reader())

    thread = threading.Thread(target=run_reader)
    thread.start()

    await buffer.write("prime\n")
    assert ready.wait(1)
    await buffer.write("from main\n")
    thread.join(timeout=1)

    assert result == ["prime\n", "from main\n"]
