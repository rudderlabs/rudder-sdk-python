"""Shared pytest controls for deterministic repository tests."""

import ipaddress
import socket

import pytest


def _is_loopback(host):
    if host == 'localhost':
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


@pytest.fixture(autouse=True)
def block_external_network(monkeypatch):
    """Fail a test that tries to connect to a non-loopback address."""
    unexpected_hosts = []
    original_getaddrinfo = socket.getaddrinfo
    original_connect = socket.socket.connect

    def guarded_getaddrinfo(host, *args, **kwargs):
        if not _is_loopback(host):
            unexpected_hosts.append(str(host))
            raise AssertionError(
                'External network access is not allowed in repository tests: '
                '{}'.format(host))
        return original_getaddrinfo(host, *args, **kwargs)

    def guarded_connect(sock, address):
        if sock.family not in (socket.AF_INET, socket.AF_INET6):
            return original_connect(sock, address)
        host = address[0] if isinstance(address, tuple) else address
        if not _is_loopback(host):
            unexpected_hosts.append(str(host))
            raise AssertionError(
                'External network access is not allowed in repository tests: '
                '{}'.format(host))
        return original_connect(sock, address)

    monkeypatch.setattr(socket, 'getaddrinfo', guarded_getaddrinfo)
    monkeypatch.setattr(socket.socket, 'connect', guarded_connect)

    yield

    assert not unexpected_hosts, (
        'Repository test attempted external network access: {}'.format(
            ', '.join(sorted(set(unexpected_hosts)))))
