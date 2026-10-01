"""Add application errors and security to FastAPI's generated document.

Run ``uvicorn examples.fastapi_augment.app:app`` and open
http://127.0.0.1:8000/docs.
"""

from __future__ import annotations

from typing import Any, Optional

from fastapi import APIRouter, FastAPI, Header, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from qstd_openapi import OpenAPI
from qstd_openapi.contrib.app_errors import AppErrors
from qstd_openapi.fastapi import OpenAPIRouter, augment


class ApplicationError(Exception):
    code: int
    message: str
    status_code = 500

    def to_dict(self) -> dict[str, Any]:
        return {
            'code': self.code,
            'error': type(self).__name__,
            'message': self.message,
        }


class UserAlreadyExistsError(ApplicationError):
    code = 1001
    message = 'User already exists'
    status_code = 409


class UserRegisterInput(BaseModel):
    email: str
    password: str = Field(min_length=8)


class UserDTO(BaseModel):
    id: int
    email: str


users = OpenAPIRouter(APIRouter(prefix='/users', tags=['Users']))


@users.post(
    '/register',
    response_model=UserDTO,
    status_code=201,
    errors=[UserAlreadyExistsError],
)
async def register_user(body: UserRegisterInput) -> UserDTO:
    """Register a user."""
    if body.email == 'existing@example.com':
        raise UserAlreadyExistsError()
    return UserDTO(id=1, email=body.email)


@users.get(
    '/me',
    response_model=UserDTO,
    security='UserSession',
)
async def get_profile(
    x_session: Optional[str] = Header(None, alias='X-Session'),
) -> UserDTO:
    """Return the current user's profile."""
    return UserDTO(id=1, email='user@example.com')


app = FastAPI(title='Users API', version='1.0.0')
app.include_router(users.router)


@app.exception_handler(ApplicationError)
async def handle_application_error(
    request: Request,
    error: ApplicationError,
) -> JSONResponse:
    return JSONResponse(error.to_dict(), status_code=error.status_code)


spec = OpenAPI(
    info={'title': 'Users API', 'version': '1.0.0'},
    security_schemes={
        'UserSession': {
            'type': 'apiKey',
            'in': 'header',
            'name': 'X-Session',
        },
    },
    errors=[AppErrors(ApplicationError)],
)
augment(app, spec)
