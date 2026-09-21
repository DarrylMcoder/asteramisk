import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from asteramisk.events import UIEvent, realtime_event
from asteramisk.ui.ui import UI
from asteramisk.internal.tts import TTSEngine
from asteramisk.internal.transcriber import TranscribeEngine


def test_optional_listeners_are_isolated_and_removable():
    one, two = UI.__new__(UI), UI.__new__(UI)
    first, second = [], []
    one.emit_event("unused")
    def failed(event):
        raise RuntimeError("Listener failure")
    one.add_event_listener(failed)
    remove = one.add_event_listener(first.append)
    two.add_event_listener(second.append)
    one.emit_event("one")
    two.emit_event("two")
    remove()
    one.emit_event("unsubscribed")
    assert [e.kind for e in first] == ["one"]
    assert [e.kind for e in second] == ["two"]
    assert first[0].occurred_at.tzinfo is not None
    async def wrong(event):
        pass
    with pytest.raises(TypeError):
        one.add_event_listener(wrong)


@pytest.mark.asyncio
async def test_shared_tts_request_callbacks_and_actual_cache_hits():
    engine = TTSEngine.__new__(TTSEngine)
    engine.get_from_cache = AsyncMock(side_effect=[b"cached", None])
    engine._free_tts = AsyncMock(return_value=b"")
    first, second = [], []
    await asyncio.gather(
        engine.tts("one", save_to_cache=False, event_callback=first.append),
        engine.tts("two", save_to_cache=False, event_callback=second.append),
    )
    assert len(first) == len(second) == 1
    assert first[0].data["cached"] is True
    assert second[0].data["cached"] is False
    assert second[0].data["provider"] == "gtts"
    engine._free_tts.assert_awaited_once_with("two")


@pytest.mark.asyncio
async def test_controlled_tts_forwards_request_listener():
    engine = TTSEngine.__new__(TTSEngine)
    engine.tts = AsyncMock(return_value=b"audio")
    engine.save_to_cache = AsyncMock(return_value="file")
    callback = [].append
    await engine.tts_to_file("text", event_callback=callback)
    assert engine.tts.await_args.kwargs["event_callback"] == callback


@pytest.mark.asyncio
async def test_speech_recognition_reports_submitted_audio_without_transcript():
    engine = TranscribeEngine.__new__(TranscribeEngine)
    engine.is_transcribing = True
    stream = SimpleNamespace(connected=True)
    async def read():
        stream.connected = False
        return b"\0" * 16000
    stream.read = read
    async def recognize(requests):
        async for _ in requests:
            pass
        async def responses():
            yield SimpleNamespace(speech_event_type=0, results=[SimpleNamespace(is_final=True,
                alternatives=[SimpleNamespace(transcript="not recorded")])])
        return responses()
    engine.client = SimpleNamespace(streaming_recognize=recognize)
    events = []
    assert await engine.transcribe_from_stream(stream, event_callback=events.append) == "not recorded"
    assert events[0].data["audio_seconds"] == 1
    assert "not recorded" not in repr(events)


def test_realtime_usage_keeps_generated_output_distinct_from_playback():
    events = []
    raw = SimpleNamespace(type="raw_model_event", data=SimpleNamespace(type="raw_server_event", data={
        "type": "response.done", "response": {"id": "r1", "status": "cancelled", "usage": {"input_tokens": 10},
        "output": [{"type": "message", "id": "item1", "content": [{"transcript": "Partial answer"}]}]}}))
    realtime_event(events.append, raw, "gpt-realtime-2", "segment1")
    realtime_event(events.append, SimpleNamespace(type="audio_interrupted", item_id="item1"), "gpt-realtime-2", "segment1")
    assert [e.kind for e in events] == ["realtime.usage", "conversation.output", "realtime.audio_interrupted"]
    assert events[1].data["delivery"] == "generated_not_proof_fully_heard"
    assert events[1].data["item_id"] == events[2].data["item_id"]


@pytest.mark.asyncio
async def test_partial_google_tts_failure_retains_successful_chunk_usage():
    engine = TTSEngine.__new__(TTSEngine)
    engine._split_for_google_tts = lambda text: ["first", "second"]
    engine._client = SimpleNamespace(synthesize_speech=AsyncMock(side_effect=[
        SimpleNamespace(audio_content=b"audio"), RuntimeError("provider failed")]))
    events = []
    with pytest.raises(RuntimeError):
        await engine._premium_tts("first second", "voice", event_callback=events.append)
    assert [e.data["characters"] for e in events] == [5, 6]
    assert [e.data["outcome"] for e in events] == ["returned", "RuntimeError"]
