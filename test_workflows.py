"""Test workflows for CLI testing."""

from pyworkflow import step, workflow


@step()
async def greet(name: str) -> str:
    """Greet the user."""
    return f"Hello, {name}!"


@step()
async def add_numbers(a: int, b: int) -> int:
    """Add two numbers."""
    return a + b


@workflow(durable=True)
async def simple_workflow(name: str) -> str:
    """A simple greeting workflow."""
    greeting = await greet(name)
    return greeting


@workflow(durable=True, max_duration="1h")
async def math_workflow(x: int, y: int) -> dict:
    """A simple math workflow."""
    result = await add_numbers(x, y)
    greeting = await greet("Math Wizard")
    return {"result": result, "greeting": greeting}
