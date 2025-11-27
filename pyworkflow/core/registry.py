"""
Global registry for workflows and steps.

The registry tracks all decorated workflows and steps, enabling:
- Lookup by name
- Metadata access
- Validation
"""

from typing import Any, Callable, Dict, Optional
from dataclasses import dataclass


@dataclass
class WorkflowMetadata:
    """Metadata for a registered workflow."""

    name: str
    func: Callable[..., Any]
    original_func: Callable[..., Any]  # Unwrapped function
    max_duration: Optional[str] = None
    metadata: Dict[str, Any] = None

    def __post_init__(self) -> None:
        if self.metadata is None:
            self.metadata = {}


@dataclass
class StepMetadata:
    """Metadata for a registered step."""

    name: str
    func: Callable[..., Any]
    original_func: Callable[..., Any]  # Unwrapped function
    max_retries: int = 3
    retry_delay: str = "exponential"
    timeout: Optional[int] = None
    metadata: Dict[str, Any] = None

    def __post_init__(self) -> None:
        if self.metadata is None:
            self.metadata = {}


class WorkflowRegistry:
    """
    Global registry for workflows and steps.

    This is a singleton that tracks all @workflow and @step decorated functions.
    """

    def __init__(self) -> None:
        self._workflows: Dict[str, WorkflowMetadata] = {}
        self._steps: Dict[str, StepMetadata] = {}
        self._workflow_by_func: Dict[Callable[..., Any], str] = {}
        self._step_by_func: Dict[Callable[..., Any], str] = {}

    # Workflow registration

    def register_workflow(
        self,
        name: str,
        func: Callable[..., Any],
        original_func: Callable[..., Any],
        max_duration: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> None:
        """
        Register a workflow.

        Args:
            name: Workflow name (unique identifier)
            func: Wrapped workflow function
            original_func: Original unwrapped function
            max_duration: Optional maximum duration
            metadata: Optional metadata dict
        """
        if name in self._workflows:
            existing = self._workflows[name]
            if existing.original_func is not original_func:
                raise ValueError(
                    f"Workflow name '{name}' already registered with different function"
                )
            # Allow re-registration with same function (e.g., during hot reload)
            return

        workflow_meta = WorkflowMetadata(
            name=name,
            func=func,
            original_func=original_func,
            max_duration=max_duration,
            metadata=metadata or {},
        )

        self._workflows[name] = workflow_meta
        self._workflow_by_func[func] = name
        self._workflow_by_func[original_func] = name

    def get_workflow(self, name: str) -> Optional[WorkflowMetadata]:
        """
        Get workflow metadata by name.

        Args:
            name: Workflow name

        Returns:
            WorkflowMetadata if found, None otherwise
        """
        return self._workflows.get(name)

    def get_workflow_by_func(self, func: Callable[..., Any]) -> Optional[WorkflowMetadata]:
        """
        Get workflow metadata by function reference.

        Args:
            func: Workflow function

        Returns:
            WorkflowMetadata if found, None otherwise
        """
        name = self._workflow_by_func.get(func)
        return self._workflows.get(name) if name else None

    def get_workflow_name(self, func: Callable[..., Any]) -> Optional[str]:
        """
        Get workflow name from function reference.

        Args:
            func: Workflow function

        Returns:
            Workflow name if found, None otherwise
        """
        return self._workflow_by_func.get(func)

    def list_workflows(self) -> Dict[str, WorkflowMetadata]:
        """Get all registered workflows."""
        return self._workflows.copy()

    # Step registration

    def register_step(
        self,
        name: str,
        func: Callable[..., Any],
        original_func: Callable[..., Any],
        max_retries: int = 3,
        retry_delay: str = "exponential",
        timeout: Optional[int] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> None:
        """
        Register a step.

        Args:
            name: Step name
            func: Wrapped step function
            original_func: Original unwrapped function
            max_retries: Maximum retry attempts
            retry_delay: Retry delay strategy
            timeout: Optional timeout in seconds
            metadata: Optional metadata dict
        """
        if name in self._steps:
            existing = self._steps[name]
            if existing.original_func is not original_func:
                raise ValueError(f"Step name '{name}' already registered with different function")
            # Allow re-registration
            return

        step_meta = StepMetadata(
            name=name,
            func=func,
            original_func=original_func,
            max_retries=max_retries,
            retry_delay=retry_delay,
            timeout=timeout,
            metadata=metadata or {},
        )

        self._steps[name] = step_meta
        self._step_by_func[func] = name
        self._step_by_func[original_func] = name

    def get_step(self, name: str) -> Optional[StepMetadata]:
        """
        Get step metadata by name.

        Args:
            name: Step name

        Returns:
            StepMetadata if found, None otherwise
        """
        return self._steps.get(name)

    def get_step_by_func(self, func: Callable[..., Any]) -> Optional[StepMetadata]:
        """
        Get step metadata by function reference.

        Args:
            func: Step function

        Returns:
            StepMetadata if found, None otherwise
        """
        name = self._step_by_func.get(func)
        return self._steps.get(name) if name else None

    def get_step_name(self, func: Callable[..., Any]) -> Optional[str]:
        """
        Get step name from function reference.

        Args:
            func: Step function

        Returns:
            Step name if found, None otherwise
        """
        return self._step_by_func.get(func)

    def list_steps(self) -> Dict[str, StepMetadata]:
        """Get all registered steps."""
        return self._steps.copy()

    def clear(self) -> None:
        """Clear all registrations (useful for testing)."""
        self._workflows.clear()
        self._steps.clear()
        self._workflow_by_func.clear()
        self._step_by_func.clear()


# Global singleton registry
_registry = WorkflowRegistry()


# Public API

def register_workflow(
    name: str,
    func: Callable[..., Any],
    original_func: Callable[..., Any],
    max_duration: Optional[str] = None,
    metadata: Optional[Dict[str, Any]] = None,
) -> None:
    """Register a workflow in the global registry."""
    _registry.register_workflow(name, func, original_func, max_duration, metadata)


def get_workflow(name: str) -> Optional[WorkflowMetadata]:
    """Get workflow metadata from global registry."""
    return _registry.get_workflow(name)


def get_workflow_by_func(func: Callable[..., Any]) -> Optional[WorkflowMetadata]:
    """Get workflow metadata by function from global registry."""
    return _registry.get_workflow_by_func(func)


def get_workflow_name(func: Callable[..., Any]) -> Optional[str]:
    """Get workflow name from function in global registry."""
    return _registry.get_workflow_name(func)


def list_workflows() -> Dict[str, WorkflowMetadata]:
    """List all workflows in global registry."""
    return _registry.list_workflows()


def register_step(
    name: str,
    func: Callable[..., Any],
    original_func: Callable[..., Any],
    max_retries: int = 3,
    retry_delay: str = "exponential",
    timeout: Optional[int] = None,
    metadata: Optional[Dict[str, Any]] = None,
) -> None:
    """Register a step in the global registry."""
    _registry.register_step(name, func, original_func, max_retries, retry_delay, timeout, metadata)


def get_step(name: str) -> Optional[StepMetadata]:
    """Get step metadata from global registry."""
    return _registry.get_step(name)


def get_step_by_func(func: Callable[..., Any]) -> Optional[StepMetadata]:
    """Get step metadata by function from global registry."""
    return _registry.get_step_by_func(func)


def get_step_name(func: Callable[..., Any]) -> Optional[str]:
    """Get step name from function in global registry."""
    return _registry.get_step_name(func)


def list_steps() -> Dict[str, StepMetadata]:
    """List all steps in global registry."""
    return _registry.list_steps()


def clear_registry() -> None:
    """Clear the global registry (for testing)."""
    _registry.clear()
