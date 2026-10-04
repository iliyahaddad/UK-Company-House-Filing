#!/usr/bin/env python3
"""Development entry point.

    python run.py

Binds to 127.0.0.1 only. For anything beyond your own machine, run behind a
real WSGI/ASGI server (uvicorn/gunicorn) with TLS in front of it, and set
APP_ENV=production, AUTH_USER/AUTH_PASSWORD and CH_CREDENTIALS_KEY first -
the app refuses to start in production otherwise.
"""
import os

import uvicorn

if __name__ == "__main__":
    host = os.getenv("HOST", "127.0.0.1")
    if host not in ("127.0.0.1", "localhost", "::1"):
        print(f"Refusing to bind to {host}: run.py is for local development only. "
              "Use uvicorn/gunicorn directly for anything else.")
        raise SystemExit(1)
    uvicorn.run("app.main:app", host=host, port=int(os.getenv("PORT", "8000")),
                reload=os.getenv("APP_ENV", "development") != "production")
