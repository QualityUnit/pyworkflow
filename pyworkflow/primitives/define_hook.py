"""
Typed hooks with Pydantic validation.

Provides a type-safe way to define hooks with validated payloads.
"""

from collections.abc import Awaitable, Callable
from typing import Generic, TypeVar

from pydantic import BaseModel, ValidationError

from pyworkflow.primitives.hooks import hook

T = TypeVar("T", bound=BaseModel)


class TypedHook(Generic[T]):
    """
    A hook that validates payload against a Pydantic schema.

    Provides type-safe access to hook payloads with automatic validation.
    Token is auto-generated in format "run_id:hook_id".

    Example:
        class ApprovalPayload(BaseModel):
            approved: bool
            reviewer: str
            comments: Optional[str] = None

        approval = define_hook("approval", ApprovalPayload)

        # In workflow - result is typed as ApprovalPayload
        result = await approval()
        if result.approved:
            await process_order(order_id)
    """

    def __init__(self, name: str, schema: type[T]) -> None:
        """
        Initialize a typed hook.

        Args:
            name: Hook name for logging/debugging
            schema: Pydantic model class for payload validation
        """
        self.name = name
        self.schema = schema

    async def __call__(
        self,
        *,
        timeout: str | int | None = None,
        on_created: Callable[[str], Awaitable[None]] | None = None,
    ) -> T:
        """
        Wait for external event and validate payload.

        Args:
            timeout: Optional maximum wait time:
                - str: Duration string ("24h", "7d")
                - int: Seconds
                - None: Wait forever
            on_created: Optional async callback invoked with the token when
                the hook is created. Use this to notify external systems.

        Returns:
            Validated payload as the Pydantic model type

        Raises:
            ValidationError: If payload doesn't match schema
            RuntimeError: If called outside a workflow context
        """
        payload = await hook(
            self.name,
            timeout=timeout,
            on_created=on_created,
            payload_schema=self.schema,
        )

        # Validate and return typed result
        return self.schema.model_validate(payload)

    def __repr__(self) -> str:
        return f"TypedHook(name={self.name!r}, schema={self.schema.__name__})"


def define_hook(name: str, schema: type[T]) -> TypedHook[T]:
    """
    Create a typed hook with Pydantic validation.

    This is the recommended way to create hooks when you want
    type-safe, validated payloads. Token is auto-generated in
    format "run_id:hook_id".

    Args:
        name: Hook name for logging/debugging
        schema: Pydantic model class for payload validation

    Returns:
        TypedHook instance that can be awaited in workflows

    Example:
        # Define payload schema
        class PaymentConfirmation(BaseModel):
            transaction_id: str
            amount: Decimal
            status: Literal["success", "failed"]
            timestamp: datetime

        # Create typed hook
        payment_confirmation = define_hook("payment", PaymentConfirmation)

        # Use in workflow
        @workflow
        async def payment_workflow(order_id: str):
            # Send payment request...

            # Wait for payment confirmation (typed!)
            async def notify_payment_system(token: str):
                await send_webhook_url(f"/webhook/payment/{token}")

            result: PaymentConfirmation = await payment_confirmation(
                timeout="1h",
                on_created=notify_payment_system,
            )

            if result.status == "success":
                return {"order_id": order_id, "paid": True}
            else:
                return {"order_id": order_id, "paid": False}
    """
    return TypedHook(name, schema)


class HookValidationError(Exception):
    """Raised when hook payload validation fails."""

    def __init__(
        self,
        hook_name: str,
        schema: type[BaseModel],
        validation_error: ValidationError,
    ) -> None:
        self.hook_name = hook_name
        self.schema = schema
        self.validation_error = validation_error
        super().__init__(
            f"Hook '{hook_name}' payload validation failed for schema "
            f"'{schema.__name__}': {validation_error}"
        )
