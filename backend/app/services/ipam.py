import ipaddress

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import VpnAccount, VpnNode


def _norm(value) -> str:
    # INET может прийти как str, IPv4Address или IPv4Interface ('10.8.0.2/32')
    return str(ipaddress.ip_interface(str(value)).ip)


def allocate_ip(db: Session, node: VpnNode) -> str:
    if not node.subnet_cidr:
        raise RuntimeError(f"node {node.code} has no subnet_cidr")
    net = ipaddress.ip_network(node.subnet_cidr)

    # Сериализуем выдачу адресов на ноде до конца транзакции.
    db.execute(select(VpnNode.id).where(VpnNode.id == node.id).with_for_update())

    used = {
        _norm(ip)
        for ip in db.execute(
            select(VpnAccount.ip_address).where(
                VpnAccount.node_id == node.id, VpnAccount.ip_address.is_not(None)
            )
        ).scalars()
    }
    # Первый хост подсети (.1) зарезервирован под сервер WireGuard.
    for i, host in enumerate(net.hosts()):
        if i == 0:
            continue
        if str(host) not in used:
            return str(host)
    raise RuntimeError(f"no free ip in {node.subnet_cidr}")
