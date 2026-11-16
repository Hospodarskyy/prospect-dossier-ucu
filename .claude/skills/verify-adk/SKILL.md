---
name: verify-adk
description: Check how Google ADK really behaves in the installed version before relying on it (callbacks, events, state, tools, adk eval, adk web). Use before writing code or advice that depends on an ADK detail that is not already in CLAUDE.md section 6.
---

# Verify an ADK fact in the installed source

ADK changes quickly and its documentation, examples and model memory often
describe another version. The project pins `google-adk==1.39.1`
(`requirements.txt`); what that code does is the truth.

1. Look in `CLAUDE.md` section 6 first: facts there are already verified.
2. Otherwise find it in the installed package, not from memory:
   - root: `.venv/lib/python3.12/site-packages/google/adk/`
   - search: `grep -rn "<name>" .venv/lib/python3.12/site-packages/google/adk/`
   - read the function that does the work, not only its docstring.
   adk.dev and GitHub are second sources; if they disagree with the installed
   code, the installed code wins.
3. If reading is not enough, confirm with a run that costs nothing:
   an offline test with a fake context, or a full run with `MAX_LLM_CALLS=0`
   (every model call is blocked by the hard stop, so no tokens are spent).
4. Write the fact into `CLAUDE.md` section 6, in English, one bullet: what
   happens, the file (and function) where it is decided, and how it was checked.
5. Tell the user what was found and where, before using it.

Facts found this way (now in CLAUDE.md section 6):
- callbacks that change state emit their own event with `state_delta` and no
  text; Google Search grounding does not appear as a function call;
- `adk eval` groups a run's events by `invocation_id`, so an event built
  without `invocation_id=ctx.invocation_id` makes one run look like two
  (`evaluation/evaluation_generator.py`);
- `adk eval` loads the agent's `.env` with `override=True`
  (`cli/utils/envs.py`), so shell variables do not win there.
