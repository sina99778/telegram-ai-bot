from enum import Enum

class TransactionStatus(str, Enum):
    PENDING = "PENDING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    CANCELED = "CANCELED"
    REFUNDED = "REFUNDED"

class LedgerEntryType(str, Enum):
    USAGE = "USAGE"
    PURCHASE = "PURCHASE"
    REFUND = "REFUND"
    BONUS = "BONUS"
    ADMIN_ADJUSTMENT = "ADMIN_ADJUSTMENT"
    VIP_ACCESS = "VIP_ACCESS"

class WalletType(str, Enum):
    NORMAL = "NORMAL"
    VIP = "VIP"

class FeatureName(str, Enum):
    FLASH_TEXT = "FLASH_TEXT"
    PRO_TEXT = "PRO_TEXT"
    IMAGE_GEN = "IMAGE_GEN"
    IMAGE_EDIT = "IMAGE_EDIT"
    VOICE_GEN = "VOICE_GEN"

class PromoCodeKind(str, Enum):
    GIFT_NORMAL_CREDITS = "gift_normal_credits"
    GIFT_VIP_CREDITS = "gift_vip_credits"
    GIFT_VIP_DAYS = "gift_vip_days"
    DISCOUNT_PERCENT = "discount_percent"

class MessageRole(str, Enum):
    USER = "USER"
    MODEL = "MODEL"
    SYSTEM = "SYSTEM"
