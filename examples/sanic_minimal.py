"""A minimal Sanic application with generated OpenAPI documentation.

Run ``sanic examples.sanic_minimal:app`` and open http://127.0.0.1:8000/docs.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from pydantic import BaseModel, Field
from sanic import Blueprint, Request, Sanic, response

from qstd_openapi import OpenAPI
from qstd_openapi.sanic import OpenAPIBlueprint, SanicRoutes, mount
from qstd_openapi.ui import Redoc


class UserRegisterInput(BaseModel):
    email: str
    password: str = Field(min_length=8)


class UserDTO(BaseModel):
    id: int
    email: str
    created_at: datetime


users = OpenAPIBlueprint(Blueprint('Users', url_prefix='/users'))


@users.post(
    '/register',
    tags=['Users'],
    body=UserRegisterInput,
    responses={201: UserDTO},
    body_examples={
        'standard': {
            'email': 'user@example.com',
            'password': 'example-passphrase',
        },
    },
)
async def register_user(request: Request) -> Any:
    """Register a user."""
    payload = UserRegisterInput.model_validate(request.json)
    user = UserDTO(
        id=1,
        email=payload.email,
        created_at=datetime.now(timezone.utc),
    )
    return response.json(user.model_dump(mode='json'), status=201)


app = Sanic('users_minimal')
app.blueprint(users.blueprint)

spec = OpenAPI(info={'title': 'Users API', 'version': '1.0.0'})
spec.include(SanicRoutes(app))
mount(app, spec, json_path='/openapi.json', ui={'/docs': Redoc()})
