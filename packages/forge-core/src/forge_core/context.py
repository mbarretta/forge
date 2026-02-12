"""Execution context passed to every plugin run."""

from __future__ import annotations

import threading
from dataclasses import dataclass, field
from typing import Callable


@dataclass
class ExecutionContext:
    """Context provided to plugins during execution.

    Attributes:
        auth_token: Chainguard auth token (from chainctl).
        config: Arbitrary configuration dict (from env vars or config file).
        on_progress: Callback to report progress. Called with (fraction, message)
                     where fraction is 0.0-1.0.
        cancel_event: Threading event that is set when cancellation is requested.
                      Plugins should check this periodically in long-running loops.
    """

    auth_token: str = ""
    config: dict = field(default_factory=dict)
    on_progress: Callable[[float, str], None] = field(default=lambda f, m: None)
    cancel_event: threading.Event = field(default_factory=threading.Event)

    def progress(self, fraction: float, message: str) -> None:
        """Report progress. Convenience wrapper around on_progress."""
        self.on_progress(fraction, message)

    @property
    def is_cancelled(self) -> bool:
        """Check if cancellation has been requested."""
        return self.cancel_event.is_set()
