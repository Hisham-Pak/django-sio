[![PyPI version](https://badge.fury.io/py/django-sio.svg)](https://badge.fury.io/py/django-sio)
[![codecov](https://codecov.io/github/Hisham-Pak/django-sio/graph/badge.svg?token=4K0FFMWOS9)](https://codecov.io/github/Hisham-Pak/django-sio)
# Django SocketIO (`django-sio`)

Socket.IO for Django, powered by Channels and compatible with the official Socket.IO clients.

📖 Documentation: [django-sio.readthedocs.io](https://django-sio.readthedocs.io/)
🐍 PyPI: [pypi.org/project/django-sio/](https://pypi.org/project/django-sio/)
🚀 Demo project: [django-sio-chat-demo](https://github.com/hisham-pak/django-sio-chat-demo)

---
## Code Coverage

![Repository graph](https://codecov.io/github/Hisham-Pak/django-sio/graphs/icicle.svg?token=4K0FFMWOS9 "Repository graph")

## Development Setup

Clone the repository and install dependencies using [uv](https://github.com/astral-sh/uv):

```bash
# Install dependencies
uv sync

# Editable install
uv pip install -e .
```

### Building Documentation

This project uses sphinx.

```bash
uv run make html
```

See documentation in `build/` directory.

### Running Tests

Execute the test suite with:

```bash
uv run pytest -sq
uv run pytest -sq --durations=10  # To get 10 slowest tests
uv run pytest --cov=. --cov-report=html  # To generate code coverage report

# To run js_client tests make sure you do `npm install` before
uv run pytest -vv -s tests/js_client/test_js_client_integration.py --run-js
# To run js_client tests till first failure
JS_BAIL=1 \
  uv run pytest -vv -s tests/js_client/test_js_client_integration.py --run-js
# To run specific js_client tests. Alternatively use it.only() or to skip it.skip().
SIO_TRANSPORT=default JS_GREP="should forcefully close the session" \
  uv run pytest -vv -s tests/js_client/test_js_client_integration.py --run-js
```

### Running Linters and Formatters

```bash
uv run ruff format --check
uv run ruff format
uv run docformatter . --check
uv run docformatter --in-place .
uv run ruff check
npx eslint tests/js_client
npx eslint tests/js_client --fix
```

### Running with tox

Run the full tox matrix:

```bash
uv run tox
```

List the tox matrix:

```bash
$ uv run tox -l
... # past support
py39-dj42
py310-dj42
py311-dj42
py312-dj42
py310-dj51
py311-dj51
py312-dj51
py313-dj51
py310-dj52
py311-dj52
py312-dj52
py313-dj52
py314-dj52
py312-dj60
py313-dj60
py314-dj60
py312-djmain
py313-djmain
py314-djmain
... # future support
qa
qa-js

# run the tests with python 3.14, on Django 5.2 and main branch with linting or code quality assurance.
$ uv run tox -e py314-dj52,py314-djmain,qa
```

Note that tox can also forward arguments to pytest. For example, forward the -sq or --run-js flag to pytest as such:

```bash
uv run tox -e py314-djmain -- -sq --run-js
```

### Contributing

Contributions are welcome! Please open issues or pull requests to help improve the package.

## Release

To create a release:
```bash
git tag -a v1.0.0 -m "Release version 1.0.0"
git push origin v1.0.0
```

