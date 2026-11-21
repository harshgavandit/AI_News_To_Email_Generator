"""Stable client identity for abuse controls.

IPv6 users normally receive at least a /64, so a per-address quota can be bypassed by
rotating interface identifiers. Quotas therefore key IPv6 clients by their /64 prefix.
"""
import ipaddress
import os

IPV6_PREFIX = 64


def client_address(request) -> str:
    """Return the client network used for quotas: the IPv4 address or the IPv6 /64."""
    address = request.client.host if request.client else "unknown"
    if os.getenv("VERCEL"):
        # Vercel overwrites this header at the edge; it is not client-controlled there.
        address = request.headers.get("x-vercel-forwarded-for", address).split(",")[0].strip()
    return quota_network(address)


def quota_network(address: str) -> str:
    try:
        ip = ipaddress.ip_address(address.strip().strip("[]").split("%", 1)[0])
    except ValueError:
        return address[:64]
    if ip.version == 6 and ip.ipv4_mapped:
        return str(ip.ipv4_mapped)
    if ip.version == 6:
        return str(ipaddress.ip_network(f"{ip}/{IPV6_PREFIX}", strict=False))
    return str(ip)
