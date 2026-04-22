# tests/unit/test_geoip.py (исправленный)
"""
Тесты для модуля определения региона по IP.
"""

import pytest

from src.common.utils.geoip import get_region_by_ip


class TestGeoIP:
    """Тесты для get_region_by_ip."""

    def test_localhost_ipv4(self):
        """Тест IPv4 localhost."""
        assert get_region_by_ip("127.0.0.1") == "local"
        assert get_region_by_ip("127.0.0.2") == "local"

    def test_local_network_192_168(self):
        """Тест локальной сети 192.168.x.x."""
        assert get_region_by_ip("192.168.1.1") == "local"
        assert get_region_by_ip("192.168.0.100") == "local"
        assert get_region_by_ip("192.168.255.255") == "local"

    def test_local_network_10(self):
        """Тест локальной сети 10.x.x.x."""
        assert get_region_by_ip("10.0.0.1") == "local"
        assert get_region_by_ip("10.255.255.255") == "local"
        assert get_region_by_ip("10.0.0.0") == "local"

    def test_localhost_ipv6(self):
        """Тест IPv6 localhost."""
        assert get_region_by_ip("::1") == "local"

    def test_public_ip(self):
        """Тест публичных IP."""
        assert get_region_by_ip("8.8.8.8") == "ru"
        assert get_region_by_ip("1.1.1.1") == "ru"
        assert get_region_by_ip("77.88.55.66") == "ru"
        assert get_region_by_ip("2001:4860:4860::8888") == "ru"

    def test_edge_cases(self):
        """Тест граничных случаев."""
        # 127.x.x.x - все локальные
        assert get_region_by_ip("127.255.255.255") == "local"
        # 192.168.x.x - все локальные
        assert get_region_by_ip("192.168.0.0") == "local"
        assert get_region_by_ip("192.168.0.1") == "local"
        # 10.x.x.x - все локальные
        assert get_region_by_ip("10.0.0.0") == "local"
        assert get_region_by_ip("10.255.255.255") == "local"

    def test_not_local_networks(self):
        """Тест сетей, которые не являются локальными."""
        assert get_region_by_ip("172.16.0.1") == "ru"  # 172.16.x.x - не в прототипе
        # 192.168.256.1 - невалидный IP, но в реальности не будет передан
        # Валидный публичный IP
        assert get_region_by_ip("8.8.8.8") == "ru"
