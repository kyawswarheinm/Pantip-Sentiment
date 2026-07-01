"""Database package — exposes db_session and get_client."""

from .client import db_session, get_client

__all__ = ["db_session", "get_client"]
