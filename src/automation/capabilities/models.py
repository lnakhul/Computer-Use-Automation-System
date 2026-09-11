"""Pydantic contracts for recorded, replayable capabilities.

These models describe intent and expected state. They intentionally contain no
browser- or desktop-automation implementation details.
"""

from __future__ import annotations

from decimal import Decimal
from enum import StrEnum
from typing import Annotated, Literal, Union

from pydantic import BaseModel, ConfigDict, Field, PositiveInt, model_validator


class ContractModel(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class ArtifactSchemaVersion(StrEnum):
    V1 = "1.0"


class SurfaceKind(StrEnum):
    WEB = "web"


class ActionRisk(StrEnum):
    READ_ONLY = "read_only"
    REVERSIBLE = "reversible"
    IRREVERSIBLE = "irreversible"


class RiskyActionPolicy(StrEnum):
    BLOCK = "block"
    REQUIRE_HUMAN_CONFIRMATION = "require_human_confirmation"


class ActionType(StrEnum):
    NAVIGATE = "navigate"
    CLICK = "click"
    FILL = "fill"
    WAIT_FOR_STATE = "wait_for_state"
    EXTRACT_TEXT = "extract_text"


class ParameterType(StrEnum):
    STRING = "string"
    INTEGER = "integer"
    DECIMAL = "decimal"
    BOOLEAN = "boolean"


class OutputType(StrEnum):
    STRING = "string"
    INTEGER = "integer"
    DECIMAL = "decimal"
    BOOLEAN = "boolean"


class LocatorKind(StrEnum):
    ROLE = "role"
    LABEL = "label"
    TEXT = "text"
    ATTRIBUTE = "attribute"
    CSS = "css"


class CheckpointConditionType(StrEnum):
    ELEMENT_VISIBLE = "element_visible"
    TEXT_CONTAINS = "text_contains"
    URL_MATCHES = "url_matches"
    EXTRACTED_VALUE_MATCHES = "extracted_value_matches"


class LocatorRole(StrEnum):
    BUTTON = "button"
    CELL = "cell"
    COMBOBOX = "combobox"
    HEADING = "heading"
    LINK = "link"
    TEXTBOX = "textbox"


class RoleLocator(ContractModel):
    kind: Literal[LocatorKind.ROLE] = LocatorKind.ROLE
    role: LocatorRole
    accessible_name: str = Field(min_length=1)


class LabelLocator(ContractModel):
    kind: Literal[LocatorKind.LABEL] = LocatorKind.LABEL
    label: str = Field(min_length=1)


class TextLocator(ContractModel):
    kind: Literal[LocatorKind.TEXT] = LocatorKind.TEXT
    text: str = Field(min_length=1)
    exact: bool = True


class AttributeLocator(ContractModel):
    kind: Literal[LocatorKind.ATTRIBUTE] = LocatorKind.ATTRIBUTE
    attribute_name: str = Field(min_length=1)
    attribute_value: str = Field(min_length=1)


class CssLocator(ContractModel):
    kind: Literal[LocatorKind.CSS] = LocatorKind.CSS
    selector: str = Field(min_length=1)


LocatorStrategy = Annotated[
    Union[RoleLocator, LabelLocator, TextLocator, AttributeLocator, CssLocator],
    Field(discriminator="kind"),
]


class LocatorCandidate(ContractModel):
    priority: PositiveInt
    strategy: LocatorStrategy


class ElementTarget(ContractModel):
    description: str = Field(min_length=1)
    candidates: list[LocatorCandidate] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_candidate_priorities(self) -> ElementTarget:
        priorities = [candidate.priority for candidate in self.candidates]
        if priorities != sorted(priorities) or len(set(priorities)) != len(priorities):
            raise ValueError("locator candidate priorities must be unique and ascending")
        return self


class StringParameter(ContractModel):
    value_type: Literal[ParameterType.STRING] = ParameterType.STRING
    name: str = Field(min_length=1)
    description: str = Field(min_length=1)
    required: bool = True
    sensitive: bool = False
    pattern: str | None = None
    default: str | None = None

    @model_validator(mode="after")
    def reject_sensitive_default(self) -> StringParameter:
        if self.sensitive and self.default is not None:
            raise ValueError("sensitive parameters cannot persist default values")
        return self


class IntegerParameter(ContractModel):
    value_type: Literal[ParameterType.INTEGER] = ParameterType.INTEGER
    name: str = Field(min_length=1)
    description: str = Field(min_length=1)
    required: bool = True
    sensitive: bool = False
    minimum: int | None = None
    maximum: int | None = None
    default: int | None = None

    @model_validator(mode="after")
    def reject_sensitive_default(self) -> IntegerParameter:
        if self.sensitive and self.default is not None:
            raise ValueError("sensitive parameters cannot persist default values")
        return self


class DecimalParameter(ContractModel):
    value_type: Literal[ParameterType.DECIMAL] = ParameterType.DECIMAL
    name: str = Field(min_length=1)
    description: str = Field(min_length=1)
    required: bool = True
    sensitive: bool = False
    minimum: Decimal | None = None
    maximum: Decimal | None = None
    default: Decimal | None = None

    @model_validator(mode="after")
    def reject_sensitive_default(self) -> DecimalParameter:
        if self.sensitive and self.default is not None:
            raise ValueError("sensitive parameters cannot persist default values")
        return self


class BooleanParameter(ContractModel):
    value_type: Literal[ParameterType.BOOLEAN] = ParameterType.BOOLEAN
    name: str = Field(min_length=1)
    description: str = Field(min_length=1)
    required: bool = True
    sensitive: bool = False
    default: bool | None = None

    @model_validator(mode="after")
    def reject_sensitive_default(self) -> BooleanParameter:
        if self.sensitive and self.default is not None:
            raise ValueError("sensitive parameters cannot persist default values")
        return self


InputParameter = Annotated[
    Union[StringParameter, IntegerParameter, DecimalParameter, BooleanParameter],
    Field(discriminator="value_type"),
]


class OutputDeclaration(ContractModel):
    name: str = Field(min_length=1)
    description: str = Field(min_length=1)
    output_type: OutputType
    source_action_id: str = Field(min_length=1)
    parser: Literal["raw_text", "integer", "decimal", "currency", "boolean"]
    required: bool = True
    sensitive: bool = False


class ElementVisibleCondition(ContractModel):
    condition_type: Literal[CheckpointConditionType.ELEMENT_VISIBLE] = CheckpointConditionType.ELEMENT_VISIBLE
    target: ElementTarget


class TextContainsCondition(ContractModel):
    condition_type: Literal[CheckpointConditionType.TEXT_CONTAINS] = CheckpointConditionType.TEXT_CONTAINS
    target: ElementTarget
    expected_text: str = Field(min_length=1)


class UrlMatchesCondition(ContractModel):
    condition_type: Literal[CheckpointConditionType.URL_MATCHES] = CheckpointConditionType.URL_MATCHES
    pattern: str = Field(min_length=1)


class ExtractedValueMatchesCondition(ContractModel):
    condition_type: Literal[CheckpointConditionType.EXTRACTED_VALUE_MATCHES] = CheckpointConditionType.EXTRACTED_VALUE_MATCHES
    output_name: str = Field(min_length=1)
    pattern: str = Field(min_length=1)


CheckpointCondition = Annotated[
    Union[
        ElementVisibleCondition,
        TextContainsCondition,
        UrlMatchesCondition,
        ExtractedValueMatchesCondition,
    ],
    Field(discriminator="condition_type"),
]


class NavigateAction(ContractModel):
    action_type: Literal[ActionType.NAVIGATE] = ActionType.NAVIGATE
    action_id: str = Field(min_length=1)
    description: str = Field(min_length=1)
    risk: ActionRisk = ActionRisk.READ_ONLY
    route: str = Field(min_length=1)
    postconditions: list[CheckpointCondition] = Field(default_factory=list)


class ClickAction(ContractModel):
    action_type: Literal[ActionType.CLICK] = ActionType.CLICK
    action_id: str = Field(min_length=1)
    description: str = Field(min_length=1)
    risk: ActionRisk = ActionRisk.READ_ONLY
    target: ElementTarget
    postconditions: list[CheckpointCondition] = Field(default_factory=list)


class FillAction(ContractModel):
    action_type: Literal[ActionType.FILL] = ActionType.FILL
    action_id: str = Field(min_length=1)
    description: str = Field(min_length=1)
    risk: ActionRisk = ActionRisk.REVERSIBLE
    target: ElementTarget
    value_template: str = Field(min_length=1)
    sensitive_value: bool = False
    postconditions: list[CheckpointCondition] = Field(default_factory=list)

    @model_validator(mode="after")
    def require_symbolic_value_template(self) -> FillAction:
        if "${" not in self.value_template or "}" not in self.value_template:
            raise ValueError("fill values must be symbolic parameter templates")
        return self


class WaitForStateAction(ContractModel):
    action_type: Literal[ActionType.WAIT_FOR_STATE] = ActionType.WAIT_FOR_STATE
    action_id: str = Field(min_length=1)
    description: str = Field(min_length=1)
    risk: ActionRisk = ActionRisk.READ_ONLY
    condition: CheckpointCondition
    timeout_seconds: float = Field(gt=0, le=120)
    postconditions: list[CheckpointCondition] = Field(default_factory=list)


class ExtractTextAction(ContractModel):
    action_type: Literal[ActionType.EXTRACT_TEXT] = ActionType.EXTRACT_TEXT
    action_id: str = Field(min_length=1)
    description: str = Field(min_length=1)
    risk: ActionRisk = ActionRisk.READ_ONLY
    target: ElementTarget
    output_name: str = Field(min_length=1)
    postconditions: list[CheckpointCondition] = Field(default_factory=list)


Action = Annotated[
    Union[NavigateAction, ClickAction, FillAction, WaitForStateAction, ExtractTextAction],
    Field(discriminator="action_type"),
]


class BusinessOutcome(ContractModel):
    code: str = Field(min_length=1, pattern=r"^[A-Z][A-Z0-9_]*$")
    description: str = Field(min_length=1)
    detection: CheckpointCondition


class CompatibilityMetadata(ContractModel):
    surface_kind: SurfaceKind
    vendor_product: str = Field(min_length=1)
    vendor_version: str = Field(min_length=1)
    application_name: str = Field(min_length=1)
    application_version: str = Field(min_length=1)
    tenant_variant: str | None = None


class SafetyProfile(ContractModel):
    permitted_action_types: list[ActionType] = Field(min_length=1)
    maximum_risk: ActionRisk = ActionRisk.REVERSIBLE
    risky_action_policy: RiskyActionPolicy = RiskyActionPolicy.BLOCK

    @model_validator(mode="after")
    def validate_risky_action_policy(self) -> SafetyProfile:
        if self.maximum_risk is ActionRisk.IRREVERSIBLE and self.risky_action_policy is RiskyActionPolicy.BLOCK:
            raise ValueError("irreversible capabilities must declare confirmation or exclude irreversible risk")
        return self


class SuccessCheckpoint(ContractModel):
    description: str = Field(min_length=1)
    conditions: list[CheckpointCondition] = Field(min_length=1)


class CapabilityArtifact(ContractModel):
    artifact_schema_version: Literal[ArtifactSchemaVersion.V1] = ArtifactSchemaVersion.V1
    capability_id: str = Field(min_length=1, pattern=r"^[a-z0-9]+(?:[._-][a-z0-9]+)*$")
    revision: PositiveInt
    name: str = Field(min_length=1)
    description: str = Field(min_length=1)
    compatibility: CompatibilityMetadata
    entry_point: str = Field(min_length=1)
    inputs: list[InputParameter] = Field(default_factory=list)
    actions: list[Action] = Field(min_length=1)
    outputs: list[OutputDeclaration] = Field(default_factory=list)
    success_checkpoint: SuccessCheckpoint
    known_business_outcomes: list[BusinessOutcome] = Field(default_factory=list)
    safety_profile: SafetyProfile

    @model_validator(mode="after")
    def validate_action_references(self) -> CapabilityArtifact:
        action_ids = [action.action_id for action in self.actions]
        if len(action_ids) != len(set(action_ids)):
            raise ValueError("action_id values must be unique")

        output_action_ids = set(action_ids)
        invalid_sources = [
            output.source_action_id
            for output in self.outputs
            if output.source_action_id not in output_action_ids
        ]
        if invalid_sources:
            raise ValueError(f"outputs reference unknown actions: {invalid_sources}")

        declared_risks = {action.risk for action in self.actions}
        if ActionRisk.IRREVERSIBLE in declared_risks and self.safety_profile.risky_action_policy is RiskyActionPolicy.BLOCK:
            raise ValueError("artifact contains irreversible actions but its safety policy blocks them")
        return self