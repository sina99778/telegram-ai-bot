from abc import ABC, abstractmethod
from typing import Dict, Any, Tuple
from app.core.enums import TransactionStatus

class BasePaymentProvider(ABC):
    """Abstract interface for payment providers."""
    
    @property
    @abstractmethod
    def provider_name(self) -> str:
        pass

    @abstractmethod
    async def create_invoice(self, amount: float, currency: str, order_id: str, description: str, webhook_url: str) -> Dict[str, Any]:
        """
        Calls the external provider to create an invoice.
        Returns a dict containing at least {'invoice_url': str, 'provider_payment_id': str}
        """
        pass

    @abstractmethod
    async def verify_webhook(self, payload: Dict[str, Any], headers: Dict[str, str], raw_body: bytes) -> bool:
        """Verifies the authenticity of the webhook payload using provider signatures."""
        pass

    @abstractmethod
    def parse_webhook_status(self, payload: Dict[str, Any]) -> Tuple[str, TransactionStatus]:
        """
        Parses the raw payload to extract the provider_payment_id and the normalized TransactionStatus.
        Returns: (provider_payment_id, status)
        """
        pass
