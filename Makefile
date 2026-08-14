.PHONY: install backend frontend dev test

install:
	uv sync --group main --group dev
	cd webapp && npm install

backend:
	uv run uvicorn core.api:app --app-dir src --reload

frontend:
	cd webapp && npm run dev

# Runs both, forwarding Ctrl-C to kill the other.
dev:
	@trap 'kill 0' EXIT INT TERM; \
	$(MAKE) backend & \
	$(MAKE) frontend & \
	wait

test:
	uv run pytest
	cd webapp && npm test
