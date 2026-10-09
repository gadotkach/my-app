"""Маркетплейсы (расширяемая архитектура).

Регистрация клиентов — в app.marketplaces.bootstrap.
"""

from app.marketplaces.base import BaseMarketplaceClient, MarketplaceClientError
from app.marketplaces.registry import MarketplaceRegistry

__all__ = [
    "BaseMarketplaceClient",
    "MarketplaceClientError",
    "MarketplaceRegistry",
]
