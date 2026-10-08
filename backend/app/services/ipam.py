import ipaddress

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import VpnAccount, VpnNode


def allocate_ip(db: Session, node: VpnNode) -> str:
    if not node.subnet_cidr:
        raise RuntimeError(f"node {node.code} has no subnet_cidr")
    net = ipaddress.ip_network(node.subnet_cidr)
    used = set(
        db.execute(
            select(VpnAccount.ip_address).where(VpnAccount.node_id == node.id)
        ).scalars()
    )
    for host in net.hosts():
        if str(host) not in used:
            return str(host)
    raise RuntimeError(f"no free ip in {node.subnet_cidr}")