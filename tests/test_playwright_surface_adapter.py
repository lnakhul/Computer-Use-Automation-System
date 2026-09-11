from threading import Thread
from pathlib import Path

import pytest
from werkzeug.serving import make_server

from automation.capabilities.models import ElementTarget
from automation.demo_app import create_demo_application
from automation.surface.errors import SessionControlError, TargetResolutionError
from automation.surface.playwright_adapter import PlaywrightBrowserSurfaceAdapter

playwright = pytest.importorskip("playwright.sync_api")


@pytest.fixture
def demo_server():
    server = make_server("127.0.0.1", 0, create_demo_application())
    server_thread = Thread(target=server.serve_forever, daemon=True)
    server_thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}"
    finally:
        server.shutdown()
        server_thread.join(timeout=2)


def member_id_target() -> ElementTarget:
    return ElementTarget(
        description="Member ID field",
        candidates=[
            {
                "priority": 1,
                "strategy": {"kind": "label", "label": "Member ID"},
            },
            {
                "priority": 2,
                "strategy": {
                    "kind": "attribute",
                    "attribute_name": "name",
                    "attribute_value": "member_id",
                },
            },
        ],
    )


def test_adapter_operates_on_demo_app_and_records_fallback_metadata(demo_server: str, tmp_path: Path) -> None:
    with playwright.sync_playwright() as browser_runtime:
        browser = browser_runtime.chromium.launch(channel="chrome")
        page = browser.new_page()
        adapter = PlaywrightBrowserSurfaceAdapter(page)

        adapter.navigate(f"{demo_server}/members/search")
        adapter.enter_text(member_id_target(), "12345")
        search_button = ElementTarget(
            description="Search button",
            candidates=[
                {
                    "priority": 1,
                    "strategy": {"kind": "role", "role": "button", "accessible_name": "Search"},
                }
            ],
        )
        adapter.click(search_button)
        page.wait_for_url("**/members/12345")

        balance_target = ElementTarget(
            description="Savings balance value",
            candidates=[
                {
                    "priority": 1,
                    "strategy": {"kind": "label", "label": "Savings balance"},
                }
            ],
        )
        assert adapter.read_text_or_value(balance_target) == "$1,240.50"
        observation = adapter.observe()
        assert observation.current_location.endswith("/members/12345")
        assert "Member Details" in observation.visible_text

        evidence_path = adapter.capture_evidence(tmp_path / "member-detail.png")
        assert evidence_path.exists()
        browser.close()


def test_adapter_requires_unique_target_resolution(demo_server: str) -> None:
    with playwright.sync_playwright() as browser_runtime:
        browser = browser_runtime.chromium.launch(channel="chrome")
        page = browser.new_page()
        adapter = PlaywrightBrowserSurfaceAdapter(page)
        adapter.navigate(f"{demo_server}/members/search")

        ambiguous_target = ElementTarget(
            description="Ambiguous text",
            candidates=[
                {
                    "priority": 1,
                    "strategy": {"kind": "text", "text": "Member", "exact": False},
                }
            ],
        )
        with pytest.raises(TargetResolutionError):
            adapter.resolve_recorded_target(ambiguous_target)
        browser.close()


def test_adapter_transfers_and_restores_same_live_session(demo_server: str) -> None:
    with playwright.sync_playwright() as browser_runtime:
        browser = browser_runtime.chromium.launch(channel="chrome")
        page = browser.new_page()
        adapter = PlaywrightBrowserSurfaceAdapter(page)
        adapter.navigate(f"{demo_server}/members/search")

        human_session = adapter.expose_live_session()
        assert human_session.control_owner == "human"
        with pytest.raises(SessionControlError):
            adapter.observe()

        resumed_session = adapter.resume_live_session(human_session.session_id)
        assert resumed_session.session_id == human_session.session_id
        assert resumed_session.control_owner == "automation"
        assert adapter.observe().current_location.endswith("/members/search")
        browser.close()