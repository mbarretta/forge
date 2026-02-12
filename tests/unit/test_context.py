"""Tests for ExecutionContext."""

import threading

from forge_core.context import ExecutionContext


def test_context_creation():
    """Test ExecutionContext creation with defaults."""
    ctx = ExecutionContext()

    assert ctx.auth_token == ""
    assert ctx.config == {}
    assert callable(ctx.on_progress)
    assert isinstance(ctx.cancel_event, threading.Event)


def test_context_with_values():
    """Test ExecutionContext creation with values."""
    cancel_event = threading.Event()
    progress_calls = []

    def on_progress(fraction, message):
        progress_calls.append((fraction, message))

    ctx = ExecutionContext(
        auth_token="test-token",
        config={"key": "value"},
        on_progress=on_progress,
        cancel_event=cancel_event,
    )

    assert ctx.auth_token == "test-token"
    assert ctx.config == {"key": "value"}
    assert ctx.cancel_event is cancel_event


def test_progress_callback():
    """Test progress reporting."""
    progress_calls = []

    def on_progress(fraction, message):
        progress_calls.append((fraction, message))

    ctx = ExecutionContext(on_progress=on_progress)

    ctx.progress(0.5, "Halfway done")
    ctx.progress(1.0, "Complete")

    assert len(progress_calls) == 2
    assert progress_calls[0] == (0.5, "Halfway done")
    assert progress_calls[1] == (1.0, "Complete")


def test_cancellation():
    """Test cancellation detection."""
    ctx = ExecutionContext()

    assert not ctx.is_cancelled

    ctx.cancel_event.set()

    assert ctx.is_cancelled
