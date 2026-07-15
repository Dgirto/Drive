"""Conector Ruvic para Google Drive (Google Workspace) vía cuenta de
servicio con delegación de dominio."""

from .client import DriveClient
from .config import ENV_PREFIX, DriveConfig
from .exceptions import (
    DriveAuthError,
    DriveConnectorError,
    DriveDataError,
    DriveNetworkError,
)
from .logging_utils import setup_logging

__all__ = [
    "ENV_PREFIX",
    "DriveAuthError",
    "DriveClient",
    "DriveConfig",
    "DriveConnectorError",
    "DriveDataError",
    "DriveNetworkError",
    "setup_logging",
]

__version__ = "1.0.0"
