# One-command safety net: lint + format + types + full test suite.
# Run `make check` before committing / declaring work done.

.PHONY: check lint format types test precommit

check: lint format types test
	@echo "========================================="
	@echo " make check: ALL GREEN - safe to commit"
	@echo "========================================="

lint:
	ruff check . --fix

format:
	ruff format .

types:
	mypy --config-file=mypy.ini --exclude=scripts/ .

test:
	pytest -q

# Mirror what CI/pre-commit runs across the WHOLE repo (not just staged files).
precommit:
	pre-commit run --all-files
