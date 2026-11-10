.PHONY: lint test coverage

lint:
	python -m pylint check_gitlab_version.py test_check_gitlab_version.py

test:
	python -m unittest -v test_check_gitlab_version.py

coverage:
	python -m coverage run -m unittest -b test_check_gitlab_version.py
	python -m coverage report -m --include check_gitlab_version.py --fail-under 100
