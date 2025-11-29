from __future__ import annotations

import os
import pathlib
import shutil
import subprocess

import pytest
import sio

JS_DIR = pathlib.Path(__file__).parent.parent / "js_client"


@pytest.fixture(scope="session")
def ensure_js_deps():
    if shutil.which("npm") is None:
        pytest.skip("npm (Node.js) is not available")

    node_modules = JS_DIR / "node_modules"
    if not node_modules.exists():
        subprocess.run(
            ["npm", "i"],
            cwd=JS_DIR,
            check=True,
        )
    return JS_DIR


@pytest.mark.skipif(
    shutil.which("npm") is None,
    reason="npm (Node.js) is not available",
)
@pytest.mark.js_client
@pytest.mark.django_db(transaction=True)
def test_js_socketio_client_integration(live_server_url: str, ensure_js_deps):
    env = os.environ.copy()
    env["DJANGO_SIO_BASE_URL"] = live_server_url

    cmd = ["npm", "test"]


    js_args = []

    if os.environ.get("JS_BAIL") == "1":
        js_args.append("--bail")

    js_grep = os.environ.get("JS_GREP")
    if js_grep:
        js_args.extend(["--grep", js_grep])

    if js_args:
        cmd.extend(["--", *js_args])

    completed = subprocess.run(
        cmd,
        cwd=ensure_js_deps,
        env=env,
        text=True,
    )

    assert completed.returncode == 0, "`npm test` failed"
