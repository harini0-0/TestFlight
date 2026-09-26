"""Service entrypoints. Compose runs each module; local dev can run the gateway alone."""

from gateway.main import app

__all__ = ["app"]
