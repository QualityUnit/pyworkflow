"""Common schema types."""

from typing import Generic, TypeVar

from pydantic import BaseModel

T = TypeVar("T")


class PaginatedResponse(BaseModel, Generic[T]):
    """Base paginated response model."""

    items: list[T]
    count: int
    limit: int = 100
    offset: int = 0
