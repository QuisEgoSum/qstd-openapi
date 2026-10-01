"""A small Sanic service with errors, authentication and a webhook.

Run ``sanic examples.sanic_service.app:app`` and open
http://127.0.0.1:8000/docs.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sanic import Blueprint, Request, Sanic, response

from qstd_openapi import OpenAPI, WebhookSet, openapi
from qstd_openapi.contrib.app_errors import AppErrors
from qstd_openapi.sanic import OpenAPIBlueprint, SanicRoutes, mount
from qstd_openapi.ui import Redoc, SwaggerUI

from .auth import require_session
from .errors import ApplicationError, UserAlreadyExistsError
from .models import UserDTO, UserRegisteredEvent, UserRegisterInput

SECURITY_SCHEMES = {
    'UserSession': {
        'type': 'apiKey',
        'in': 'header',
        'name': 'X-Session',
    },
}

users = OpenAPIBlueprint(Blueprint('Users', url_prefix='/users'))
profiles = OpenAPIBlueprint(Blueprint('Profiles', url_prefix='/profile'))


@users.post(
    '/register',
    body=UserRegisterInput,
    responses={201: UserDTO},
    errors=[UserAlreadyExistsError],
)
async def register_user(request: Request) -> Any:
    """Register a user."""
    payload = UserRegisterInput.model_validate(request.json)
    if payload.email == 'existing@example.com':
        raise UserAlreadyExistsError(email=payload.email)
    user = UserDTO(
        id=1,
        email=payload.email,
        display_name=payload.display_name,
        created_at=datetime.now(timezone.utc),
    )
    return response.json(user.model_dump(mode='json'), status=201)


@profiles.get('/', response=UserDTO)
@require_session
async def get_profile(request: Request) -> Any:
    """Return the current user's profile."""
    user = UserDTO(
        id=1,
        email='user@example.com',
        display_name='Example User',
        created_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
    )
    return response.json(user.model_dump(mode='json'))


webhooks = WebhookSet()


@webhooks.register('user.registered')
@openapi.body(UserRegisteredEvent)
async def send_user_registered(event: UserRegisteredEvent) -> None:
    """Notify a client after a successful registration."""


app = Sanic('users_service')
app.blueprint(users.blueprint)
app.blueprint(profiles.blueprint)


@app.exception(  # pyright: ignore[reportUnknownMemberType, reportUntypedFunctionDecorator]
    ApplicationError,
)
async def handle_application_error(
    request: Request,
    error: ApplicationError,
) -> Any:
    return response.json(error.to_dict(), status=error.status_code)


def build_spec() -> OpenAPI:
    spec = OpenAPI(
        info={'title': 'Users API', 'version': '1.0.0'},
        security_schemes=SECURITY_SCHEMES,
        errors=[AppErrors(ApplicationError)],
    )
    spec.include(SanicRoutes(app), webhooks)
    return spec


spec = build_spec()
mount(
    app,
    spec,
    json_path='/openapi.json',
    yaml_path='/openapi.yaml',
    ui={'/docs': Redoc(), '/swagger': SwaggerUI()},
)
