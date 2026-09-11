"""Playwright implementation of the generic computer surface contract."""

from __future__ import annotations

import uuid
from pathlib import Path

from playwright.sync_api import Locator, Page

from automation.capabilities.models import (
    AttributeLocator,
    CssLocator,
    ElementTarget,
    LabelLocator,
    LocatorKind,
    RoleLocator,
    TextLocator,
)
from automation.surface.contracts import (
    LiveInteractiveSession,
    ResolvedSurfaceTarget,
    SurfaceObservation,
)
from automation.surface.errors import SessionControlError, TargetResolutionError


class PlaywrightBrowserSurfaceAdapter:
    """Adapts a live Playwright page to surface-independent operations."""

    def __init__(self, page: Page, surface_identifier: str = "playwright-browser") -> None:
        self._page = page
        self._surface_identifier = surface_identifier
        self._session_id = str(uuid.uuid4())
        self._control_owner = "automation"

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
        )

    def navigate(self, destination: str) -> None:
        self._require_automation_control()
        self._page.goto(destination, wait_until="domcontentloaded")

    def resolve_recorded_target(self, target: ElementTarget) -> ResolvedSurfaceTarget:
        self._require_automation_control()
        for candidate in target.candidates:
            locator = self._locator_for_strategy(candidate.strategy)
            if locator.count() == 1:
                return ResolvedSurfaceTarget(
                    target_description=target.description,
                    selected_priority=candidate.priority,
                    strategy_kind=candidate.strategy.kind.value,
                )
        raise TargetResolutionError(f"could not resolve target: {target.description}")

    def click(self, target: ElementTarget) -> ResolvedSurfaceTarget:
        self._require_automation_control()
        resolution = self._resolve_locator(target)
        resolution.locator.click()
        return resolution.metadata

    def enter_text(self, target: ElementTarget, text: str) -> ResolvedSurfaceTarget:
        self._require_automation_control()
        resolution = self._resolve_locator(target)
        resolution.locator.fill(text)
        return resolution.metadata

    def read_text_or_value(self, target: ElementTarget) -> str:
        self._require_automation_control()
        resolution = self._resolve_locator(target)
        if resolution.locator.evaluate("element => element instanceof HTMLInputElement || element instanceof HTMLTextAreaElement"):
            return resolution.locator.input_value()
        return resolution.locator.inner_text()

    def capture_evidence(self, destination: Path) -> Path:
        self._require_automation_control()
        destination.parent.mkdir(parents=True, exist_ok=True)
        self._page.screenshot(path=str(destination), full_page=True)
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

    def _session_handle(self) -> LiveInteractiveSession:
        return LiveInteractiveSession(
            session_id=self._session_id,
            current_location=self._page.url,
            control_owner=self._control_owner,
        )

    def _require_automation_control(self) -> None:
        if self._control_owner != "automation":
            raise SessionControlError("automation does not own the live session")

    def _resolve_locator(self, target: ElementTarget) -> _ResolvedLocator:
        for candidate in target.candidates:
            locator = self._locator_for_strategy(candidate.strategy)
            if locator.count() == 1:
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
            if label_locator.count() == 1:
                return label_locator
            return self._page.locator(f'[aria-label="{strategy.label}"]')
        if isinstance(strategy, TextLocator):
            return self._page.get_by_text(strategy.text, exact=strategy.exact)
        if isinstance(strategy, AttributeLocator):
            return self._page.locator(f'[{strategy.attribute_name}="{strategy.attribute_value}"]')
        if isinstance(strategy, CssLocator):
            return self._page.locator(strategy.selector)
        raise TargetResolutionError(f"unsupported locator kind: {getattr(strategy, 'kind', None)}")


class _ResolvedLocator:
    def __init__(self, locator: Locator, metadata: ResolvedSurfaceTarget) -> None:
        self.locator = locator
        self.metadata = metadata