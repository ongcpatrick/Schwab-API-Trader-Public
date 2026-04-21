"""Risk-check routes."""

from fastapi import APIRouter
from pydantic import BaseModel

from schwab_trader.risk.engine import check_order
from schwab_trader.risk.models import AccountSnapshot, OrderIntent, RiskCheckResult, RiskPolicy


class OrderRiskCheckRequest(BaseModel):
    """Request payload for order risk evaluation."""

    policy: RiskPolicy
    account: AccountSnapshot
    order: OrderIntent


router = APIRouter()


@router.post("/check-order", response_model=RiskCheckResult)
def risk_check(payload: OrderRiskCheckRequest) -> RiskCheckResult:
    """Run the risk engine for a pending order."""

    return check_order(order=payload.order, policy=payload.policy, account=payload.account)
