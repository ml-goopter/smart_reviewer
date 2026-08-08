from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse


class ApiError(Exception):
    """An error with a status the API contract defines.

    `code` is a stable machine-readable string, never a human sentence and
    never anything derived from an exception: the frontend maps status codes to
    fixed customer-facing copy, and leaking internal detail here would put
    database or provider messages on a public page.
    """

    def __init__(self, status_code: int, code: str) -> None:
        super().__init__(code)
        self.status_code = status_code
        self.code = code


def install_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(ApiError)
    async def _api_error(_: Request, exc: ApiError) -> JSONResponse:
        return JSONResponse(status_code=exc.status_code, content={"error": exc.code})

    @app.exception_handler(RequestValidationError)
    async def _validation_error(_: Request, __: RequestValidationError) -> JSONResponse:
        # The contract specifies 400 for a malformed merchant or suggestion id;
        # FastAPI's default 422 with a field-by-field breakdown is both off-spec
        # and more detail than a public endpoint should volunteer.
        return JSONResponse(status_code=400, content={"error": "invalid_request"})
