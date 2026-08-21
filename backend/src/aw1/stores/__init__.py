"""Catalogo de tiendas."""

from .registry import STORES, Store, resolve, store_for_host

__all__ = ["STORES", "Store", "resolve", "store_for_host"]
