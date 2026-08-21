.PHONY: help install install-backend install-frontend dev run build test lint typecheck check demo clean

help:
	@echo "make install    Instala backend, frontend y el navegador de Playwright"
	@echo "make run        Arranca AW1 en http://127.0.0.1:8000"
	@echo "make dev        Backend + frontend con recarga en caliente (2 procesos)"
	@echo "make build      Compila la interfaz"
	@echo "make check      lint + typecheck + tests (lo mismo que CI)"
	@echo "make demo       Levanta la tienda de prueba en el puerto 9100"

install: install-backend install-frontend

install-backend:
	cd backend && python -m pip install -U pip && python -m pip install -e ".[dev]"
	cd backend && python -m playwright install chromium

install-frontend:
	cd frontend && npm install

build:
	cd frontend && npm run build

run: build
	cd backend && python -m aw1

dev:
	@echo "Terminal 1: cd backend && python -m aw1"
	@echo "Terminal 2: cd frontend && npm run dev   ->  http://127.0.0.1:5173"

test:
	cd backend && python -m pytest

lint:
	cd backend && python -m ruff check .
	cd frontend && npm run lint

typecheck:
	cd backend && python -m mypy

check: lint typecheck test

demo:
	python scripts/demo_store.py 9100

clean:
	rm -rf backend/.pytest_cache backend/.mypy_cache backend/.ruff_cache frontend/dist
	find . -name __pycache__ -type d -prune -exec rm -rf {} +
