import ipaddress
import socket
from dataclasses import dataclass
from time import monotonic
from urllib.parse import urljoin, urlsplit

import httpx

from cybernews_runtime.news import web_url

PUBLIC_IP_TRANSITIONS = tuple(
    ipaddress.ip_network(network) for network in ("64:ff9b::/96", "64:ff9b:1::/48", "2001::/32", "2002::/16")
)


class FeedError(Exception):
    """Safe, message-free diagnostic code for an external dependency."""


@dataclass(frozen=True)
class FeedResponse:
    body: bytes | None
    url: str
    etag: str | None
    last_modified: str | None


def validated_host(url: str, allowlist: frozenset[str]) -> tuple[str, int]:
    try:
        parts = urlsplit(web_url(url))
        host = parts.hostname.rstrip(".").encode("idna").decode("ascii").lower()
        expected_port = 443 if parts.scheme == "https" else 80
        if host not in allowlist or parts.port not in (None, expected_port) or parts.fragment:
            raise FeedError("blocked_feed_address")
        return host, expected_port
    except (UnicodeError, ValueError):
        raise FeedError("invalid_feed_url") from None


def is_public(address: str) -> bool:
    ip = ipaddress.ip_address(address)
    if not ip.is_global or ip.is_multicast or ip.is_reserved:
        return False
    if isinstance(ip, ipaddress.IPv6Address):
        return ip.ipv4_mapped is None and not any(ip in block for block in PUBLIC_IP_TRANSITIONS)
    return True


def resolved_addresses(host: str, port: int, resolver=socket.getaddrinfo) -> list[str]:
    try:
        result = resolver(host, port, type=socket.SOCK_STREAM)
        addresses = list(dict.fromkeys(row[4][0] for row in result))
        if not addresses or any(not is_public(address) for address in addresses):
            raise FeedError("blocked_feed_ip")
    except socket.gaierror:
        raise FeedError("dns_error") from None
    return sorted(addresses, key=lambda address: ":" in address)


def safe_validator(value: str | None) -> str | None:
    if value and len(value) <= 512 and all(32 <= ord(char) <= 126 for char in value):
        return value
    return None


class FeedFetcher:
    def __init__(self, hosts, max_bytes, *, resolver=socket.getaddrinfo, transport_factory=None):
        self.hosts = hosts
        self.max_bytes = max_bytes
        self.resolver = resolver
        self.transport_factory = transport_factory

    def fetch(self, url, *, etag=None, last_modified=None, validator_url=None):
        deadline = monotonic() + 15
        for hop in range(5):
            host, port = validated_host(url, self.hosts)
            addresses = resolved_addresses(host, port, self.resolver)
            headers = {
                "Host": host,
                "User-Agent": "CyberNews/0.3 (RSS reader; https://github.com/Sergo379/CyberNews)",
                "Accept": "application/rss+xml, application/atom+xml, application/xml, text/xml;q=0.9, */*;q=0.1",
                "Accept-Encoding": "identity",
            }
            if url == validator_url:
                if etag:
                    headers["If-None-Match"] = etag
                if last_modified:
                    headers["If-Modified-Since"] = last_modified
            result = self.request(url, host, addresses, headers, deadline)
            if isinstance(result, FeedResponse):
                return result
            if hop == 4:
                raise FeedError("too_many_redirects")
            target = urljoin(url, result)
            if urlsplit(url).scheme == "https" and urlsplit(target).scheme != "https":
                raise FeedError("blocked_redirect")
            url = target
        raise FeedError("too_many_redirects")

    def request(self, url, host, addresses, headers, deadline):
        for address in addresses[:2]:
            remaining = deadline - monotonic()
            if remaining <= 0:
                raise FeedError("feed_timeout")
            # Pin the actual connection to a validated IP and preserve Host and TLS SNI.
            # Each request owns its pool, so a connection cannot be reused for a different host.
            target = httpx.URL(url).copy_with(host=address)
            try:
                transport = self.transport_factory() if self.transport_factory else None
                with httpx.Client(
                    timeout=min(4, remaining), trust_env=False, follow_redirects=False, transport=transport,
                ) as client:
                    with client.stream("GET", target, headers=headers, extensions={"sni_hostname": host}) as reply:
                        return self.read_response(reply, url, deadline)
            except (httpx.ConnectError, httpx.ConnectTimeout):
                continue
            except httpx.TimeoutException:
                raise FeedError("feed_timeout") from None
            except (httpx.RequestError, httpx.InvalidURL):
                raise FeedError("feed_network_error") from None
        raise FeedError("feed_connection_error")

    def read_response(self, reply, url, deadline):
        if reply.status_code in {301, 302, 303, 307, 308}:
            target = reply.headers.get("location")
            if not target:
                raise FeedError("invalid_redirect")
            return target
        etag = safe_validator(reply.headers.get("etag"))
        modified = safe_validator(reply.headers.get("last-modified"))
        if reply.status_code == 304:
            return FeedResponse(None, url, etag, modified)
        if reply.status_code != 200:
            raise FeedError(f"feed_http_{reply.status_code}")
        if reply.headers.get("content-encoding", "identity").lower() != "identity":
            raise FeedError("unsupported_feed_encoding")
        length = reply.headers.get("content-length")
        if length is not None:
            if not length.isdecimal() or len(length) > 10:
                raise FeedError("invalid_feed_length")
            if int(length) > self.max_bytes:
                raise FeedError("feed_too_large")
        data = bytearray()
        # MockTransport may return pre-buffered data. Real requests stream raw bytes.
        chunks = (reply.content,) if reply.is_stream_consumed else reply.iter_raw(chunk_size=16_384)
        for chunk in chunks:
            if monotonic() > deadline:
                raise FeedError("feed_timeout")
            if len(data) + len(chunk) > self.max_bytes:
                raise FeedError("feed_too_large")
            data.extend(chunk)
        return FeedResponse(bytes(data), url, etag, modified)
