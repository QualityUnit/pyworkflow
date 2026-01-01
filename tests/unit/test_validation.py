"""
Unit tests for step parameter validation.
"""

from typing import Any

import pytest
from pydantic import BaseModel

from pyworkflow.core.exceptions import FatalError
from pyworkflow.core.validation import (
    StepValidationError,
    validate_step_parameters,
)


class TestStepValidationError:
    """Test the StepValidationError exception."""

    def test_is_fatal_error(self):
        """Test that StepValidationError is a FatalError subclass."""
        assert issubclass(StepValidationError, FatalError)

    def test_error_message_format(self):
        """Test that error message contains expected information."""
        from pydantic import ValidationError

        # Create a validation error
        try:
            from pydantic import TypeAdapter

            TypeAdapter(int).validate_python("not_an_int")
        except ValidationError as e:
            error = StepValidationError(
                step_name="my_step",
                param_name="x",
                expected_type=int,
                received_value="not_an_int",
                validation_error=e,
            )

            assert "my_step" in str(error)
            assert "x" in str(error)
            assert "int" in str(error)
            assert "not_an_int" in str(error)


class TestValidateStepParameters:
    """Test the validate_step_parameters function."""

    def test_validates_typed_int_parameter(self):
        """Test that typed int parameters are validated."""

        async def my_step(x: int):
            return x * 2

        # Valid call - should not raise
        validate_step_parameters(my_step, (42,), {}, "my_step")

        # Invalid call - should raise
        with pytest.raises(StepValidationError) as exc_info:
            validate_step_parameters(my_step, ("not_an_int",), {}, "my_step")

        assert "x" in str(exc_info.value)
        assert "my_step" in str(exc_info.value)

    def test_validates_typed_str_parameter(self):
        """Test that typed str parameters are validated."""

        async def my_step(name: str):
            return name

        # Valid call
        validate_step_parameters(my_step, ("hello",), {}, "my_step")

        # Pydantic does not coerce int to str by default
        with pytest.raises(StepValidationError):
            validate_step_parameters(my_step, (42,), {}, "my_step")

    def test_validates_typed_float_parameter(self):
        """Test that typed float parameters are validated."""

        async def my_step(amount: float):
            return amount

        # Valid call
        validate_step_parameters(my_step, (99.99,), {}, "my_step")

        # Int can be coerced to float
        validate_step_parameters(my_step, (100,), {}, "my_step")

    def test_skips_untyped_parameters(self):
        """Test that untyped parameters are skipped."""

        async def my_step(typed: int, untyped):
            return typed + untyped

        # Should validate 'typed' but skip 'untyped'
        validate_step_parameters(my_step, (42, "anything"), {}, "my_step")

        # Invalid typed parameter should fail
        with pytest.raises(StepValidationError):
            validate_step_parameters(my_step, ("invalid", "anything"), {}, "my_step")

    def test_validates_pydantic_models(self):
        """Test validation with Pydantic models."""

        class Order(BaseModel):
            id: str
            amount: float

        async def process_order(order: Order):
            return order.id

        # Valid Pydantic model
        valid_order = Order(id="123", amount=99.99)
        validate_step_parameters(process_order, (valid_order,), {}, "process_order")

        # Dict that can be coerced to model
        validate_step_parameters(
            process_order,
            ({"id": "123", "amount": 99.99},),
            {},
            "process_order",
        )

        # Invalid data - missing required field
        with pytest.raises(StepValidationError):
            validate_step_parameters(
                process_order,
                ({"id": "123"},),  # missing 'amount'
                {},
                "process_order",
            )

    def test_validates_kwargs(self):
        """Test that keyword arguments are validated."""

        async def my_step(x: int):
            return x

        # Valid kwargs
        validate_step_parameters(my_step, (), {"x": 42}, "my_step")

        # Invalid kwargs
        with pytest.raises(StepValidationError):
            validate_step_parameters(my_step, (), {"x": "invalid"}, "my_step")

    def test_validates_mixed_args_and_kwargs(self):
        """Test validation with both args and kwargs."""

        async def my_step(x: int, y: str):
            return f"{x}_{y}"

        # Args only
        validate_step_parameters(my_step, (42, "hello"), {}, "my_step")

        # Kwargs only
        validate_step_parameters(my_step, (), {"x": 42, "y": "hello"}, "my_step")

        # Mixed
        validate_step_parameters(my_step, (42,), {"y": "hello"}, "my_step")

    def test_handles_optional_types(self):
        """Test validation with Optional types."""

        async def my_step(x: int | None):
            return x

        validate_step_parameters(my_step, (42,), {}, "my_step")
        validate_step_parameters(my_step, (None,), {}, "my_step")

        with pytest.raises(StepValidationError):
            validate_step_parameters(my_step, ("invalid",), {}, "my_step")

    def test_handles_union_types(self):
        """Test validation with Union types."""

        async def my_step(x: int | str):
            return x

        validate_step_parameters(my_step, (42,), {}, "my_step")
        validate_step_parameters(my_step, ("hello",), {}, "my_step")

        # List is not int or str
        with pytest.raises(StepValidationError):
            validate_step_parameters(my_step, ([1, 2, 3],), {}, "my_step")

    def test_handles_list_types(self):
        """Test validation with List types."""

        async def my_step(items: list[int]):
            return sum(items)

        validate_step_parameters(my_step, ([1, 2, 3],), {}, "my_step")

        # List of strings should fail
        with pytest.raises(StepValidationError):
            validate_step_parameters(my_step, (["a", "b"],), {}, "my_step")

    def test_handles_dict_types(self):
        """Test validation with Dict types."""

        async def my_step(data: dict[str, int]):
            return data

        validate_step_parameters(my_step, ({"a": 1, "b": 2},), {}, "my_step")

        # Dict with wrong value type
        with pytest.raises(StepValidationError):
            validate_step_parameters(my_step, ({"a": "not_int"},), {}, "my_step")

    def test_handles_any_type(self):
        """Test validation with Any type - should accept anything."""

        async def my_step(x: Any):
            return x

        validate_step_parameters(my_step, (42,), {}, "my_step")
        validate_step_parameters(my_step, ("hello",), {}, "my_step")
        validate_step_parameters(my_step, ([1, 2, 3],), {}, "my_step")
        validate_step_parameters(my_step, (None,), {}, "my_step")

    def test_handles_no_type_hints(self):
        """Test that functions without type hints are skipped."""

        async def untyped_step(x, y, z):
            return x + y + z

        # Should not raise, even with any data types
        validate_step_parameters(untyped_step, ("a", "b", "c"), {}, "untyped_step")
        validate_step_parameters(untyped_step, (1, 2, 3), {}, "untyped_step")

    def test_handles_default_values(self):
        """Test validation with default parameter values."""

        async def my_step(x: int, y: str = "default"):
            return f"{x}_{y}"

        # Without optional param
        validate_step_parameters(my_step, (42,), {}, "my_step")

        # With optional param
        validate_step_parameters(my_step, (42, "custom"), {}, "my_step")

        # With invalid optional param
        with pytest.raises(StepValidationError):
            validate_step_parameters(my_step, (42, 123), {}, "my_step")

    def test_handles_sync_functions(self):
        """Test validation with synchronous functions."""

        def sync_step(x: int):
            return x * 2

        validate_step_parameters(sync_step, (42,), {}, "sync_step")

        with pytest.raises(StepValidationError):
            validate_step_parameters(sync_step, ("not_int",), {}, "sync_step")

    def test_handles_nested_pydantic_models(self):
        """Test validation with nested Pydantic models."""

        class Address(BaseModel):
            street: str
            city: str

        class Customer(BaseModel):
            name: str
            address: Address

        async def process_customer(customer: Customer):
            return customer.name

        # Valid nested model
        valid_customer = Customer(
            name="John",
            address=Address(street="123 Main St", city="NYC"),
        )
        validate_step_parameters(process_customer, (valid_customer,), {}, "process_customer")

        # Valid dict representation
        validate_step_parameters(
            process_customer,
            ({"name": "John", "address": {"street": "123 Main St", "city": "NYC"}},),
            {},
            "process_customer",
        )

        # Invalid - missing nested field
        with pytest.raises(StepValidationError):
            validate_step_parameters(
                process_customer,
                ({"name": "John", "address": {"street": "123 Main St"}},),  # missing city
                {},
                "process_customer",
            )

    def test_handles_empty_args(self):
        """Test validation with no arguments."""

        async def no_args_step() -> str:
            return "done"

        # Should not raise
        validate_step_parameters(no_args_step, (), {}, "no_args_step")

    def test_step_validation_error_attributes(self):
        """Test that StepValidationError stores all relevant attributes."""

        async def my_step(x: int):
            return x

        try:
            validate_step_parameters(my_step, ("invalid",), {}, "my_step")
            pytest.fail("Should have raised StepValidationError")
        except StepValidationError as e:
            assert e.step_name == "my_step"
            assert e.param_name == "x"
            assert e.expected_type is int
            assert e.received_value == "invalid"
            assert e.validation_error is not None
