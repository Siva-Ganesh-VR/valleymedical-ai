.PHONY: install test api ui up down

install:
	cd backend && pip install -r requirements-dev.txt
	cd frontend && npm install

test:
	cd backend && python -m pytest

api:
	cd backend && uvicorn app.main:create_app --factory --reload --port 8000

ui:
	cd frontend && npm run dev

up:
	docker compose up --build

down:
	docker compose down
