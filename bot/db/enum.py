import enum


class UserRole(enum.Enum):
    USER = "user"
    ADMIN = "admin"
    SUPPORT = "support"


class TransactionStatus(str, enum.Enum):
    PENDING = "pending"
    ASSIGNED = "assigned"
    COMPLETED = "completed"
    FAILED = "failed"
    SUCCESS = "success"
    REFUNDED = "refunded"


class TransactionType(str, enum.Enum):
    TOPUP = "topup"
    REFERRAL_BONUS = "referral_bonus"
    WITHDRAW_REQUEST = "withdraw_request"


class UsageEventType(str, enum.Enum):
    AI_TEXT = "ai_text"
    MANUAL_TEXT = "manual_text"
    INSTRUMENTAL = "instrumental"


class MusicTaskStatus(str, enum.Enum):
    PENDING = "pending"
    PROCESSING = "processing"
    SUCCESS = "success"
    ERROR = "error"
    TIMEOUT = "timeout"
