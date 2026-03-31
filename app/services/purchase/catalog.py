from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Optional

from app.core.enums import WalletType


class PurchaseKind(str, Enum):
    NORMAL_CREDITS = "normal_credits"
    VIP_CREDITS = "vip_credits"
    VIP_ACCESS = "vip_access"


@dataclass(frozen=True)
class PurchaseProduct:
    code: str
    kind: PurchaseKind
    usd_price: float
    normal_credits: int = 0
    vip_credits: int = 0
    vip_days: int = 0

    @property
    def wallet_type(self) -> Optional[WalletType]:
        if self.kind == PurchaseKind.NORMAL_CREDITS:
            return WalletType.NORMAL
        if self.kind == PurchaseKind.VIP_CREDITS:
            return WalletType.VIP
        return None


PRODUCTS: dict[str, PurchaseProduct] = {
    "normal_100": PurchaseProduct(
        code="normal_100",
        kind=PurchaseKind.NORMAL_CREDITS,
        usd_price=1.99,
        normal_credits=100,
    ),
    "normal_350": PurchaseProduct(
        code="normal_350",
        kind=PurchaseKind.NORMAL_CREDITS,
        usd_price=5.99,
        normal_credits=350,
    ),
    "normal_800": PurchaseProduct(
        code="normal_800",
        kind=PurchaseKind.NORMAL_CREDITS,
        usd_price=11.99,
        normal_credits=800,
    ),
    "vip_150": PurchaseProduct(
        code="vip_150",
        kind=PurchaseKind.VIP_CREDITS,
        usd_price=1.99,
        vip_credits=150,
    ),
    "vip_700": PurchaseProduct(
        code="vip_700",
        kind=PurchaseKind.VIP_CREDITS,
        usd_price=6.99,
        vip_credits=700,
    ),
    "vip_1800": PurchaseProduct(
        code="vip_1800",
        kind=PurchaseKind.VIP_CREDITS,
        usd_price=14.99,
        vip_credits=1800,
    ),
    "access_30d": PurchaseProduct(
        code="access_30d",
        kind=PurchaseKind.VIP_ACCESS,
        usd_price=2.99,
        vip_days=30,
    ),
    "access_90d": PurchaseProduct(
        code="access_90d",
        kind=PurchaseKind.VIP_ACCESS,
        usd_price=7.99,
        vip_days=90,
    ),
}


def get_product(code: str) -> PurchaseProduct | None:
    return PRODUCTS.get(code)


def build_order_id(product_code: str, telegram_id: int, timestamp: int) -> str:
    return f"p:{product_code}:u:{telegram_id}:t:{timestamp}"


def parse_order_id(order_id: str) -> tuple[str, int] | None:
    try:
        parts = order_id.split(":")
        if len(parts) != 6:
            return None
        if parts[0] != "p" or parts[2] != "u" or parts[4] != "t":
            return None
        product_code = parts[1]
        telegram_id = int(parts[3])
        return product_code, telegram_id
    except Exception:
        return None
