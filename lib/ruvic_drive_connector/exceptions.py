"""Excepciones propias del conector Drive.

Separan los tres tipos de fallo que el usuario debe distinguir:
autenticación, red/servidor y datos. Nunca exponemos excepciones
crípticas del cliente HTTP subyacente.
"""


class DriveConnectorError(Exception):
    """Error base del conector."""


class DriveAuthError(DriveConnectorError):
    """Credenciales inválidas o delegación de dominio no autorizada para el usuario impersonado."""


class DriveNetworkError(DriveConnectorError):
    """No se pudo alcanzar la API de Drive (red, timeout, error temporal del servidor)."""


class DriveDataError(DriveConnectorError):
    """La operación es válida pero el recurso no existe o los datos son inválidos."""
