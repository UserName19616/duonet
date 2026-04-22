# src/network/geoip.py
"""
Модуль определения региона по IP-адресу.

Использует MaxMind GeoLite2 базу данных.
При отсутствии БД или ошибке возвращает "ru" (fallback).
Для приватных IP возвращает "local".
"""

import logging
import os
from functools import lru_cache
from ipaddress import ip_address, ip_network
from typing import Optional

import requests

logger = logging.getLogger(__name__)

# Путь к базе данных GeoIP
GEOIP_DB_PATH = os.environ.get("GEOIP_DB_PATH", "data/GeoLite2-Country.mmdb")
# URL для скачивания БД (бесплатная версия)
GEOIP_DB_URL = "https://github.com/P3TERX/GeoLite2.mmdb/raw/download/GeoLite2-Country.mmdb"

# Локальные сети (RFC 1918)
PRIVATE_NETWORKS = [
    ip_network("127.0.0.0/8"),      # localhost
    ip_network("10.0.0.0/8"),       # private (10.0.0.0 – 10.255.255.255)
    ip_network("192.168.0.0/16"),   # private (192.168.0.0 – 192.168.255.255)
    ip_network("169.254.0.0/16"),   # link-local
    ip_network("::1/128"),          # IPv6 localhost
    ip_network("fc00::/7"),         # IPv6 private (ULA)
]


def _is_private_ip(ip: str) -> bool:
    """Проверка, является ли IP локальным/частным."""
    try:
        addr = ip_address(ip)
        for network in PRIVATE_NETWORKS:
            if addr in network:
                return True
        return False
    except ValueError:
        return True  # невалидный IP считаем локальным


def _get_external_ip() -> str:
    """Получение внешнего IP через внешний сервис."""
    try:
        response = requests.get("https://api.ipify.org", timeout=5)
        if response.status_code == 200:
            return response.text.strip()
    except Exception as e:
        logger.warning(f"Failed to get external IP: {e}")
    return None


def _get_region_from_db(ip: str) -> Optional[str]:
    """Получение региона из GeoIP базы."""
    try:
        import geoip2.database
        if not os.path.exists(GEOIP_DB_PATH):
            logger.debug(f"GeoIP database not found at {GEOIP_DB_PATH}")
            return None

        reader = geoip2.database.Reader(GEOIP_DB_PATH)
        try:
            response = reader.country(ip)
            return response.country.iso_code.lower()
        finally:
            reader.close()
    except Exception as e:
        logger.debug(f"GeoIP lookup failed for {ip}: {e}")
        return None


def download_geoip_db(force: bool = False) -> bool:
    """
    Скачивание GeoIP базы данных.

    Args:
        force: Принудительная перезапись.

    Returns:
        True если успешно.
    """
    if os.path.exists(GEOIP_DB_PATH) and not force:
        logger.info(f"GeoIP database already exists at {GEOIP_DB_PATH}")
        return True

    os.makedirs(os.path.dirname(GEOIP_DB_PATH), exist_ok=True)

    try:
        logger.info(f"Downloading GeoIP database from {GEOIP_DB_URL}")
        response = requests.get(GEOIP_DB_URL, stream=True, timeout=30)
        response.raise_for_status()

        with open(GEOIP_DB_PATH, "wb") as f:
            for chunk in response.iter_content(chunk_size=8192):
                f.write(chunk)

        logger.info(f"GeoIP database downloaded to {GEOIP_DB_PATH}")
        return True
    except Exception as e:
        logger.error(f"Failed to download GeoIP database: {e}")
        return False


@lru_cache(maxsize=10000)
def get_region_by_ip(ip: str) -> str:
    """
    Определение региона по IP-адресу.

    Алгоритм:
      1. Если IP локальный → "local"
      2. Если IP не локальный → поиск в GeoIP БД
      3. При ошибке или отсутствии БД → "ru"

    Args:
        ip: IP-адрес (IPv4 или IPv6).

    Returns:
        Двухбуквенный код региона (например, "ru", "us", "de") или "local".
    """
    # Проверяем локальные IP
    if _is_private_ip(ip):
        logger.debug(f"IP {ip} is private, returning 'local'")
        return "local"

    # Пытаемся определить через GeoIP
    region = _get_region_from_db(ip)
    if region:
        return region

    # Fallback
    logger.debug(f"Could not determine region for {ip}, using 'ru'")
    return "ru"


def get_client_ip(request) -> str:
    """
    Извлечение реального IP клиента из запроса.

    Args:
        request: FastAPI Request объект.

    Returns:
        IP-адрес клиента.
    """
    forwarded = request.headers.get("X-Forwarded-For")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "0.0.0.0"
