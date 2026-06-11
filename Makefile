.PHONY: check check-backend check-frontend dev

check: check-backend check-frontend

check-backend:
	cd backend && uv run ruff check . && uv run pytest -q

check-frontend:
	cd frontend && npx tsc -b --noEmit && npx vitest run

dev:
	@trap 'kill 0' INT TERM; \
	(cd backend && uv run uvicorn notebook_forge.api:app --reload --port 8400) & \
	(cd frontend && npm run dev) & \
	wait
