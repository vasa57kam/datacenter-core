# datacenter-core

Ядро биллинга дата-центра: поминутное списание, VPN-менеджер (3x-ui VLESS Reality,
WireGuard SSH, OpenVPN-заглушка), мост к CCTV Cloud через internal API.

## Деплой одной командой
```bash
git clone https://github.com/vasa57kam/datacenter-core.git && cd datacenter-core
bash install.sh            # или: GIT_TOKEN=... bash install.sh для приватного репо
./install.sh update        # обновление
./install.sh backup        # ручной бэкап
./install.sh status        # статус
```

## Принципы
- Деньги только в копейках (bigint), никаких float.
- Все списания через неизменяемый ledger_entries с idempotency_key.
- Биллинг — источник правды; ноды и внешние системы только выполняют команды.
- VPN-секреты хранятся зашифрованными (Fernet).
- 3x-ui >= 3.8: логин с cookie-сессией + заголовок X-CSRF-Token (адаптер умеет).

## API
- /api/v1/* — клиенты и админ (JWT)
- /internal/v1/* — ноды и CCTV (X-Internal-Key)
- /docs — Swagger
