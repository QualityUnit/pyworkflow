"""Service layer for workflow operations."""

import inspect
from typing import Any, get_origin, get_type_hints

from app.repositories.workflow_repository import WorkflowRepository
from app.schemas.workflow import (
    WorkflowListResponse,
    WorkflowParameter,
    WorkflowResponse,
)


def _get_type_name(type_hint: Any) -> str:
    """Convert a Python type hint to a simple type name for the frontend.

    Args:
        type_hint: The type hint to convert.

    Returns:
        A string representing the type ("string", "number", "boolean", "array", "object", "any").
    """
    if type_hint is Any or type_hint is inspect.Parameter.empty:
        return "any"

    # Handle None type
    if type_hint is type(None):
        return "any"

    # Get the origin for generic types (e.g., list[str] -> list)
    origin = get_origin(type_hint)
    if origin is not None:
        if origin is list:
            return "array"
        if origin is dict:
            return "object"
        # Union types (Optional, etc.)
        if origin is type(None):
            return "any"

    # Handle basic types
    if hasattr(type_hint, "__name__"):
        type_name = type_hint.__name__
        if type_name == "str":
            return "string"
        if type_name in ("int", "float"):
            return "number"
        if type_name == "bool":
            return "boolean"
        if type_name == "list":
            return "array"
        if type_name == "dict":
            return "object"

    return "any"


def _extract_workflow_parameters(func: Any) -> list[WorkflowParameter]:
    """Extract parameter information from a workflow function.

    Args:
        func: The workflow function to inspect.

    Returns:
        List of WorkflowParameter objects.
    """
    sig = inspect.signature(func)
    params = []

    # Try to get type hints
    try:
        hints = get_type_hints(func)
    except Exception:
        hints = {}

    for param_name, param in sig.parameters.items():
        # Skip *args and **kwargs
        if param.kind in (inspect.Parameter.VAR_POSITIONAL, inspect.Parameter.VAR_KEYWORD):
            continue

        type_hint = hints.get(param_name, Any)
        has_default = param.default is not inspect.Parameter.empty

        # Serialize the default value
        default_value = None
        if has_default:
            default_value = param.default

        param_info = WorkflowParameter(
            name=param_name,
            type=_get_type_name(type_hint),
            required=not has_default,
            default=default_value,
        )
        params.append(param_info)

    return params


class WorkflowService:
    """Service for workflow-related business logic."""

    def __init__(self, repository: WorkflowRepository):
        """Initialize with workflow repository.

        Args:
            repository: WorkflowRepository instance.
        """
        self.repository = repository

    def list_workflows(self) -> WorkflowListResponse:
        """Get all registered workflows.

        Returns:
            WorkflowListResponse with list of workflows.
        """
        workflows = self.repository.list_all()

        items = [
            WorkflowResponse(
                name=name,
                description=metadata.description,
                max_duration=metadata.max_duration,
                tags=metadata.tags or [],
                parameters=_extract_workflow_parameters(metadata.original_func),
            )
            for name, metadata in workflows.items()
        ]

        return WorkflowListResponse(
            items=items,
            count=len(items),
        )

    def get_workflow(self, name: str) -> WorkflowResponse | None:
        """Get a specific workflow by name.

        Args:
            name: Workflow name.

        Returns:
            WorkflowResponse if found, None otherwise.
        """
        metadata = self.repository.get_by_name(name)

        if metadata is None:
            return None

        return WorkflowResponse(
            name=metadata.name,
            description=metadata.description,
            max_duration=metadata.max_duration,
            tags=metadata.tags or [],
            parameters=_extract_workflow_parameters(metadata.original_func),
        )
