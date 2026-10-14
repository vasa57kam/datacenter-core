import argparse
import asyncio
import json
from types import SimpleNamespace

from sqlalchemy import select

from app.adapters.vpn.threexui import ThreeXuiAdapter
from app.core import security
from app.db import SessionLocal
from app.models import VpnAccount, VpnNode


def sync_account(account_id: int) -> None:
    db = SessionLocal()
    try:
        account = db.get(VpnAccount, account_id)
        if not account:
            print(f"Account {account_id} not found")
            return
        
        node = db.get(VpnNode, account.node_id)
        if not node:
            print(f"Node {account.node_id} not found")
            return
        
        # Создаём временный адаптер
        tmp = SimpleNamespace(
            id=node.id,
            api_url=node.api_url,
            api_user=node.api_user,
            api_key_enc=node.api_key_enc,
            extra=node.extra or {},
        )
        adapter = ThreeXuiAdapter(tmp)
        
        # Получаем клиента из панели
        client = asyncio.run(adapter._get_client(account.username))
        if not client:
            print(f"Client {account.username} not found in panel")
            return
        
        # Обновляем UUID в БД
        panel_uuid = client.get("uuid") or client.get("id")
        if panel_uuid and panel_uuid != account.uuid:
            print(f"Updating UUID: {account.uuid} -> {panel_uuid}")
            account.uuid = panel_uuid
            db.commit()
        else:
            print(f"UUID matches: {account.uuid}")
        
        # Показываем параметры для ссылки
        rs = (node.extra or {}).get("reality_settings") or {}
        print(f"\nLink parameters:")
        print(f"  Host: {node.endpoint_host}:{node.endpoint_port}")
        print(f"  UUID: {account.uuid}")
        print(f"  SNI: {rs.get('sni', 'N/A')}")
        print(f"  PublicKey: {rs.get('pbk', 'N/A')}")
        print(f"  ShortId: {rs.get('sid', 'N/A')}")
        print(f"  Fingerprint: {rs.get('fp', 'N/A')}")
        print(f"  SpiderX: {rs.get('spx', 'N/A')}")
        
    finally:
        db.close()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--account-id", type=int, required=True, help="VPN account ID")
    a = ap.parse_args()
    sync_account(a.account_id)


if __name__ == "__main__":
    main()
