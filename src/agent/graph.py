"""LangGraph single-node graph template.

Returns a predefined response. Replace logic and configuration as needed.
"""

from __future__ import annotations

import asyncio
import copy
from dataclasses import dataclass, field
from datetime import datetime, timedelta
import logging
import time
from typing import Any, Dict, Literal

import aiohttp
from langgraph.graph import StateGraph
from langgraph.runtime import Runtime
from typing_extensions import TypedDict

from pydantic import BaseModel, Field
from laya.integrations.langchain import LayaDecision


log = logging.getLogger(__name__)
def _default_start() -> str:
    return (datetime.now() + timedelta(days=1)).strftime("%Y-%m-%dT00:00:00")

def _default_end() -> str:
    return (datetime.now() + timedelta(days=7)).strftime("%Y-%m-%dT23:59:59")

URL = "https://www.visitnh.gov/api/events/getitems"
HEADERS = {
    "User-Agent": "weekend-planner/0.1 (personal project)",
    "Accept": "application/json",
}
EVENT_CACHE_TTL_SECONDS = 300
_event_cache: dict[tuple[str, str], tuple[float, list[dict]]] = {}
_event_cache_lock = asyncio.Lock()


class Context(TypedDict):
    """Context parameters for the agent.

    Set these when creating assistants OR when invoking the graph.
    See: https://langchain-ai.github.io/langgraph/cloud/how-tos/configuration_cloud/
    """

    my_configurable_param: str


class Event(BaseModel):
    """Represents an event with a venue type."""

    venue: Literal["indoor", "outdoor", "mixed", "unknown"] = Field(
        default="unknown",
        description=(
            "Classify where event takes place. "
            "Choose indoor if entirely inside, outdoor if entirely outside, "
            "or mixed if it includes meaningful indoor and outdoor activities. "
            "If the description is ambiguous, choose unknown."
        )
    )


@dataclass
class State:
    """Input state for the agent.

    Defines the initial structure of incoming data.
    See: https://langchain-ai.github.io/langgraph/concepts/low_level/#state
    """

    request: str = ""
    events: list[dict] = field(default_factory=list)
    towns: list[str] = field(default_factory=list)
    forecasts: dict[str, str] = field(default_factory=dict)
    route: str = ""
    route_reason: str = ""
    start_date: str = field(default_factory=_default_start)
    end_date: str = field(default_factory=_default_end)
    errors: list[str] = field(default_factory=list)


# LangGraph node that calls national weather service API to get weather data for a given location
async def get_weather_data(state: State) -> Dict[str, Any]:
    """Get weather data for a given location.

    Args:
        state (State): The input state containing the location.
    Returns:
        Dict[str, Any]: The weather data for the given location.
    """
    # update state with weather data
    # Placeholder implementation - replace with actual API call
    for town in state.towns:
        state.forecasts[town] = {"temperature": "75°F", "condition": "Sunny"}
    return state

async def classify_events(state: State) -> Dict[str, Any]:
    """Classify events based on their venue type.

    Args:
        state (State): The input state containing the events.
    Returns:
        Dict[str, Any]: The updated state with classified events.
    """
    decide = LayaDecision(Event)

    prompts = [f"What is the venue type of the event '{event['title']}': {event['description']}?" for event in state.events]
    result = await asyncio.to_thread(decide.batch, prompts)
    print("Classification result:", result)

    for event, classification in zip(state.events, result):
        event["venue"] = classification["venue"]
    return state

async def get_event_data(state: State) -> dict[str, Any]:
    """Fetch events for the requested date range, using a short-lived cache."""
    cache_key = (state.start_date, state.end_date)
    now = time.monotonic()
    cached = _event_cache.get(cache_key)
    if cached and now - cached[0] < EVENT_CACHE_TTL_SECONDS:
        log.info("Using cached events for %s through %s", *cache_key)
        return {"events": copy.deepcopy(cached[1]), "errors": []}

    events: list[dict] = []
    errors: list[str] = []
    timeout = aiohttp.ClientTimeout(total=10)

    async with _event_cache_lock:
        cached = _event_cache.get(cache_key)
        if cached and time.monotonic() - cached[0] < EVENT_CACHE_TTL_SECONDS:
            log.info("Using cached events for %s through %s", *cache_key)
            return {"events": copy.deepcopy(cached[1]), "errors": []}

        async with aiohttp.ClientSession(headers=HEADERS, timeout=timeout) as session:
            page, hits = 1, None
            while hits is None or len(events) < hits:
                payload = {
                    "pageNumber": page,
                    "region": [], "city": [], "category": [],
                    "startDate": state.start_date,
                    "endDate": state.end_date,
                }
                try:
                    async with session.post(URL, json=payload) as resp:
                        if resp.status != 200:
                            body = (await resp.text())[:500]
                            errors.append(f"events page {page}: HTTP {resp.status} body={body} payload={payload}")
                            break
                        data = await resp.json()
                except (aiohttp.ClientError, asyncio.TimeoutError) as e:
                    errors.append(f"events page {page}: {e!r}")
                    break

                hits = data.get("hits", 0)
                batch = data.get("results", [])
                if not batch:
                    break
                events.extend(batch)
                page += 1
                await asyncio.sleep(1)      # be polite between pages

        if not errors:
            _event_cache[cache_key] = (time.monotonic(), copy.deepcopy(events))

    log.info("fetched %d of %s events", len(events), hits)
    return {"events": events, "errors": errors}


# Define the graph
graph = (
    StateGraph(State, context_schema=Context)
    .add_node(classify_events, name="classify_events")
    .add_node(get_weather_data, name="get_weather_data")
    .add_node(get_event_data, name="get_event_data")
    .add_edge("__start__", "get_event_data")
    .add_edge("get_event_data", "classify_events")
    .add_edge("classify_events", "get_weather_data")
    .add_edge("get_weather_data", "__end__")
    .compile(name="New Graph")
)
