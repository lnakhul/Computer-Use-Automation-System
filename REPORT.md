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
