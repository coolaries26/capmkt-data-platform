.PHONY: db-up db-down db-reset db-restart build health

db-up:
	docker compose up -d postgres

db-down:
	docker compose down

db-reset:
	docker compose down -v && docker compose up -d

db-restart:
	docker compose down && docker compose up -d postgres 

build:
	docker build -t capmkt:dev .

health:
	docker compose run --rm app healthcheck
