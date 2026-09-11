# Computer-Use-Automation-System
AI agents for banks and credit unions. This project is about the backend integration layer that gives those agents hands - the system that lets an AI agent actually operate an institution's back-office applications to get real work done.

## Local discovery demo

Install the project and test dependencies with `python3 -m pip install -e '.[test]'`, then start the local demo application:

```bash
python3 -m automation.demo_app.app
```

With `OPENAI_API_KEY` configured, run a genuine OpenAI-compatible discovery session in a second terminal:

```bash
OPENAI_MODEL=gpt-4o-mini python3 -m automation.discovery.cli \
	--goal "look up member 12345 and read the current savings balance" \
	--target http://127.0.0.1:5001/members/search \
	--member-id 12345
```

The command writes the discovered artifact and redacted JSONL evidence to `evidence/`. This command is an opt-in manual run and does not imply that a live model run has already been performed.
