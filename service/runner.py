"""Run the ADK pipeline once for one request (spec hard stops on the service
side: RunConfig(max_llm_calls) and asyncio.wait_for)."""
import asyncio
import inspect
from collections.abc import Callable
from dataclasses import dataclass

from google.adk.agents.run_config import RunConfig
from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.genai import types

APP_NAME = "dossier_agent"
USER_ID = "service"


@dataclass
class RunOutcome:
    state: dict               # session state after the run (may be partial)
    error: str | None         # None if the pipeline finished


async def run_agent(request_text: str, *, run_id: str, started_at: str, trigger: str,
                    timeout_seconds: float, max_llm_calls: int,
                    on_event: Callable | None = None) -> RunOutcome:
    """One session per run. Exceptions and the timeout are caught and returned
    as RunOutcome.error, together with whatever state the session reached.

    on_event(event) is called for every ADK event as it arrives (sync or async);
    the Streamlit demo uses it to show the run live."""
    from dossier_agent.agent import root_agent   # imported late: reads .env and config

    sessions = InMemorySessionService()
    session = await sessions.create_session(
        app_name=APP_NAME, user_id=USER_ID,
        state={"run_id": run_id, "started_at": started_at, "trigger": trigger},
    )
    runner = Runner(agent=root_agent, app_name=APP_NAME, session_service=sessions)
    message = types.Content(role="user", parts=[types.Part(text=request_text)])

    async def consume() -> None:
        async for event in runner.run_async(user_id=USER_ID, session_id=session.id,
                                            new_message=message,
                                            run_config=RunConfig(max_llm_calls=max_llm_calls)):
            if on_event is not None:
                result = on_event(event)
                if inspect.isawaitable(result):
                    await result

    error = None
    try:
        await asyncio.wait_for(consume(), timeout=timeout_seconds)
    except asyncio.TimeoutError:
        error = f"timeout: the run took longer than {timeout_seconds:.0f} s"
    except Exception as exc:          # Vertex down, ConfigError, LlmCallsLimitExceededError, ...
        error = f"{type(exc).__name__}: {exc}"
    final = await sessions.get_session(app_name=APP_NAME, user_id=USER_ID, session_id=session.id)
    return RunOutcome(state=dict(final.state) if final else {}, error=error)
