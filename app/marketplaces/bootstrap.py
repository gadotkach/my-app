"""Регистрация всех клиентов маркетплейсов.

Импортируется один раз — из app.main (при старте).
"""

from app.marketplaces.registry import MarketplaceRegistry

# Импорт клиентов (регистрация через явный вызов ниже)
from app.ozon_ads_client import OzonAdsClient
from app.ozon_client import OzonClient
from app.wb_client import WBClient

# Явная регистрация
MarketplaceRegistry.register(OzonClient)
MarketplaceRegistry.register(WBClient)
MarketplaceRegistry.register(OzonAdsClient)
