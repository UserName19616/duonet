"""Вспомогательные утилиты."""
from .geoip import get_region_by_ip, get_client_ip

__all__ = ["get_region_by_ip", "get_client_ip"]
