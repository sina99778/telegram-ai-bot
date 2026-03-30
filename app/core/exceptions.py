class AppError(Exception):
    """Base exception for all application errors."""
    pass

class BillingError(AppError):
    """Base exception for billing-related errors."""
    pass

class InsufficientCreditsError(BillingError):
    def __init__(self, required: int, available: int):
        self.required = required
        self.available = available
        super().__init__(f"Insufficient credits. Required: {required}, Available: {available}")

class DuplicateTransactionError(BillingError):
    """Raised when an idempotent operation is retried with the same reference_id."""
    pass
