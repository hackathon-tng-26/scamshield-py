from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import DemoScenario
from app.schemas.scenarios import DemoScenarioDto

router = APIRouter()


@router.get("", response_model=list[DemoScenarioDto])
def list_scenarios(db: Session = Depends(get_db)) -> list[DemoScenarioDto]:
    rows = db.query(DemoScenario).order_by(DemoScenario.moment, DemoScenario.id).all()
    return [
        DemoScenarioDto(
            id=row.id,
            sender_id=row.sender_id,
            recipient_id=row.recipient_id,
            recipient_phone=row.recipient_phone,
            recipient_display_name=row.recipient_display_name,
            amount=row.amount,
            expected_verdict=row.expected_verdict,  # type: ignore[arg-type]
            moment=row.moment,
        )
        for row in rows
    ]
