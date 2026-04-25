from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict


class AlertEntry(BaseModel):
    model_config = ConfigDict(extra="forbid")

    transaction_id: str
    timestamp: datetime
    sender_id: str
    recipient_id: str
    recipient_phone: str
    recipient_label: str
    amount: float
    score: int
    verdict: Literal["GREEN", "YELLOW", "RED"]
    top_feature: str | None = None
