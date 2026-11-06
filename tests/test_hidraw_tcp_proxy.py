"""Tests for contrib/hidraw-tcp-proxy --allow access control (stdlib only, no hidraw needed)."""

from __future__ import annotations

import argparse
import importlib.util
import ipaddress
import logging
import os
from pathlib import Path
import socket

import pytest

_PATH = Path(__file__).resolve().parents[1] / "contrib" / "hidraw-tcp-proxy" / "hidraw_tcp_proxy.py"
_spec = importlib.util.spec_from_file_location("hidraw_tcp_proxy", _PATH)
assert _spec is not None and _spec.loader is not None
proxy_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(proxy_mod)


def test_parse_allow_none_means_any():
	assert proxy_mod.parse_allow(None) is None
	assert proxy_mod.parse_allow([]) is None


def test_parse_allow_mixed_and_comma_separated():
	nets = proxy_mod.parse_allow(["10.0.0.6", "10.0.0.10/31, 10.0.0.21", "fd00::/8"])
	assert nets == [
		ipaddress.ip_network("10.0.0.6/32"),
		ipaddress.ip_network("10.0.0.10/31"),
		ipaddress.ip_network("10.0.0.21/32"),
		ipaddress.ip_network("fd00::/8"),
	]


@pytest.mark.parametrize("value", ["10.0.0.300", "evil.example", "10.0.0.0/33", " , "])
def test_parse_allow_rejects_invalid(value):
	with pytest.raises(argparse.ArgumentTypeError):
		proxy_mod.parse_allow([value])


@pytest.mark.parametrize(
	("address", "expected"),
	[
		("10.0.0.6", True),
		("10.0.0.11", True),  # 10.0.0.10/31
		("10.0.0.12", False),
		("10.0.0.5", False),
		("::ffff:10.0.0.6", True),  # IPv4-mapped
		("fd00::1", False),  # no IPv6 network allowed
		("not-an-ip", False),
	],
)
def test_is_allowed(address, expected):
	allow = proxy_mod.parse_allow(["10.0.0.6,10.0.0.10/31"])
	assert proxy_mod.is_allowed(address, allow) is expected


def test_is_allowed_without_list_accepts_everyone():
	assert proxy_mod.is_allowed("192.0.2.1", None) is True


def _proxy_with_listener(allow):
	"""Proxy with a real listener on 127.0.0.1 and a dummy 'device' fd."""
	proxy = proxy_mod.Proxy(None, 0x16D6, 0x0008, "127.0.0.1", 0, allow)
	listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
	listener.bind(("127.0.0.1", 0))
	listener.listen(8)
	proxy._listener = listener
	read_fd, write_fd = os.pipe()
	proxy._dev_fd = read_fd  # pretend the device is open
	return proxy, listener, (read_fd, write_fd)


def _cleanup(proxy, listener, fds):
	for client in list(proxy._clients.values()):
		client.sock.close()
	listener.close()
	for fd in fds:
		os.close(fd)


def _connect(listener):
	client = socket.create_connection(listener.getsockname(), timeout=2)
	client.settimeout(2)
	return client


def test_allowed_client_is_accepted():
	proxy, listener, fds = _proxy_with_listener(proxy_mod.parse_allow(["127.0.0.1"]))
	try:
		client = _connect(listener)
		proxy._on_accept(0)
		assert len(proxy._clients) == 1
		client.close()
	finally:
		_cleanup(proxy, listener, fds)


def test_disallowed_client_is_closed_and_logged_once(caplog):
	proxy, listener, fds = _proxy_with_listener(proxy_mod.parse_allow(["10.0.0.6"]))
	try:
		with caplog.at_level(logging.WARNING, logger="hidraw-tcp-proxy"):
			for _ in range(3):
				client = _connect(listener)
				proxy._on_accept(0)
				assert client.recv(1) == b""  # closed by the proxy
				client.close()
		assert proxy._clients == {}
		refusals = [r for r in caplog.records if "not in --allow" in r.getMessage()]
		assert len(refusals) == 1  # rate-limited per address
	finally:
		_cleanup(proxy, listener, fds)


def test_no_allow_list_keeps_old_behaviour():
	proxy, listener, fds = _proxy_with_listener(None)
	try:
		client = _connect(listener)
		proxy._on_accept(0)
		assert len(proxy._clients) == 1
		client.close()
	finally:
		_cleanup(proxy, listener, fds)


def test_refused_log_memory_is_bounded(monkeypatch):
	proxy = proxy_mod.Proxy(None, 0x16D6, 0x0008, "127.0.0.1", 0, proxy_mod.parse_allow(["10.0.0.6"]))
	monkeypatch.setattr(proxy_mod, "REFUSED_LOG_MAX_PEERS", 10)
	for i in range(25):
		proxy._log_refused("192.0.2.{}".format(i), "192.0.2.{}:1".format(i))
	assert len(proxy._refused_logged) <= 10
