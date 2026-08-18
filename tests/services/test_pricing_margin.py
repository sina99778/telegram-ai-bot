"""Living spec for the >=70% profit-margin guarantee.

Real per-unit provider costs are taken from the billing export. The configured
credit costs and pack prices must keep every credit pack above the target
margin, even when a buyer spends entirely on the costliest feature. If someone
turns a feature back into a loss leader (e.g. image=10 credits), these fail.
"""

import pytest

from app.core.config import settings
from app.services.purchase.catalog import PRODUCTS

# Measured from the Gemini pricing table (€). Conservative where uncertain.
REAL_COST_EUR = {
    "flash_msg": 0.0011,   # one Flash message (capped input + output)
    "pro_msg": 0.004,      # one Pro (3.7 Flash) message
    "image": 0.066,        # one generated image
}
USD_TO_EUR = 0.92
TARGET_MARGIN = 0.70


def _credits(p):
    return p.normal_credits or p.vip_credits


def _worst_cost_per_credit() -> float:
    """€ cost of one credit when spent on its most expensive feature."""
    return max(
        REAL_COST_EUR["flash_msg"] / settings.NORMAL_MESSAGE_COST,
        REAL_COST_EUR["pro_msg"] / settings.VIP_MESSAGE_COST,
        REAL_COST_EUR["image"] / settings.IMAGE_CREDIT_COST,
    )


@pytest.mark.parametrize("code", [c for c, p in PRODUCTS.items() if _credits(p)])
def test_each_credit_pack_keeps_target_margin(code):
    p = PRODUCTS[code]
    sale_per_credit = p.usd_price * USD_TO_EUR / _credits(p)
    margin = 1 - _worst_cost_per_credit() / sale_per_credit
    assert margin >= TARGET_MARGIN, f"{code}: margin {margin:.0%} < {TARGET_MARGIN:.0%}"


def test_no_feature_is_a_loss_leader():
    """At the cheapest pack's per-credit price, every feature still clears 70%."""
    cheapest = min(p.usd_price * USD_TO_EUR / _credits(p) for p in PRODUCTS.values() if _credits(p))
    assert REAL_COST_EUR["flash_msg"] <= cheapest * settings.NORMAL_MESSAGE_COST * (1 - TARGET_MARGIN)
    assert REAL_COST_EUR["pro_msg"] <= cheapest * settings.VIP_MESSAGE_COST * (1 - TARGET_MARGIN)
    assert REAL_COST_EUR["image"] <= cheapest * settings.IMAGE_CREDIT_COST * (1 - TARGET_MARGIN)
