"""Sample Python module for testing."""

import os
from pathlib import Path


def authenticate_user(username: str, password: str) -> bool:
    """Authenticate a user with username and password."""
    if not username or not password:
        return False
    return username == "admin" and password == "secret"


class UserService:
    """Service for managing users."""

    def __init__(self, db_connection):
        self.db = db_connection

    def get_user(self, user_id: int) -> dict:
        """Fetch a user by ID."""
        return self.db.query(f"SELECT * FROM users WHERE id = {user_id}")

    def create_user(self, name: str, email: str) -> dict:
        """Create a new user."""
        return {"name": name, "email": email}


def handle_error(error: Exception) -> str:
    """Handle an error and return a message."""
    return f"Error occurred: {error}"
