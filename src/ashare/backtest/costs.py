"""Trading cost helpers for Phase 1b backtests."""

from __future__ import annotations


def calculate_trade_costs(
    side: str,
    notional: float,
    commission_bps: float,
    stamp_tax_bps: float,
    min_commission_yuan: float,
) -> dict[str, float]:
    """Return commission, stamp tax, and total cost for one order."""
    normalized_side = side.lower()
    if normalized_side not in {"buy", "sell"}:
        raise ValueError("side must be 'buy' or 'sell'.")
    trade_notional = abs(float(notional))
    if trade_notional <= 0:
        return {"commission": 0.0, "stamp_tax": 0.0, "total_cost": 0.0}

    commission = max(trade_notional * float(commission_bps) / 10_000.0, float(min_commission_yuan))
    stamp_tax = (
        trade_notional * float(stamp_tax_bps) / 10_000.0
        if normalized_side == "sell"
        else 0.0
    )
    return {
        "commission": float(commission),
        "stamp_tax": float(stamp_tax),
        "total_cost": float(commission + stamp_tax),
    }
