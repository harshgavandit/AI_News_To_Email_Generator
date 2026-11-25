"""Run critical UI journeys against a credential-free local application."""

from __future__ import annotations

import os
import re
import socket
import subprocess
import sys
import sysconfig
import tempfile
import time
from pathlib import Path
from urllib.request import urlopen

from playwright.sync_api import expect, sync_playwright


def main() -> None:
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        port = listener.getsockname()[1]
    url = f"http://127.0.0.1:{port}"
    with tempfile.TemporaryDirectory() as directory:
        env = {
            "PATH": os.environ["PATH"],
            "SYSTEMROOT": os.environ.get("SYSTEMROOT", ""),
            "PYTHON_DOTENV_DISABLED": "1",
            "NEWS_DATABASE_URL": f"sqlite:///{Path(directory, 'smoke.db').as_posix()}",
        }
        # On Windows the venv launcher spawns another process that retains the SQLite handle.
        python = sys.executable
        if os.name == "nt":
            python = str(Path(sys.base_prefix, "python.exe"))
            env["PYTHONPATH"] = sysconfig.get_path("purelib")
        subprocess.run(
            [
                python,
                "-s",
                "-c",
                "from app.server import get_store; store = get_store(); "
                "store.ensure_discovery_schema(); store.ensure_curiosity_schema()",
            ],
            env=env,
            check=True,
        )
        with subprocess.Popen(
            [
                python,
                "-s",
                "-m",
                "uvicorn",
                "app.server:app",
                "--host",
                "127.0.0.1",
                "--port",
                str(port),
                "--no-access-log",
            ],
            env=env,
        ) as server:
            try:
                for _ in range(80):
                    if server.poll() is not None:
                        raise RuntimeError("FastAPI stopped before becoming ready")
                    try:
                        with urlopen(f"{url}/api/health", timeout=1) as response:
                            if response.status == 200:
                                break
                    except OSError:
                        time.sleep(0.25)
                else:
                    raise RuntimeError("FastAPI did not respond to the health probe")

                with sync_playwright() as playwright:
                    browser = playwright.chromium.launch(
                        channel=os.environ.get("INFORMA_TEST_BROWSER")
                    )
                    try:
                        page = browser.new_page(reduced_motion="reduce")
                        page.route(
                            "**/*",
                            lambda route: (
                                route.continue_()
                                if route.request.url.startswith(url + "/")
                                else route.abort()
                            ),
                        )
                        errors: list[str] = []
                        page.on("pageerror", lambda error: errors.append(str(error)))
                        page.goto(url, wait_until="domcontentloaded")
                        expect(page).to_have_title(re.compile("Informa AI"))
                        theme = page.get_by_role("combobox", name="Color theme")
                        theme.select_option("dark")
                        expect(page.locator("html")).to_have_attribute(
                            "data-theme", "dark"
                        )
                        page.get_by_role(
                            "button", name="Send feedback", exact=True
                        ).click()
                        expect(
                            page.get_by_role("dialog", name="Send feedback")
                        ).to_be_visible()
                        page.get_by_role("button", name="Close feedback").click()
                        page.get_by_role(
                            "link", name="Research Desk", exact=True
                        ).first.click()
                        expect(
                            page.get_by_role(
                                "textbox", name="Search or ask about technology news"
                            )
                        ).to_be_visible()
                        assert not errors, errors
                    finally:
                        browser.close()
            finally:
                if server.poll() is None:
                    server.terminate()
                server.wait(timeout=10)
    print("Browser release smoke passed.")


if __name__ == "__main__":
    main()
