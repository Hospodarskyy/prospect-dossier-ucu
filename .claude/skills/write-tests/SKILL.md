---
name: write-tests
description: Write or update pytest tests for the Prospect Dossier project the way this repository does it (offline, fake ADK contexts, temporary storage, regression tests for eval findings). Use when adding or changing code in dossier_agent/, service/, demo_app/ or eval/, and when a change breaks existing tests.
---

# Write tests for this project

Rule of the project: a component is not done until it has an offline test
and/or an eval. Tests are the cheap, exact layer; what the model does is
measured by the eval (`run-eval` skill), not by unit tests.

## Ground rules

- **Offline only.** No model call, no network, no real storage. A test that
  needs one of them fakes it (below). `pytest` must pass without `.env` and
  without internet.
- **Storage.** `tests/conftest.py` gives every test its own temporary
  `LocalStorage` with `config/seller_cases.md` (autouse fixture `tmp_storage`);
  never read or write `data/storage/`. Use `tmp_storage` directly when a test
  needs to put files there (memory, outbox, inbox).
- **Prices.** conftest removes the Vertex variables, so costs use the Gemini API
  table; set them in the test if it is about Vertex.
- One file per module (`tests/test_<module>.py`), sections separated by comment
  banners, a docstring on top saying what the file covers.

## Faking ADK and the outside world

| What | How it is done here |
|---|---|
| a custom agent (`BaseAgent._run_async_impl`) | `ctx = SimpleNamespace(invocation_id="inv-1", session=SimpleNamespace(state={...}))`, then `asyncio.run` over `[e async for e in Agent()._run_async_impl(ctx)]`; check `event.actions.state_delta`, `escalate`, `invocation_id` |
| a callback (`init_state`, `finalize_run`, ...) | `SimpleNamespace(state={...}, user_content=types.Content(role="user", parts=[types.Part(text=...)]))` |
| a function tool with `tool_context` | `SimpleNamespace(state={...})` as `tool_context`; assert both the return value and what it wrote to state |
| web pages | pass a fake `fetch` to `verify_research(..., fetch=...)` (see `fake_fetch` in `test_verification.py`), or `monkeypatch.setattr(agent_module, "verify_research", fake)` |
| the agent inside the service | `handle_run(storage, run=fake_run, ...)` with a fake that returns a result (see `test_service.py`) |
| the Streamlit demo | `streamlit.testing.v1.AppTest` on `app.py` (see `test_demo_app.py`) |
| a whole run without cost | not a unit test: run the agent with `MAX_LLM_CALLS=0` (every model call is blocked by the hard stop) |

When a change in ADK usage changes the shape of these fakes (a new field read
from `ctx`), update every fake that builds it: `grep -rn "SimpleNamespace(" tests/`.

## What to test

- **Edge cases with `@pytest.mark.parametrize`:** empty, missing, malformed and
  hostile values (a domain like `../../etc` becomes a file path; a broken JSON
  request must stop before any model call).
- **A regression test for every finding**, with a comment saying where it came
  from, e.g. `# found by the component eval (2026-11-13): Doctolib got industry
  "Healthcare" ...`. The test fails on the old code and passes on the fix.
- **Rules in prompts that code relies on:** assert the key sentence is in the
  instruction (e.g. `"A different set of people in Key" in WRITER_INSTRUCTION`),
  so it is not lost in an edit. Do not test the model's answer this way.
- **Eval code is code:** metric formulas get tests on a small made-up run
  (`test_eval_components.py`).

## Steps

1. Read the module and its existing test file; reuse its helpers and fixtures.
2. Write the failing test first when fixing a bug, and check that it fails.
3. Run the file, then the whole suite: `pytest -q` (from the repository root;
   `pytest.ini` puts the root on the path). Every test must pass.
4. Tell the user how many tests were added and what they cover; update the test
   count in `CLAUDE.md` section 3 if it changed.
