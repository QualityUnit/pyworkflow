"""
Tool-Calling Agent — Standalone Runtime

Run an agent with no workflow context at all.  The agent calls the LLM,
executes tools, and returns the result — just like a regular function.

This is the simplest way to use pyworkflow_agents and requires zero
pyworkflow infrastructure (no storage, no Celery, no event log).

Three styles are shown side-by-side:
  1. @tool_calling_agent decorator
  2. Agent base class
  3. run_tool_calling_loop() directly

Requirements:
    pip install 'pyworkflow-engine[agents]' langchain-openai

Run:
    OPENAI_API_KEY=sk-... python examples/tool_calling_agent/standalone.py
"""

import asyncio
import os

from langchain_openai import ChatOpenAI

from pyworkflow_agents import Agent, tool, tool_calling_agent
from pyworkflow_agents.agent.tool_calling.loop import run_tool_calling_loop

# ---------------------------------------------------------------------------
# Tools
# ---------------------------------------------------------------------------

@tool(register=False)
def get_weather(city: str) -> str:
    """Get the current weather for a city."""
    # Stub — replace with a real API call
    forecasts = {
        "london": "Overcast, 8°C",
        "tokyo": "Sunny, 22°C",
        "new york": "Partly cloudy, 15°C",
    }
    return forecasts.get(city.lower(), f"No data for {city}")


@tool(register=False)
def get_population(city: str) -> str:
    """Get the population of a city."""
    populations = {
        "london": "~9 million",
        "tokyo": "~14 million",
        "new york": "~8.3 million",
    }
    return populations.get(city.lower(), f"No data for {city}")


TOOLS = [get_weather, get_population]


# ---------------------------------------------------------------------------
# 1. Decorator style
# ---------------------------------------------------------------------------

model = ChatOpenAI(model="gpt-4o-mini")


@tool_calling_agent(model=model, tools=TOOLS)
async def city_info_agent(city: str):
    """You answer questions about cities using the available tools."""
    return f"Tell me about the weather and population of {city}."


# ---------------------------------------------------------------------------
# 2. Base-class style
# ---------------------------------------------------------------------------


class CityInfoAgent(Agent):
    """You answer questions about cities using the available tools."""

    model = model
    tools = TOOLS

    async def run(self, city: str) -> str:
        return f"Tell me about the weather and population of {city}."


# ---------------------------------------------------------------------------
# 3. Direct loop call
# ---------------------------------------------------------------------------


async def city_info_direct(city: str):
    return await run_tool_calling_loop(
        model=model,
        input=f"Tell me about the weather and population of {city}.",
        tools=TOOLS,
        system_prompt="You answer questions about cities using the available tools.",
        record_events=False,
    )


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


async def main():
    if not os.environ.get("OPENAI_API_KEY"):
        print("Set OPENAI_API_KEY to run this example.")
        return

    city = "Tokyo"

    print("=== Tool-Calling Agent — Standalone Runtime ===\n")

    # 1. Decorator
    print("--- 1. @tool_calling_agent decorator ---")
    result = await city_info_agent(city)
    print(f"Answer:  {result.content}")
    print(f"Iters:   {result.iterations}  |  Tool calls: {result.tool_calls_made}\n")

    # 2. Base class
    print("--- 2. Agent base class ---")
    agent = CityInfoAgent()
    result = await agent(city=city)
    print(f"Answer:  {result.content}")
    print(f"Iters:   {result.iterations}  |  Tool calls: {result.tool_calls_made}\n")

    # 3. Direct loop
    print("--- 3. run_tool_calling_loop() ---")
    result = await city_info_direct(city)
    print(f"Answer:  {result.content}")
    print(f"Iters:   {result.iterations}  |  Tool calls: {result.tool_calls_made}\n")

    print("=== Key Characteristics ===")
    print("  - No workflow context, no storage, no Celery")
    print("  - Agent runs as a plain async function")
    print("  - Perfect for scripts, notebooks, and quick prototypes")


if __name__ == "__main__":
    asyncio.run(main())
