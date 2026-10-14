"""One batch operation per work queue at a time.

"Read work queue", "Load demo workload" and "Retry with AI" each run many model calls and can take
minutes with a live model. Running two at once on the same queue would race over the same cases,
so a second request gets a clear "please wait" instead of a database error.

Process-local: correct for the single-worker deployments this POC uses (Render free tier, local).
A multi-worker production deployment would use a database or Redis lock instead.
"""
from __future__ import annotations

import threading
from contextlib import contextmanager

from app.errors import InvalidStateError

_guard = threading.Lock()
_running: dict[str, str] = {}


@contextmanager
def exclusive(queue: str, action: str):
    with _guard:
        if queue in _running:
            raise InvalidStateError(
                f"'{_running[queue]}' is still running on this queue. Wait for it to finish, then try again.")
        _running[queue] = action
    try:
        yield
    finally:
        with _guard:
            _running.pop(queue, None)


def running(queue: str) -> str | None:
    with _guard:
        return _running.get(queue)
