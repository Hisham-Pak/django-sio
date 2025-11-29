from channels.testing import ChannelsLiveServerTestCase
import pytest


@pytest.fixture(scope="session")
def live_server_url(django_db_setup, django_db_blocker) -> str:
    """
    Start the Channels live server once per test session and return its base
    URL (e.g. 'http://127.0.0.1:8001').
    """

    class _Server(ChannelsLiveServerTestCase):
        serve_static = True

    # Set up the ASGI server
    with django_db_blocker.unblock():
        _Server.setUpClass()
    try:
        # Create a dummy instance to access the *instance* property
        server_instance = _Server(methodName="runTest")
        url = server_instance.live_server_url  # this is now a real string
        yield url
    finally:
        with django_db_blocker.unblock():
            _Server.tearDownClass()


def pytest_addoption(parser):
    parser.addoption(
        "--run-js",
        action="store_true",
        default=False,
        help="Run JS socket.io client integration tests",
    )


def pytest_configure(config):
    # So pytest -q shows the marker nicely
    config.addinivalue_line(
        "markers",
        "js_client: mark tests that run the Node.js/socket.io-client suite",
    )


def pytest_collection_modifyitems(config, items):
    if config.getoption("--run-js"):
        # User explicitly asked to run JS tests: don't skip anything.
        return

    skip_js = pytest.mark.skip(reason="use --run-js to run JS client tests")
    for item in items:
        if "js_client" in item.keywords:
            item.add_marker(skip_js)
