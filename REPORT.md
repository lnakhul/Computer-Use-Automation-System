# 1. Architecture

The implementation is a single-process Python package with logical module boundaries rather than separate services. The concrete surface is a local Flask application that presents a deliberately old-fashioned member-servicing UI: table-based details, conventional labels, no test IDs, validation errors, a not-found state, a simulated delay, and a simulated dialog. All data is synthetic.

The main components are:

- `capabilities`: Pydantic v2 models for versioned artifacts, typed inputs and outputs, ordered actions, target strategies, checkpoints, compatibility metadata, and safety profiles.
- `surface`: the `ComputerSurfaceAdapter` protocol and the Playwright implementation. Playwright types and locator mechanics stop at this boundary.
- `policy`: explicit target/action/risk policy models, a pure evaluator, and a policy-enforcing surface facade.
- `discovery`: the structured `AgentDecisionProvider`, OpenAI-compatible provider, bounded observe-decide-act runner, and artifact conversion.
- `replay`: the ordered, LLM-free artifact executor and typed execution results.
- `intervention`: same-session control ownership, human action execution, resume, and transfer records.
- `evidence`: recursive redaction and JSONL persistence.
- `cli`: evaluator-facing commands for the demo app, discovery, replay, exceptional replay, and handoff demonstration.

The design deliberately keeps the LLM out of replay. During discovery the provider returns one Pydantic-validated decision. The runner records only the semantic action and a short reasoning summary, then sends the action through policy and the surface adapter. This trades generality for a narrow, inspectable vertical slice.

# 2. Artifact schema

`CapabilityArtifact` is a JSON-serializable, versioned Pydantic model. Its schema version is currently `1.0`; its independent `revision` identifies a reviewed capability revision. The artifact contains:

- capability identity, name, description, and compatibility metadata;
- entry point and ordered discriminated-union actions;
- typed input declarations and symbolic fill templates;
- output extraction declarations;
- a success checkpoint and optional known business outcomes; and
- a safety profile listing permitted action types and maximum risk behavior.

The V1 actions are `navigate`, `click`, `fill`, `wait_for_state`, and `extract_text`. A target contains ordered locator candidates. Candidate strategies include role/name, label, visible text, attribute, and CSS forms. The artifact does not contain Playwright objects or model transcripts.

Runtime values are supplied at invocation time. A recorded fill step stores `${member_id}` rather than the value used during discovery. Sensitive parameter defaults are rejected by the model validation, and the CLI redacts invocation values in evidence. The checked-in example is a synthetic artifact; it is not represented as a live discovery recording.

# 3. Determinism & error handling

`CapabilityReplayRunner` accepts an artifact, invocation mapping, policy-enforced surface, and optional evidence sinks. It validates required and unknown parameters, executes actions in their serialized order, resolves targets through the adapter, and never imports or calls an LLM provider.

Each action passes through `PolicyEnforcedSurfaceAdapter` before reaching the underlying surface. Fill templates are resolved from in-memory invocation values at execution time. Surface operations use Playwright's bounded action/wait APIs; replay adds a fixed transient retry budget and retries only errors whose message identifies a slow, loading, or transient condition. It does not invent alternate steps.

After actions, the runner checks declared business outcomes and then the final checkpoint. `MEMBER_NOT_FOUND` is returned as `KnownBusinessOutcome`, not an exception. Other result types are `CapabilityExecutionSucceeded`, `CapabilityExecutionFailed`, and `HumanInterventionRequired`. Hard failures include the capability ID, artifact schema version, step ID/index, expected state, sanitized observed state, machine-readable category, debugging summary, and optional screenshot reference.

Checkpoint support is intentionally small: visible targets, text containment, URL patterns, and extracted-value patterns. The current replay tests use deterministic fake surfaces for the taxonomy and existing browser tests exercise the real Playwright adapter. The CLI provides real-browser replay against the local app.

# 4. Heterogeneity & multi-tenant

The artifact describes semantic intent and expected states; `ComputerSurfaceAdapter` supplies perception and interaction mechanics. That boundary permits a future accessibility-tree or native desktop adapter without changing the capability action vocabulary. The current implementation only supplies Playwright. Coordinate automation, desktop automation, and accessibility-tree resolution are not implemented.

Compatibility metadata records surface kind, vendor product/version, application identity/version, and an optional tenant variant. The current CLI does not implement a tenant catalog or override service. A credible next layer would keep a vendor-level artifact as the base contract and apply constrained, versioned tenant locator/route overrides at runtime, while preserving the artifact's safety profile and input/output contract. Replay failures and fallback usage would be the signals for drift review rather than automatic mutation.

This is a design seam, not a claim that multi-tenant execution exists in the current code.

# 5. Escalation & handoff

`HumanInterventionCoordinator` owns a session-scoped lease represented by `AUTOMATION` or `HUMAN`. It observes the current state, calls `expose_live_session`, creates a typed `HumanInterventionRequest`, and captures a screenshot reference. The request contains capability and goal, current step, reason, sanitized state, session ID, and control owner.

While the human owns the session, the Playwright adapter rejects automation operations. The coordinator accepts explicit typed human actions against that same browser page, records a `HumanActionRecord`, captures evidence, and exposes `resume_automation`. Resume requires the same session ID and changes ownership back to automation. Invalid repeated handoffs, late human actions, and invalid resumes are rejected.

The `human-demo` CLI exercises this path against the live local browser by dismissing a simulated session dialog. It is intentionally a small scripted operator surface. There is no real-time multi-user console, authentication for operators, or automatic integration from every replay failure into a coordinator request; those are deliberate scope cuts.

# 6. Safety

Safety is explicit and evaluated before an action is delegated. `SafetyPolicy` contains allowed origins/routes, permitted action types, denied risk classes, and risk classes requiring confirmation. `SafetyPolicyEvaluator` returns `allowed`, `requires_human_confirmation`, or `denied`. The wrapper blocks navigation outside the configured target allowlist and blocks action types not explicitly permitted.

The V1 risk model distinguishes read-only, reversible, and irreversible actions. Irreversible actions are denied by the default artifact policy unless a policy explicitly requires human confirmation. Replay maps a confirmation-required action to `HumanInterventionRequired`; it does not silently execute it.

Evidence persistence is a separate security boundary. `SensitiveDataRedactor` recursively redacts configured field names and token/header patterns before JSONL writing. CLI policies redact member IDs, authorization/cookie/token fields, balances, outputs, visible state, and values. Artifacts contain symbolic parameter references, not invocation values. These controls reduce accidental persistence; they do not replace secret management, authorization, or production compliance controls.

# 7. Cuts

The following were intentionally not implemented:

- real banking or external production applications;
- real credentials, production PII, or financial transaction submission;
- a native desktop or accessibility-tree surface adapter;
- a distributed worker/service architecture;
- a capability catalog, approval lifecycle, tenant override service, or drift remediation;
- open-ended LLM recovery during replay;
- a full operator console with concurrent users, authentication, or co-browsing;
- automatic escalation wiring from every replay failure into a human queue; and
- a fabricated live discovery evidence bundle.

The scope was reduced intentionally to preserve depth in the load-bearing requirements: typed and reviewable artifacts, a real surface abstraction, policy-before-action enforcement, an LLM decision seam, deterministic replay, explicit business/error result types, redacted evidence, and same-session control transfer. The remaining work is primarily production hardening and breadth around those seams rather than a hidden claim of completeness.
# 1. Architecture

This project uses a small, single-process Python application with clear logical boundaries rather than prematurely introducing services, queues, or multi-tenant infrastructure. The implemented vertical slice targets a local, intentionally legacy-style member-servicing web application with synthetic data. The representative capability is: look up a member by member ID and return the current savings balance.

The main boundaries are:

- `surface`: perception and interaction mechanics. V1 provides a Playwright browser adapter.
- `capabilities`: versioned Pydantic contracts for reusable capability artifacts, actions, locators, inputs, outputs, checkpoints, and results.
- `discovery`: the observe-decide-act loop, including the OpenAI-compatible LLM client and action recording.
- `replay`: deterministic execution of saved artifacts without LLM decisions.
- `policy`: URL, route, frame, action, and risk allowlists.
- `intervention`: pause, human control transfer, resume, and human-action recording.
- `evidence`: structured JSONL run logs, sanitized observations, screenshots, and failure references.
- `demo_app`: the local banking/member-servicing surface used for the end-to-end demonstration.

The LLM is used during discovery only. It proposes one bounded, structured action at a time from the current observation. It never receives direct Playwright access. The recorder converts successful semantic actions into a reviewable artifact that is independent of the raw model transcript. Replay is the production execution path and does not ask the model what to do next.

Playwright is a pragmatic V1 choice because it provides reliable browser sessions, waiting, screenshots, and frame support while keeping the surface boundary explicit. The local demo application avoids dependence on a public site, rate limits, changing content, or real credentials and PII. The trade-off is that the demonstration does not prove native desktop support; that is addressed through the adapter boundary and future-extension design below.

# 2. Artifact schema

A capability artifact is a typed, versioned, serializable contract for an agent-invocable operation. It is not a transcript or an opaque sequence of model messages.

The top-level artifact contains:

- `artifact_version`: serialization/schema version.
- `capability_id`: stable logical name, such as `member.savings_balance.lookup`.
- `revision`: reviewed revision of this capability.
- `name` and `description`: human- and agent-readable contract.
- `surface`: surface kind, application identity, and supported application version.
- `entry_point`: approved starting route or application entry point.
- `inputs`: typed invocation parameters.
- `outputs`: typed extracted results.
- `steps`: ordered action definitions.
- `success_checkpoint`: final state assertion.
- `error_handlers`: declared business outcomes and bounded recoveries.
- `safety_profile`: permitted actions and risk classification.
- `recording_metadata`: provenance without raw sensitive values.

A representative artifact has this shape:

```json
{
  "artifact_version": "1.0",
  "capability_id": "member.savings_balance.lookup",
  "revision": 1,
  "surface": {
    "kind": "web",
    "application": "local-member-servicing",
    "supported_version": "demo-1"
  },
  "inputs": [
    {
      "name": "member_id",
      "type": "string",
      "required": true,
      "validation": "^[0-9]{5}$",
      "sensitive": false
    }
  ],
  "outputs": [
    {
      "name": "savings_balance",
      "type": "decimal",
      "source": "member_detail.savings_balance",
      "parser": "currency",
      "required": true,
      "sensitive": true
    }
  ],
  "steps": [],
  "success_checkpoint": {},
  "error_handlers": [],
  "safety_profile": {}
}
```

Concrete discovery values must not be persisted in the artifact. Runtime values are represented by explicit references such as `${inputs.member_id}`. The artifact schema is separate from the schema of run events and separate from any model transcript.

The artifact is deliberately declarative. It describes the intended interaction and expected states; the surface adapter decides how to realize those operations on a particular surface.

# 3. Determinism & error handling

Replay validates the artifact version and input parameters, checks the entry point against policy, creates or receives a browser session, and executes the declared steps in order. It uses bounded waits, stable target resolution, declared postconditions, and a final checkpoint. It then extracts the declared outputs and returns a structured result.

The replay engine never invokes the LLM for a decision. It cannot skip a step, invent a new path, or silently choose among ambiguous controls. A target can contain ordered locator candidates, but fallback usage is recorded in evidence and ambiguous matches stop execution.

The primary checkpoint for the member balance capability requires that:

- the member detail heading is visible;
- the displayed member ID matches the requested member ID;
- the savings balance field exists and is parseable as currency; and
- no known error banner, permission dialog, or session-expiry state is visible.

V1 supports bounded recovery for safe, known conditions only. Examples include retrying a transient load, dismissing a declared interstitial, or repeating an idempotent read-only step. Recovery has a fixed retry budget and cannot be used to repeat risky actions.

The result contract distinguishes three categories:

- **Expected business outcome:** a valid domain result such as `MEMBER_NOT_FOUND`, `MEMBER_ACCESS_RESTRICTED`, or `NO_SAVINGS_ACCOUNT`. This is returned to the caller as an outcome, not as an automation crash.
- **Recoverable runtime condition:** a slow load, known transient application error, dismissible interstitial, or configured session timeout that may be handled by bounded policy. Recovery attempts are recorded.
- **Hard automation failure:** an allowlist violation, unsupported or ambiguous locator, checkpoint mismatch, unexpected dialog, exhausted timeout, unknown application error, incompatible artifact, or safety violation. Execution stops with the capability ID, run ID, step ID, expected state, observed state summary, error code, and evidence references.

UI drift is treated as a compatibility failure rather than something for replay to repair through open-ended reasoning. The adapter can use a small, ordered set of locator fallbacks, but unresolved ambiguity or missing targets must be surfaced clearly.

# 4. Heterogeneity & multi-tenant

The artifact and replay engine are independent of Playwright. A `SurfaceAdapter` translates semantic operations such as `click(target)`, `fill(target, value)`, `read(target)`, and `wait_for(condition)` into surface-specific mechanics. This allows the same capability semantics to be implemented by a browser DOM adapter, a browser accessibility-tree adapter, or a native desktop accessibility adapter later.

The target schema prioritizes semantic properties such as role, accessible name, label, stable attributes, visible text, bounded region, and expected count. CSS selectors and coordinates are fallbacks, not the primary representation. A coordinate target, if eventually required for a surface with no usable semantic tree, would include a screenshot anchor and stricter post-action verification.

Artifacts identify the vendor product and supported version independently from tenant configuration. A reusable base artifact can target a vendor product/version range while runtime configuration supplies the tenant's base URL, branding differences, route configuration, feature flags, and approved locator overrides.

Tenant overrides are declarative, versioned, and constrained. They may replace a locator or a surface-specific step, but they may not silently weaken the safety profile or change the public input/output contract. Before replay, the system identifies the tenant variant, applies allowed overrides, performs compatibility checks, and verifies key checkpoints.

Replay telemetry should record fallback usage, checkpoint failures, recovery frequency, and artifact revisions by tenant and application version. A rising failure rate indicates drift and triggers review or a new specialized revision; it does not automatically re-record a capability in production.

# 5. Escalation & handoff

The system uses a session-scoped control lease with two possible owners: `AUTOMATION` and `HUMAN`. The live browser session, including its cookies and current page, remains the same throughout the handoff.

When discovery or replay reaches a stuck or human-required state, the runner:

1. pauses before taking another automation action;
2. transfers the control lease to a human operator;
3. creates an intervention request containing the run and capability IDs, goal, current step, session ID, sanitized state, screenshot/evidence reference, and reason for escalation;
4. exposes the same browser session for manual operation;
5. records operator actions at the surface boundary;
6. waits for the operator to signal completion or resume;
7. reacquires the automation lease; and
8. re-observes the same session before continuing.

The V1 operator surface may be a CLI or local mock endpoint. The important implemented behavior is pause, same-session ownership transfer, resume, and evidence capture. Automation cannot act while the human owns the lease, and a human action does not silently mutate the saved artifact. A useful human-assisted path may be proposed as a later artifact revision for review.

Typical escalation triggers include an unexpected dialog, an unknown permission state, an exhausted bounded recovery budget, an irreversible action request, or a discovery loop that repeats the same state without progress.

# 6. Safety

Safety is enforced by explicit policy before each discovery or replay action. The LLM is not trusted to determine whether an action is permitted.

The V1 surface allowlist defines:

- approved hostnames and URL path patterns;
- approved frame origins;
- approved application and version identifiers; and
- permitted action types.

V1 permits navigation within approved routes, clicks on approved controls, filling approved fields, safe keyboard input, reading approved output fields, and evidence capture. Arbitrary JavaScript, unrestricted coordinates, file uploads, downloads, payment submission, account creation, deletion, and transaction submission are outside the V1 action set.

Actions are classified as:

- `READ_ONLY`: navigation, search, and extraction;
- `REVERSIBLE`: local filters or dismissible UI changes; and
- `IRREVERSIBLE`: account creation, transactions, deletion, or external communication.

V1 blocks irreversible actions. A future implementation could support them only with explicit policy approval and human confirmation. Replay must never retry an irreversible action automatically.

Sensitive data handling is enforced at the evidence boundary. Credentials and tokens are never recorded. Member identifiers, names, addresses, account numbers, and balances are redacted, masked, hashed, or replaced with synthetic values before persistence. The committed demonstration uses synthetic data. Runtime outputs can be returned to the caller under the capability contract while evidence stores only approved redacted representations.

# 7. Cuts

The implementation deliberately leaves out:

- integration with a real banking system;
- real credentials or production PII;
- native desktop automation;
- distributed services, queues, and scaling infrastructure;
- a full real-time operator console;
- open-ended LLM recovery during replay;
- unrestricted coordinate automation;
- irreversible transaction capabilities; and
- automatic cross-tenant artifact mutation.

These cuts preserve the load-bearing vertical slice: a real discovery run against a live local UI, a saved typed artifact, deterministic replay with typed inputs and outputs, explicit business/error outcomes, safety enforcement, same-session human handoff, and evidence for discovery and replay. With more time, the next priorities would be an accessibility-tree adapter, stronger artifact approval and stability scoring, a real operator console, and controlled tenant-variant compatibility testing.
