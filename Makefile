.PHONY: dev build up down logs seed clean reset

dev: up

build:
	docker compose build

up:
	docker compose up -d --build

down:
	docker compose down

logs:
	docker compose logs -f

seed:
	docker compose exec api npm run seed

clean:
	docker compose down -v
	rm -rf node_modules packages/*/node_modules

reset: down clean up

ps:
	docker compose ps

test:
	docker compose exec api npm test
