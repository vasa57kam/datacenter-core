.PHONY: build up down logs init admin seed backup

build:
	docker compose build

up:
	docker compose up -d

down:
	docker compose down

logs:
	docker compose logs -f --tail=100

init:
	docker compose run --rm api python scripts/init_db.py

admin:
	docker compose run --rm api python scripts/create_admin.py --email $(ADMIN_EMAIL) --password $(ADMIN_PASSWORD)

seed:
	docker compose run --rm api python scripts/seed_products.py

backup:
	docker compose exec -T db pg_dump -U billing billing > backup-$$(date +%F-%H%M).sql