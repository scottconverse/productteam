.PHONY: build publish-test publish lint test

test:
	pytest tests/ -v

lint:
	ruff check src/ tests/

build:
	python -m build

publish-test:
	python -m twine upload --repository testpypi dist/*

publish:
	python -m twine upload dist/*
