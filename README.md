# datacenter-core

Ядро биллинга дата-центра: поминутное списание, VPN-менеджер (3x-ui VLESS Reality, WireGuard, OpenVPN-заглушка), задел под мост к CCTV Cloud.

## Принципы
- Деньги только в копейках (`bigint`), никаких float.
- Все списания через неизменяемый `ledger_entries` с `idempotency_key`.
- Биллинг — источник правды по деньгам и статусам; VPN-ноды только выполняют команды.
- VPN-секреты хранятся зашифрованными (Fernet).

## Быстрый старт
```bash
cp .env.example .env && chmod 600 .env   # заполнить секреты
make build
make init
make admin ADMIN_EMAIL=admin@itkam34.ru ADMIN_PASSWORD='StrongPass!'
make seed
make up
curl http://127.0.0.1:8008/healthz
```

## 3x-ui (Нидерланды)
1. `bash <(curl -Ls https://raw.githubusercontent.com/mhsanaei/3x-ui/master/install.sh)`
2. В панели создать inbound VLESS + Reality (tcp 443), запомнить его ID.
3. Взять из Reality-настроек: `serverNames[0]` (sni), `publicKey` (pbk), `shortIds[0]` (sid).
4. Добавить ноду через `POST /api/v1/admin/nodes`, в `extra` положить:
   `{"inbound_id": 1, "sni": "...", "pbk": "...", "sid": "...", "fp": "firefox"}`.

API 3x-ui, которые использует адаптер (если версия панели отличается — правь `app/adapters/vpn/threexui.py`):
- `POST /login`
- `POST /panel/api/inbounds/addClient`
- `GET  /panel/api/inbounds/get/{id}`
- `POST /panel/api/inbounds/updateClient/{uuid}`
- `POST /panel/api/inbounds/{id}/delClient/{uuid}`

## WireGuard-узел (Россия)
Нужен скрипт `/usr/local/sbin/wg-peer` (add/remove) и sudo для пользователя `wg-manager`
(см. план спринта). Ключ SSH биллинга добавляется в ноду через `POST /api/v1/admin/nodes`.

## Спринт 2 (не в этом MVP)
Order/AuditLog, платёжные провайдеры, Next.js фронт, админ-UI, полноценный OpenVPN, мост CCTV.