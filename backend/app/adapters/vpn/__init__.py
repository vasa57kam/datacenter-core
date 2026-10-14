"""VPN adapter factory. Lazy imports to avoid circular dependencies."""
from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.models import VpnNode


def get_adapter(node: "VpnNode"):
    """Return the appropriate VPN adapter for the given node."""
    kind = (node.api_kind or "").lower()
    if kind == "3xui":
        from app.adapters.vpn.threexui import ThreeXuiAdapter
        return ThreeXuiAdapter(node)
    if kind in ("wireguard", "wg"):
        from app.adapters.vpn.wireguard_ssh import WireGuardSshAdapter
        return WireGuardSshAdapter(node)
    raise ValueError(f"Unknown api_kind: {kind!r}")
