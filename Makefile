.PHONY: dev up down install lint format fix check

dev:
	SSL_CERT_FILE=certs/ca-bundle.pem REQUESTS_CA_BUNDLE=certs/ca-bundle.pem uv run uvicorn app.main:app --reload --port 8000

up:
	docker-compose up

dev-all:
	make dev && make up

down:
	docker-compose down

install:
	uv sync

lint:
	uv run ruff check .

format:
	uv run ruff format .

fix:
	uv run ruff check --fix .

check:
	uv run ruff format --check .
	uv run ruff check .
