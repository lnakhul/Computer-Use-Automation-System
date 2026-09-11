"""Playwright implementation of the generic computer surface contract."""

from __future__ import annotations

import uuid
import json
import re
import time
from functools import wraps
from pathlib import Path

from playwright.sync_api import Locator, Page, Error as PlaywrightError, TimeoutError as PlaywrightTimeoutError

from automation.capabilities.models import (
    AttributeLocator,
    CssLocator,
    ElementTarget,
    LabelLocator,
    LocatorKind,
    RoleLocator,
    TextLocator,
    CheckpointCondition,
    ElementVisibleCondition,
    TextContainsCondition,
    UrlMatchesCondition,
)
from automation.surface.contracts import (
    LiveInteractiveSession,
    HumanSurfaceAction,
    HumanSurfaceActionType,
    ResolvedSurfaceTarget,
    SurfaceObservation,
)
from automation.surface.errors import SessionControlError, TargetResolutionError, SurfaceAdapterError, SurfaceTimeoutError, AmbiguousTargetError


def surface_operation(method):
    @wraps(method)
    def wrapped(*args, **kwargs):
        try:
            return method(*args, **kwargs)
        except PlaywrightTimeoutError as error:
            raise SurfaceTimeoutError("browser operation timed out") from error
        except PlaywrightError as error:
            raise SurfaceAdapterError("browser operation failed") from error
    return wrapped


class PlaywrightBrowserSurfaceAdapter:
    """Adapts a live Playwright page to surface-independent operations."""

    def __init__(self, page: Page, surface_identifier: str = "playwright-browser") -> None:
        self._page = page
        self._surface_identifier = surface_identifier
        self._session_id = str(uuid.uuid4())
        self._control_owner = "automation"
        self._network_guard = None
        self.last_resolution: ResolvedSurfaceTarget | None = None

    @surface_operation
    def observe(self) -> SurfaceObservation:
        self._require_automation_control()
        dialog_text = None
        visible_dialogs = self._page.locator('[role="dialog"]:visible')
        if visible_dialogs.count() > 0:
            dialog_text = visible_dialogs.first.inner_text()
        return SurfaceObservation(
            surface_identifier=self._surface_identifier,
            current_location=self._page.url,
            title=self._page.title(),
            visible_text=self._page.locator("body").inner_text(),
            dialog_text=dialog_text,
            controls=tuple(self._page.locator("input,button,a,select,[aria-label]").evaluate_all("elements => elements.slice(0,50).map(e => ({tag:e.tagName, role:e.getAttribute('role'), label:e.getAttribute('aria-label') || (e.labels && Array.from(e.labels).map(l=>l.innerText).join(' ')), text:(e.innerText || '').slice(0,100)}))")),
        )

    @surface_operation
    def navigate(self, destination: str) -> None:
        self._require_automation_control()
        self._page.goto(destination, wait_until="domcontentloaded")

    @surface_operation
    def resolve_recorded_target(self, target: ElementTarget) -> ResolvedSurfaceTarget:
        self._require_automation_control()
        return self._resolve_locator(target).metadata

    @surface_operation
    def click(self, target: ElementTarget) -> ResolvedSurfaceTarget:
        self._require_automation_control()
        resolution = self._resolve_locator(target)
        resolution.locator.click()
        return resolution.metadata

    @surface_operation
    def enter_text(self, target: ElementTarget, text: str) -> ResolvedSurfaceTarget:
        self._require_automation_control()
        resolution = self._resolve_locator(target)
        resolution.locator.fill(text)
        return resolution.metadata

    @surface_operation
    def read_text_or_value(self, target: ElementTarget) -> str:
        self._require_automation_control()
        resolution = self._resolve_locator(target)
        self.last_resolution = resolution.metadata
        if resolution.locator.evaluate("element => element instanceof HTMLInputElement || element instanceof HTMLTextAreaElement"):
            return resolution.locator.input_value()
        return resolution.locator.inner_text()

    @surface_operation
    def wait_for_state(self, condition: CheckpointCondition, timeout_seconds: float) -> None:
        self._require_automation_control()
        deadline = time.monotonic() + timeout_seconds
        while True:
            try:
                if isinstance(condition, UrlMatchesCondition):
                    matched = re.search(condition.pattern, self._page.url) is not None
                elif isinstance(condition, (ElementVisibleCondition, TextContainsCondition)):
                    locator = self._resolve_locator(condition.target).locator
                    matched = locator.is_visible()
                    if matched and isinstance(condition, TextContainsCondition):
                        matched = condition.expected_text in locator.inner_text(timeout=max(1, int((deadline - time.monotonic()) * 1000)))
                else:
                    raise SurfaceAdapterError("unsupported surface wait condition")
                if matched:
                    return
            except TargetResolutionError:
                pass
            if time.monotonic() >= deadline:
                raise SurfaceTimeoutError("declared state wait timed out")
            self._page.wait_for_timeout(min(50, max(1, int((deadline - time.monotonic()) * 1000))))

    @surface_operation
    def capture_evidence(self, destination: Path) -> Path:
        if self._control_owner not in {"automation", "human"}:
            raise SessionControlError("live session has no valid owner")
        destination.parent.mkdir(parents=True, exist_ok=True)
        # Fail-closed screenshot redaction: mask the entire content viewport.
        # Safe structural evidence provides diagnostics without page text or values.
        self._page.screenshot(path=str(destination), full_page=True, mask=[self._page.locator("html")])
        structure = self._page.locator("body").evaluate("element => ({tag: element.tagName, controls: Array.from(element.querySelectorAll('input,button,a,select')).map(e => ({tag:e.tagName,type:e.getAttribute('type')}))})")
        destination.with_suffix(".structure.json").write_text(json.dumps(structure), encoding="utf-8")
        return destination

    def expose_live_session(self) -> LiveInteractiveSession:
        if self._control_owner != "automation":
            raise SessionControlError("live session is already owned by a human")
        self._control_owner = "human"
        return self._session_handle()

    def resume_live_session(self, session_id: str) -> LiveInteractiveSession:
        if session_id != self._session_id:
            raise SessionControlError("session ID does not identify this live session")
        if self._control_owner != "human":
            raise SessionControlError("live session is not currently owned by a human")
        self._control_owner = "automation"
        return self._session_handle()

    @surface_operation
    def perform_human_action(self, action: HumanSurfaceAction) -> str | ResolvedSurfaceTarget | None:
        self._require_human_control()
        if action.action_type is HumanSurfaceActionType.NAVIGATE:
            if action.destination is None:
                raise SessionControlError("human navigation requires a destination")
            self._page.goto(action.destination, wait_until="domcontentloaded")
            return None
        if action.target is None:
            raise SessionControlError("human target action requires a target")
        resolution = self._resolve_locator_without_ownership_check(action.target)
        if action.action_type is HumanSurfaceActionType.CLICK:
            resolution.locator.click()
            return resolution.metadata
        if action.action_type is HumanSurfaceActionType.ENTER_TEXT:
            if action.value is None:
                raise SessionControlError("human text entry requires a value")
            resolution.locator.fill(action.value)
            return resolution.metadata
        raise SessionControlError(f"unsupported human action: {action.action_type.value}")

    def configure_request_guard(self, allowed):
        """Install the host policy before requests, including redirects and frames."""
        if self._network_guard is not None:
            return
        def guard(route):
            request = route.request
            if allowed(request.url, request.method):
                route.continue_()
            else:
                route.abort("blockedbyclient")
        self._network_guard = guard
        self._page.context.route("**/*", guard)

    def _session_handle(self) -> LiveInteractiveSession:
        return LiveInteractiveSession(
            session_id=self._session_id,
            current_location=self._page.url,
            control_owner=self._control_owner,
        )

    def _require_automation_control(self) -> None:
        if self._control_owner != "automation":
            raise SessionControlError("automation does not own the live session")

    def _require_human_control(self) -> None:
        if self._control_owner != "human":
            raise SessionControlError("human does not own the live session")

    def _resolve_locator(self, target: ElementTarget) -> _ResolvedLocator:
        self._require_automation_control()
        return self._resolve_locator_without_ownership_check(target)

    def _resolve_locator_without_ownership_check(self, target: ElementTarget) -> _ResolvedLocator:
        for candidate in target.candidates:
            locator = self._locator_for_strategy(candidate.strategy)
            count = locator.count()
            if count > 1:
                raise AmbiguousTargetError("recorded target matches multiple controls")
            if count == 1:
                return _ResolvedLocator(
                    locator=locator,
                    metadata=ResolvedSurfaceTarget(
                        target_description=target.description,
                        selected_priority=candidate.priority,
                        strategy_kind=candidate.strategy.kind.value,
                    ),
                )
        raise TargetResolutionError(f"could not resolve target: {target.description}")

    def _locator_for_strategy(self, strategy: object) -> Locator:
        if isinstance(strategy, RoleLocator):
            return self._page.get_by_role(strategy.role.value, name=strategy.accessible_name, exact=True)
        if isinstance(strategy, LabelLocator):
            label_locator = self._page.get_by_label(strategy.label, exact=True)
            if label_locator.count() > 0:
                return label_locator
            return self._page.locator(f'[aria-label={json.dumps(strategy.label)}]' )
        if isinstance(strategy, TextLocator):
            return self._page.get_by_text(strategy.text, exact=strategy.exact)
        if isinstance(strategy, AttributeLocator):
            return self._page.locator(f'[{strategy.attribute_name}={json.dumps(strategy.attribute_value)}]' )
        if isinstance(strategy, CssLocator):
            return self._page.locator(strategy.selector)
        raise TargetResolutionError(f"unsupported locator kind: {getattr(strategy, 'kind', None)}")


class _ResolvedLocator:
    def __init__(self, locator: Locator, metadata: ResolvedSurfaceTarget) -> None:
        self.locator = locator
        self.metadata = metadata