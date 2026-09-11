# 1. Architecture

This is a single-process vertical slice against a synthetic Flask member-servicing UI. The provider proposes bounded typed decisions; discovery records semantic actions; replay consumes the artifact without a model. `ComputerSurfaceAdapter` owns browser mechanics. Deployment policy approves operations before dispatch. Evidence persistence and human control transfer are separate boundaries.

The concrete adapter is Playwright. Labels and roles are preferred, with explicit attribute/CSS fallbacks for legacy markup. The application uses tables and no test IDs, but this does not prove support for framesets or native applications. A provider receives visible state, a bounded control inventory, and the names of declared inputs/outputs. JSON responses are validated locally against the decision union. No raw model transcript is saved.

# 2. Artifact schema

`CapabilityArtifact` has `artifact_schema_version`, independent `revision`, identity/description, compatibility metadata, `entry_point`, inputs, actions, outputs, success checkpoint, known business outcomes, and safety profile. Actions and locator strategies are discriminated unions, not Playwright objects. Unknown fields and unsupported schema versions are rejected.

Inputs have types, required/default behavior and constraints. Replay validates them before interaction. Fill actions use a single symbolic reference, such as `${member_id}`; navigation can contain URL-encoded references. Names and references must be coherent. Outputs bind to a unique extraction action of the same name, and their declared parser must agree with their type. Currency becomes `Decimal` in Python and a decimal string in JSON, preserving precision. Checkpoint regexes over extracted values apply to the original text; parsing is additionally required for success.

Discovery verifies outputs and the declared checkpoint before publishing. It uses generic action descriptions, parameterizes runtime values in navigation, and rejects artifacts containing literal invocation values. This deliberately rejects recordings that would need more sophisticated target canonicalization. It is preferable to emitting a capability tied to the first member.

# 3. Determinism & error handling

Replay executes the recorded order without importing a model provider. Retargeting resolves each relative route without replacing its path. Locators have ordered candidates: no match permits fallback; ambiguity stops. Visibility and text waits include element appearance and changing text within a bounded deadline. Text checkpoints remain scoped to their declared target. The example verifies the requested member URL and a parseable savings balance.

Known business outcomes are checked after each successful action, before happy-path postconditions. `MEMBER_NOT_FOUND` is returned as a domain result. Browser errors are translated into surface errors. Only typed timeouts on read/wait actions get a fixed retry budget; clicks and submissions are never automatically retried after uncertain execution. Unknown dialogs stop for operator review. Hard failures preserve step, expected state, sanitized observed state, category and evidence reference. Diagnostic capture is best-effort so a closed page cannot erase the primary failure.

These are deterministic instructions, not a guarantee that an external application always has the same data. No open-ended recovery, branching planner or drift repair is used. The current condition vocabulary is intentionally small.

# 4. Heterogeneity & multi-tenant

The protocol separates perception/action from the recorded action vocabulary. Role/name and label targets could map to desktop accessibility controls; CSS and attributes are explicitly browser-specific. A native adapter would require a versioned locator extension and validation of adapter-supported operations before invocation. URL locations similarly need a surface-specific interpretation for desktop windows. Simply swapping adapters would not make arbitrary web artifacts portable.

Compatibility metadata separates vendor product/version, application identity/version and tenant variant. A future runtime should compare this metadata with trusted deployment configuration before selecting an artifact. Resolution metadata for clicks, fills and reads is available in replay evidence. Versioned tenant overrides may specialize origins, routes and locators while preserving input/output and safety contracts. Store fallback and checkpoint telemetry by artifact revision and tenant/version to flag drift for review. This is a design proposal, not a tenant service implemented here; the assignment explicitly does not require one.

# 5. Escalation & handoff

The adapter owns an automation/human lease for one existing browser page. The coordinator transfers ownership, emits sanitized context and evidence, accepts explicit operator actions and signals resume. Evidence failures do not prevent the ownership transition. Automation actions are refused while the human owns the page.

`--interactive` connects discovery/replay to a minimal JSON-action operator console. It exposes the same headed session. Enter explicit click/fill/navigation actions through the console so they are recorded, then `resume` or `stop`. Replay retains its action index and captured outputs. A dialog detected before execution can be repaired and the pending action resumed; a read/wait may be retried after intervention. An uncertain click is not repeated automatically. Policy confirmation requests are routed for review but are not silently approved by resume. This is a deliberately conservative completion boundary.

The separate `human-demo` remains a scripted seam demonstration, not proof of a person operating the console. There is no concurrent co-browsing UI or native-click recorder. Direct manual browser actions bypass the console's event recording; use the explicit console to capture operator actions.

# 6. Safety

Trusted demo deployment policy independently approves the member-ID field and Search button; model risk labels cannot authorize other controls. Unknown interaction targets are rejected. Origins/routes and current location are checked, and a browser-context request guard blocks disallowed requests, redirects and frames before dispatch. Only the synthetic member search POST is allowed. The CLI disables service workers and downloads. Artifact block mode denies irreversible actions; deployment policy remains the authority.

The demo permits approved GET routes and assumes they are side-effect-free. This assumption must be reconfigured for another application. This is not an OS sandbox and does not claim to govern external browser extensions, native controls or arbitrary code outside the adapter.

Failure/handoff state omits raw page text, URLs and field values. Screenshots mask the entire page; a companion structural snapshot records only control tags/types. This sacrifices visual detail to avoid persisting sensitive contents. Evidence omits extracted values and model reasoning. Artifacts reject literal invocation values. Runtime observations sent to the configured model are unredacted application state; use this demo only with synthetic data. Production use would require an approved observation projection before model transmission, not just log redaction.

# 7. Cuts

No real banking integration, production data, desktop adapter, tenant service, distributed workers, capability catalog, approval lifecycle or automatic drift remediation is implemented. These are deliberate scope cuts rather than missing infrastructure to build for this assessment.

The mandatory genuine LLM-driven discovery evidence is still missing. Offline and real-browser tests validate mechanics but cannot substitute for it. Before submission, run discovery with your configured model API access, commit its sanitized artifact/log and replay that exact artifact under `evidence/`. This is an unresolved must-have, not an acceptable scope cut. The next work should close that evidence gap and validate the resulting recording across the synthetic members, rather than broaden the feature set.
