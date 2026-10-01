"""Request, response and webhook models used by the Sanic example."""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field


class UserRegisterInput(BaseModel):
    email: str
    password: str = Field(min_length=8)
    display_name: Optional[str] = None


class UserDTO(BaseModel):
    id: int
    email: str
    created_at: datetime
    display_name: Optional[str] = None


class UserRegisteredEvent(BaseModel):
    user_id: int
    email: str
