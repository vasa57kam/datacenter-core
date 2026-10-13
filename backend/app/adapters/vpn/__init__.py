from app.adapters.vpn.openvpn_stub import OpenVpnStubAdapter
from app.adapters.vpn.threexui import ThreeXuiAdapter
from app.adapters.vpn.wireguard_ssh import WireGuardSshAdapter


def get_adapter(node):
    if node.api_kind == "3xui":
        return ThreeXuiAdapter(node)
    if node.api_kind == "ssh_wireguard":
        return WireGuardSshAdapter(node)
    if node.api_kind == "openvpn_api":
        return OpenVpnStubAdapter(node)
    raise ValueError(f"unsupported api_kind: {node.api_kind}")


__all__ = ["get_adapter", "ThreeXuiAdapter", "WireGuardSshAdapter", "OpenVpnStubAdapter"]
