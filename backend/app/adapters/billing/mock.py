"""Mock billing work queue backed by a JSON fixture of SYNTHETIC claims."""
from __future__ import annotations

import json
from pathlib import Path

from app.adapters.billing.base import BillingQueueAdapter, ClaimWorkItem


class MockBillingQueueAdapter(BillingQueueAdapter):
    def __init__(self, data: dict):
        self._items = [ClaimWorkItem(**c) for c in data.get("claims", [])]

    @classmethod
    def from_file(cls, path: Path) -> "MockBillingQueueAdapter":
        return cls(json.loads(Path(path).read_text(encoding="utf-8")))

    def list_queues(self) -> list[str]:
        return sorted({i.queue for i in self._items})

    def list_work_items(self, queue: str) -> list[ClaimWorkItem]:
        return [i.model_copy(deep=True) for i in self._items if i.queue == queue]

    def get_work_item(self, claim_id: str) -> ClaimWorkItem | None:
        return next((i.model_copy(deep=True) for i in self._items if i.claim_id == claim_id), None)
