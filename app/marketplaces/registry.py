"""Реестр клиентов маркетплейсов."""

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.marketplaces.base import BaseMarketplaceClient


class MarketplaceRegistry:
    """Реестр клиентов маркетплейсов."""

    _clients: dict[str, type["BaseMarketplaceClient"]] = {}

    @classmethod
    def register(cls, client_cls: type["BaseMarketplaceClient"]) -> type["BaseMarketplaceClient"]:
        if not client_cls.code or client_cls.code == "unknown":
            raise ValueError(f"{client_cls.__name__}: code должен быть определён")
        cls._clients[client_cls.code] = client_cls
        return client_cls

    @classmethod
    def get(cls, code: str) -> type["BaseMarketplaceClient"]:
        if code not in cls._clients:
            raise ValueError(f"Unknown marketplace: {code}")
        return cls._clients[code]

    @classmethod
    def all(cls) -> dict[str, type["BaseMarketplaceClient"]]:
        return dict(cls._clients)

    @classmethod
    def codes(cls) -> list[str]:
        return sorted(cls._clients.keys())
