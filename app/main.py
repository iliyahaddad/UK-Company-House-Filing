"""FastAPI application: wiring, error handling, startup checks."""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from . import config
from .accounting.rules import ConflictError, DomainError, NotFoundError
from .api.routes import router
from .db.database import CredentialDecryptionError, init_db
from .security import install_security
from .xbrl.postprocess import PostProcessError

log = logging.getLogger("ukaccounts")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    if config.IS_PRODUCTION:
        problems = config.production_problems()
        if problems:
            raise RuntimeError("Refusing to start with APP_ENV=production: " + "; ".join(problems))
    else:
        log.warning(
            "Running with APP_ENV=%s (not production). Do not expose this process to the internet.",
            config.APP_ENV,
        )
    yield


app = FastAPI(title="UK Accounts - Companies House Filing", version="4.1.0", lifespan=lifespan)
install_security(app)
app.include_router(router)
app.mount("/static", StaticFiles(directory="app/web/static"), name="static")


@app.exception_handler(NotFoundError)
def handle_not_found(request: Request, exc: NotFoundError):
    return JSONResponse({"success": False, "error": str(exc)}, status_code=404)


@app.exception_handler(ConflictError)
def handle_conflict(request: Request, exc: ConflictError):
    return JSONResponse({"success": False, "error": str(exc)}, status_code=409)


@app.exception_handler(DomainError)
def handle_domain_error(request: Request, exc: DomainError):
    return JSONResponse({"success": False, "error": str(exc)}, status_code=400)


@app.exception_handler(PostProcessError)
def handle_postprocess_error(request: Request, exc: PostProcessError):
    return JSONResponse({"success": False, "error": f"Could not repair the generated iXBRL: {exc}"}, status_code=422)


@app.exception_handler(CredentialDecryptionError)
def handle_credential_error(request: Request, exc: CredentialDecryptionError):
    return JSONResponse({"success": False, "error": str(exc)}, status_code=409)


@app.exception_handler(Exception)
def handle_unexpected(request: Request, exc: Exception):
    log.exception("Unhandled error on %s %s", request.method, request.url.path)
    return JSONResponse({"success": False, "error": "Internal server error"}, status_code=500)


@app.get("/health")
def health():
    return {"status": "ok"}
