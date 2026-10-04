from typing import Annotated
from uuid import UUID, uuid4

from fastapi import Cookie, Response


def get_session_id(
    response: Response,
    session_id: Annotated[str | None, Cookie()] = None,
) -> UUID:
    if session_id is not None:
        try:
            return UUID(session_id)
        except ValueError:
            pass

    new_session_id = uuid4()
    response.set_cookie(
        key="session_id",
        value=str(new_session_id),
        httponly=True,
        samesite="lax",
    )
    return new_session_id
