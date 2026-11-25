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

from playwright.sync_api import Page, expect, sync_playwright


def seed_archive() -> None:
    from datetime import UTC, datetime

    from app import event_intelligence
    from app import server  # noqa: F401 - register the archive tables before migration
    from app.launch_store import get_store
    from app.sources import BY_ID

    store = get_store()  # type: ignore[no-untyped-call]
    assert store is not None
    store.migrate()
    headline = "Sample cloud provider declares code red after service outage"
    for index, source_id in enumerate(("bbc-tech", "the-verge")):
        source = BY_ID[source_id]
        row = {
            "id": f"browser-smoke-{index}",
            "source_id": source.id,
            "source": source.group,
            "publisher": source.label,
            "kind": source.kind,
            "category": "Service Outages",
            "title": headline,
            "description": "A local test fixture reporting a cloud outage.",
            "url": f"https://{source.hosts[0]}/informa-browser-smoke",
            "published_at": datetime.now(UTC).isoformat(),
        }
        store.ingest(source.id, [row], True)
        event_intelligence.observe(store, row)  # type: ignore[no-untyped-call]


def exercise_mobile_reading(page: Page) -> None:
    page.set_viewport_size({"width": 390, "height": 844})
    page.reload(wait_until="domcontentloaded")
    start = page.get_by_role("link", name="What changed since your last visit?")
    start.click()
    heading = page.get_by_role("heading", name="Catch up", exact=True)
    expect(heading).to_be_focused()
    expect(heading).to_be_in_viewport()
    expect(page.locator("#home-catchup-results article h3").first).to_be_in_viewport()
    expect(page.locator(".mobile-reading-region")).to_be_visible()
    expect(page.locator(".signal-orb:visible")).to_have_count(0)
    assert page.evaluate(
        "document.documentElement.scrollWidth <= document.documentElement.clientWidth"
    )


def exercise_mobile_research(page: Page) -> None:
    page.set_viewport_size({"width": 390, "height": 844})
    question = page.get_by_role("textbox", name="Search or ask about technology news")
    submit = page.get_by_role("button", name="Find sources", exact=True)
    expect(
        page.get_by_role("heading", name="Research Desk", exact=True)
    ).to_be_visible()
    expect(question).to_be_in_viewport()
    expect(submit).to_be_in_viewport()
    question.fill("cloud service outage")
    submit.click()
    expect(page.locator("#research-results")).to_contain_text("Sample cloud provider")


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
                "-m",
                "scripts.check_release_browser",
                "--seed-archive",
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
                        expect(
                            page.get_by_role("link", name="Read Today’s Top 5")
                        ).to_be_visible()
                        topic = page.locator("#edition-interests").get_by_role(
                            "button", name="AI & Machine Learning"
                        )
                        topic.click()
                        expect(topic).to_have_attribute("aria-pressed", "true")
                        expect(
                            page.get_by_role("link", name="Updates you follow")
                        ).to_be_visible()
                        page.evaluate(
                            "localStorage.setItem('informa-catchup-checkpoint', String(Date.now() - 3600000))"
                        )
                        expect(page.locator("#edition-coverage")).to_contain_text(
                            "Compare 2 sources"
                        )
                        rail_copies = page.locator(
                            "#headlines-content, #signals-content"
                        ).get_by_text("Sample cloud provider")
                        expect(rail_copies).to_have_count(0)
                        exercise_mobile_reading(page)
                        page.get_by_role("button", name="Missing coverage?").click()
                        expect(
                            page.get_by_role("radio", name="Missing story or source")
                        ).to_be_checked()
                        page.get_by_role("button", name="Close feedback").click()
                        page.set_viewport_size({"width": 1280, "height": 720})
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
                        exercise_mobile_research(page)
                        assert not errors, errors
                    finally:
                        browser.close()
            finally:
                if server.poll() is None:
                    server.terminate()
                server.wait(timeout=10)
    print("Browser release smoke passed.")


if __name__ == "__main__":
    if sys.argv[1:] == ["--seed-archive"]:
        seed_archive()
    else:
        main()
