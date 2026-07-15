"""Prueba de conexión estándar del conector drive.

Firma estándar Ruvic: def test_connection() -> tuple[bool, str]
- Lee la configuración EXCLUSIVAMENTE de las env vars RUVIC_DRIVE_*.
- Nunca lanza excepciones; retorna (ok, mensaje).

Ejecutable también como script para pruebas locales:
    python test_connection.py
"""

from __future__ import annotations


def test_connection() -> tuple[bool, str]:
    """Verifica la delegación de dominio impersonando al usuario de prueba
    (RUVIC_DRIVE_DEFAULT_USER) y consultando su información de Drive."""
    try:
        from ruvic_drive_connector import (
            DriveAuthError,
            DriveClient,
            DriveConfig,
            DriveDataError,
            DriveNetworkError,
        )
    except ImportError:
        return (
            False,
            "La librería ruvic-drive-connector no está instalada. "
            "Instala con: pip install git+https://github.com/Dgirto/"
            "Drive.git#subdirectory=lib",
        )

    try:
        config = DriveConfig.from_env()
    except ValueError as exc:
        return False, str(exc)

    try:
        client = DriveClient(user_email=config.default_user, config=config)
    except DriveDataError as exc:
        return False, str(exc)

    try:
        client.ping()
    except DriveAuthError as exc:
        return False, f"Autenticación fallida: {exc}"
    except DriveNetworkError as exc:
        return False, f"Error de red: {exc}"
    except DriveDataError as exc:
        return False, f"Error de datos: {exc}"
    except Exception as exc:  # red de seguridad: jamás propagar
        return False, f"Error inesperado: {exc}"

    return (
        True,
        f"Conexión exitosa al Drive de {config.default_user} (delegación de dominio)",
    )


if __name__ == "__main__":
    ok, message = test_connection()
    print(f"{'OK' if ok else 'FALLO'}: {message}")
    raise SystemExit(0 if ok else 1)
