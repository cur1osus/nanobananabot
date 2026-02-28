from __future__ import annotations


def format_rub(amount: int) -> str:
    safe_amount = max(amount, 0)
    return str(safe_amount // 100)
