from pydantic import BaseModel
from typing import TypeVar, Generic, Sequence
from fastapi import Query

T = TypeVar("T")


class PaginationParams(BaseModel):
    page: int = 1
    page_size: int = 20

    @property
    def offset(self) -> int:
        return (self.page - 1) * self.page_size

    @property
    def limit(self) -> int:
        return self.page_size


class Page(BaseModel, Generic[T]):
    items: Sequence[T]
    total: int
    page: int
    page_size: int
    pages: int

    @classmethod
    def create(cls, items: Sequence[T], total: int, params: PaginationParams) -> "Page[T]":
        pages = max(1, -(-total // params.page_size))  # ceil division
        return cls(
            items=items,
            total=total,
            page=params.page,
            page_size=params.page_size,
            pages=pages,
        )


def pagination_params(
    page: int = Query(default=1, ge=1, description="Número da página"),
    page_size: int = Query(default=20, ge=1, le=100, description="Itens por página"),
) -> PaginationParams:
    return PaginationParams(page=page, page_size=page_size)
