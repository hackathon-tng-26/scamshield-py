from typing import Literal

from pydantic import BaseModel, ConfigDict


class DemoScenarioDto(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    sender_id: str
    recipient_id: str | None
    recipient_phone: str | None
    recipient_display_name: str
    amount: float
    expected_verdict: Literal["GREEN", "YELLOW", "RED", "BLOCKED"]
    moment: int
