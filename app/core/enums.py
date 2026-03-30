from enum import Enum

class TransactionStatus(str, Enum):
    PENDING = "PENDING"
    SUCCESS = "SUCCESS"
    FAILED = "FAILED"

class LedgerEntryType(str, Enum):
    USAGE = "USAGE"
    PURCHASE = "PURCHASE"
    REFUND = "REFUND"
    BONUS = "BONUS"
    ADMIN_ADJUSTMENT = "ADMIN_ADJUSTMENT"

class FeatureName(str, Enum):
    FLASH_TEXT = "FLASH_TEXT"
    PRO_TEXT = "PRO_TEXT"
    IMAGE_GEN = "IMAGE_GEN"
    VOICE_GEN = "VOICE_GEN"

class MessageRole(str, Enum):
    USER = "USER"
    MODEL = "MODEL"
    SYSTEM = "SYSTEM"
