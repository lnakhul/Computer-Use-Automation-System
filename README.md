# Computer-Use-Automation-System
AI agents for banks and credit unions. This project is about the backend integration layer that gives those agents hands - the system that lets an AI agent actually operate an institution's back-office applications to get real work done.

## Reproducible demo commands

Install the project and test dependencies:

```bash
python3 -m pip install -e '.[test]'
```

Start the local legacy member-servicing target in terminal 1:

```bash
automation demo
```

The app is available at `http://127.0.0.1:5001`.

Run a genuine configured OpenAI-compatible discovery session in terminal 2. This is opt-in and does not claim that a live model run has already happened:

```bash
export OPENAI_API_KEY="your-key"
export OPENAI_MODEL="gpt-4o-mini"
automation discover \
	--goal "look up member 12345 and read the current savings balance" \
	--member-id 12345
```

The discovery command writes `evidence/discovery-artifact.json` and `evidence/discovery-run.jsonl`.

Replay the named artifact without an LLM:

```bash
automation replay evidence/discovery-artifact.json --member-id 12345
```

Replay the checked-in example artifact instead:

```bash
automation replay examples/member_savings_balance.json --member-id 12345
```

Demonstrate the expected member-not-found business outcome:

```bash
automation replay-not-found examples/member_savings_balance.json
```

Exercise same-session human control transfer, a real Playwright operator action, evidence capture, and resume:

```bash
automation human-demo
```

Each command writes machine-readable JSONL under `evidence/` with a run ID, timestamps, capability metadata when applicable, sanitized actions/results, outcomes or failures, checkpoint status, and evidence references. Failure and handoff screenshots are written under the corresponding evidence directory. Credentials, tokens, and invocation values are redacted or represented symbolically.
