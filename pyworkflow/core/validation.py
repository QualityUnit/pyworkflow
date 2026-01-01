"""
Pydantic validation for step parameters.

Validates step function arguments against their type hints using Pydantic's
TypeAdapter for runtime type checking.
"""

import inspect
from collections.abc import Callable
from typing import Any, get_type_hints

from pydantic import TypeAdapter, ValidationError

from pyworkflow.core.exceptions import FatalError


class StepValidationError(FatalError):
    """
    Raised when step parameter validation fails.

    This is a FatalError subclass to ensure validation failures
    immediately fail the workflow without retries.
    """

    def __init__(
        self,
        step_name: str,
        param_name: str,
        expected_type: type,
        received_value: Any,
        validation_error: ValidationError,
    ) -> None:
        self.step_name = step_name
        self.param_name = param_name
        self.expected_type = expected_type
        self.received_value = received_value
        self.validation_error = validation_error

        # Build clear error message
        error_details = str(validation_error)
        message = (
            f"Step '{step_name}' parameter validation failed for '{param_name}': "
            f"expected {expected_type}, got {type(received_value).__name__} "
            f"with value {received_value!r}. Details: {error_details}"
        )
        super().__init__(message)


def validate_step_parameters(
    func: Callable,
    args: tuple,
    kwargs: dict,
    step_name: str,
) -> None:
    """
    Validate step parameters against their type hints using Pydantic.

    Only parameters with type annotations are validated. Parameters without
    type hints are skipped.

    Args:
        func: The step function (original, unwrapped)
        args: Positional arguments passed to the step
        kwargs: Keyword arguments passed to the step
        step_name: Name of the step for error messages

    Raises:
        StepValidationError: If any typed parameter fails validation
    """
    # Get function signature and type hints
    sig = inspect.signature(func)

    try:
        # Try to get type hints, may fail for some edge cases
        type_hints = get_type_hints(func)
    except Exception:
        # If we can't get type hints, skip validation
        return

    if not type_hints:
        # No type hints at all, skip validation
        return

    # Bind arguments to parameters
    try:
        bound = sig.bind(*args, **kwargs)
        bound.apply_defaults()
    except TypeError:
        # If binding fails, the function call itself will fail
        # Let the normal execution handle this
        return

    # Validate each parameter that has a type hint
    for param_name, param_value in bound.arguments.items():
        if param_name not in type_hints:
            # No type hint for this parameter, skip validation
            continue

        expected_type = type_hints[param_name]

        try:
            # Use Pydantic TypeAdapter for validation
            adapter = TypeAdapter(expected_type)
            adapter.validate_python(param_value)
        except ValidationError as e:
            raise StepValidationError(
                step_name=step_name,
                param_name=param_name,
                expected_type=expected_type,
                received_value=param_value,
                validation_error=e,
            )
