"""Optional, synchronous notifications. Listeners must enqueue work and return."""
import inspect
import logging
import time
import uuid
from contextlib import contextmanager
from functools import wraps
from dataclasses import dataclass, field
from datetime import datetime, timezone

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class UIEvent:
    kind: str
    data: dict
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    occurred_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


def notify(callback, kind, **data):
    if callback is not None:
        try:
            result = callback(UIEvent(kind, data))
            if inspect.isawaitable(result):
                if inspect.iscoroutine(result):
                    result.close()
                logger.warning("Event listeners must be synchronous")
        except Exception:
            # Never log the payload: it may contain conversation text.
            logger.warning("Event listener failed for %s", kind)


@contextmanager
def operation(callback, kind, **data):
    operation_id = str(uuid.uuid4())
    started = time.monotonic()
    notify(callback, kind + ".started", operation_id=operation_id, **data)
    outcome = "returned"
    try:
        yield operation_id
    except BaseException as exc:
        outcome = type(exc).__name__
        raise
    finally:
        notify(callback, kind + ".ended", operation_id=operation_id, outcome=outcome,
               elapsed_seconds=round(time.monotonic() - started, 3), **data)


def realtime_event(callback, event, model, segment_id):
    """Normalize selected SDK events; never forward audio or tool arguments."""
    try:
        common = dict(segment_id=segment_id, model=model)
        if event.type in ("audio_end", "audio_interrupted", "error"):
            notify(callback, "realtime." + event.type, item_id=getattr(event, "item_id", None),
                   meaning="sdk_event_not_proof_of_audible_completion", **common)
        if event.type != "raw_model_event" or getattr(event.data, "type", None) != "raw_server_event":
            return
        data = event.data.data
        if hasattr(data, "model_dump"):
            data = data.model_dump()
        if not isinstance(data, dict):
            return
        if data.get("type") == "response.created":
            notify(callback, "realtime.response_started", response_id=data["response"].get("id"), **common)
        elif data.get("type") == "conversation.item.input_audio_transcription.completed":
            notify(callback, "conversation.input", item_id=data.get("item_id"),
                   text=data.get("transcript"), usage=data.get("usage"), **common)
        elif data.get("type") == "response.done":
            response = data["response"]
            notify(callback, "realtime.usage", response_id=response.get("id"),
                   usage=response.get("usage"), status=response.get("status"), **common)
            for item in response.get("output", []):
                if item.get("type") == "message" and item.get("role", "assistant") == "assistant":
                    text = " ".join(c.get("transcript") or c.get("text") or "" for c in item.get("content", []))
                    notify(callback, "conversation.output", response_id=response.get("id"),
                           item_id=item.get("id"), text=text, status=response.get("status"),
                           delivery="generated_not_proof_fully_heard", **common)
    except Exception:
        logger.warning("Could not normalize realtime event")


def reports_operation(kind):
    """Emit lifecycle facts inside a library operation without exposing its input."""
    def decorate(function):
        @wraps(function)
        async def run(self, *args, **kwargs):
            with operation(self._dispatch_event, kind):
                return await function(self, *args, **kwargs)
        return run
    return decorate
