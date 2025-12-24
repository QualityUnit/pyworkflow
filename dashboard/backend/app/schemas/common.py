"""Common schema types."""

from typing import Generic, List, TypeVar
from pydantic import BaseModel

T = TypeVar("T")


class PaginatedResponse(BaseModel, Generic[T]):
    """Base paginated response model."""

    items: List[T]
    count: int
    limit: int = 100
    offset: int = 0
