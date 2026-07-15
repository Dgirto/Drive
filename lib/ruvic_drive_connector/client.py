"""Cliente de Google Drive (Google Workspace) vía cuenta de servicio con
delegación de dominio.

Mismo patrón de autenticación que ruvic_gmail_workspace_connector
(CON-005.2): el constructor recibe el usuario del dominio a impersonar,
y una sola credencial (esta cuenta de servicio) puede actuar como
cualquier usuario autorizado del dominio sin volver a autorizar por
usuario ni gestionar expiración de tokens.

Capacidades:
- list_files():     buscar/listar archivos con filtros (sintaxis de
                     búsqueda de Drive).
- get_file():        leer los metadatos de un archivo.
- download_file():   descargar el contenido de un archivo a disco local.
- upload_file():     subir un archivo local a Drive.

Las credenciales SIEMPRE provienen de variables de entorno
RUVIC_DRIVE_* (ver config.DriveConfig.from_env). Prohibido hardcodearlas.
"""

from __future__ import annotations

import mimetypes
import re
import socket
from pathlib import Path
from typing import Any

from google.auth.exceptions import GoogleAuthError, RefreshError
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from googleapiclient.http import MediaFileUpload, MediaIoBaseDownload

from .config import DriveConfig
from .exceptions import (
    DriveAuthError,
    DriveConnectorError,
    DriveDataError,
    DriveNetworkError,
)
from .logging_utils import get_logger

_SCOPES = ["https://www.googleapis.com/auth/drive"]
_MAX_UPLOAD_BYTES = 20 * 1024 * 1024
_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
_FILE_FIELDS = "id, name, mimeType, size, modifiedTime, webViewLink, parents, owners(emailAddress)"


def _wrap_http_error(exc: HttpError) -> DriveConnectorError:
    """Traduce un error HTTP de la API de Drive a una excepción propia,
    sin dejar escapar nunca el tipo crudo del cliente HTTP."""
    status = exc.resp.status if getattr(exc, "resp", None) is not None else None
    if status in (401, 403):
        return DriveAuthError(
            "Credenciales inválidas o sin permiso suficiente sobre este "
            "recurso. Verifica que el Client ID de la cuenta de servicio "
            "esté autorizado en el Admin Console de Workspace con el "
            "scope drive."
        )
    if status == 404:
        return DriveDataError("El archivo o recurso solicitado no existe.")
    if status == 429 or (status is not None and status >= 500):
        return DriveNetworkError(
            f"Drive API no respondió correctamente (HTTP {status}). "
            "Puede ser un límite de cuota temporal; reintenta en unos segundos."
        )
    return DriveDataError(f"Error de Drive API (HTTP {status}): {exc}")


class DriveClient:
    """Cliente de Google Drive para un usuario específico de un dominio
    Google Workspace, vía cuenta de servicio con delegación de dominio.

    Args:
        user_email: correo del usuario del dominio a impersonar (ej.
            "facturacion@tuempresa.com"). La cuenta de servicio debe estar
            autorizada en el Admin Console para el dominio de ese correo.
            El conector opera sobre el Drive de ese usuario (su unidad
            personal y las unidades compartidas a las que tenga acceso).
        config: configuración de conexión. Si se omite, se lee de las
            variables de entorno RUVIC_DRIVE_* (comportamiento estándar
            en el runtime de la plataforma).

    Ejemplo:
        >>> client = DriveClient(user_email="facturacion@tuempresa.com")
        >>> client.list_files(query="name contains 'reporte'", max_results=5)
        [{'id': '1a2b3c', 'name': 'reporte.pdf', 'mimeType': 'application/pdf', ...}]
    """

    def __init__(self, user_email: str, config: DriveConfig | None = None) -> None:
        if not _EMAIL_RE.match(user_email):
            raise DriveDataError(
                f"user_email={user_email!r} no parece un correo válido "
                "(ej. 'facturacion@tuempresa.com')."
            )
        self.user_email = user_email
        self.config = config or DriveConfig.from_env()
        self._logger = get_logger()
        self._service: Any = None

    # ------------------------------------------------------------------ #
    # Conexión
    # ------------------------------------------------------------------ #

    def _get_service(self) -> Any:
        if self._service is not None:
            return self._service
        try:
            credentials = service_account.Credentials.from_service_account_info(
                self.config.service_account_info,
                scopes=_SCOPES,
                subject=self.user_email,
            )
        except (ValueError, KeyError) as exc:
            raise DriveAuthError(
                f"El JSON de la cuenta de servicio es inválido o le faltan campos: {exc}"
            ) from exc
        try:
            self._service = build(
                "drive",
                "v3",
                credentials=credentials,
                cache_discovery=False,
                static_discovery=False,
            )
        except (GoogleAuthError, OSError) as exc:
            raise DriveNetworkError(
                f"No se pudo inicializar el cliente de Drive: {exc}"
            ) from exc
        return self._service

    def ping(self) -> bool:
        """Verifica la conexión consultando el 'Acerca de' del usuario impersonado.

        Returns:
            True si la conexión y la delegación funcionan.

        Raises:
            DriveAuthError / DriveNetworkError / DriveDataError.
        """
        service = self._get_service()
        try:
            about = service.about().get(fields="user(emailAddress)").execute(num_retries=1)
        except HttpError as exc:
            raise _wrap_http_error(exc) from exc
        except RefreshError as exc:
            client_id = self.config.service_account_info.get("client_id", "?")
            raise DriveAuthError(
                f"No se pudo autenticar como {self.user_email!r} (unauthorized_client). "
                "Revisa en el Admin Console de Google Workspace (Seguridad -> Control "
                "de acceso a las API -> Delegación en todo el dominio) que: "
                f"1) el Client ID '{client_id}' esté agregado, "
                "2) los scopes autorizados incluyan exactamente "
                "'https://www.googleapis.com/auth/drive', y 3) el usuario "
                "pertenezca a ese mismo dominio."
            ) from exc
        except (socket.error, TimeoutError, OSError) as exc:
            raise DriveNetworkError(
                f"No se pudo conectar con Drive API: {exc}"
            ) from exc
        self._logger.info(
            "Ping exitoso, usuario: %s", about.get("user", {}).get("emailAddress")
        )
        return True

    # ------------------------------------------------------------------ #
    # Capacidad 1 — Buscar/listar archivos con filtros
    # ------------------------------------------------------------------ #

    def list_files(self, query: str = "", max_results: int = 20) -> list[dict[str, Any]]:
        """Busca archivos del usuario impersonado usando la sintaxis de
        búsqueda de Drive.

        Args:
            query: filtro de búsqueda de Drive (ej. "name contains 'factura'",
                "mimeType = 'application/pdf'"). Cadena vacía = todos.
            max_results: máximo de archivos a retornar (default 20, máximo 100).

        Returns:
            Lista de dicts: {"id", "name", "mime_type", "size", "modified_time", "web_view_link"}.

        Ejemplo:
            >>> client.list_files(query="name contains 'reporte'", max_results=5)
            [{'id': '1a2b3c', 'name': 'reporte.pdf', ...}]
        """
        service = self._get_service()
        max_results = max(1, min(int(max_results), 100))
        try:
            resp = (
                service.files()
                .list(
                    q=query or None,
                    pageSize=max_results,
                    fields=f"files({_FILE_FIELDS})",
                    supportsAllDrives=True,
                    includeItemsFromAllDrives=True,
                )
                .execute(num_retries=1)
            )
        except HttpError as exc:
            raise _wrap_http_error(exc) from exc

        results = [_format_file(f) for f in resp.get("files", [])]
        self._logger.info(
            "Se listaron %d archivos de %s (query=%r)", len(results), self.user_email, query
        )
        return results

    # ------------------------------------------------------------------ #
    # Capacidad 2 — Leer los metadatos de un archivo
    # ------------------------------------------------------------------ #

    def get_file(self, file_id: str) -> dict[str, Any]:
        """Obtiene los metadatos completos de un archivo.

        Args:
            file_id: ID del archivo (obtenido de list_files).

        Returns:
            Dict con: id, name, mime_type, size, modified_time, web_view_link, owner.

        Ejemplo:
            >>> client.get_file("1a2b3c")
            {'id': '1a2b3c', 'name': 'reporte.pdf', 'mime_type': 'application/pdf', ...}
        """
        service = self._get_service()
        try:
            f = (
                service.files()
                .get(fileId=file_id, fields=_FILE_FIELDS, supportsAllDrives=True)
                .execute(num_retries=1)
            )
        except HttpError as exc:
            raise _wrap_http_error(exc) from exc
        return _format_file(f)

    # ------------------------------------------------------------------ #
    # Capacidad 3 — Descargar el contenido de un archivo
    # ------------------------------------------------------------------ #

    def download_file(self, file_id: str, destination_path: str) -> str:
        """Descarga el contenido de un archivo a una ruta local.

        Los archivos nativos de Google (Docs, Sheets, Slides) se exportan
        automáticamente a un formato descargable (PDF); el resto se
        descarga tal cual.

        Args:
            file_id: ID del archivo a descargar.
            destination_path: ruta local donde guardar el archivo.

        Returns:
            La ruta local donde quedó guardado el archivo.

        Ejemplo:
            >>> client.download_file("1a2b3c", "/tmp/reporte.pdf")
            '/tmp/reporte.pdf'
        """
        service = self._get_service()
        try:
            meta = (
                service.files()
                .get(fileId=file_id, fields="mimeType, name", supportsAllDrives=True)
                .execute(num_retries=1)
            )
        except HttpError as exc:
            raise _wrap_http_error(exc) from exc

        mime_type = meta.get("mimeType", "")
        try:
            if mime_type.startswith("application/vnd.google-apps"):
                request = service.files().export_media(
                    fileId=file_id, mimeType="application/pdf"
                )
            else:
                request = service.files().get_media(fileId=file_id, supportsAllDrives=True)
        except HttpError as exc:
            raise _wrap_http_error(exc) from exc

        dest = Path(destination_path)
        dest.parent.mkdir(parents=True, exist_ok=True)
        try:
            with dest.open("wb") as fh:
                downloader = MediaIoBaseDownload(fh, request)
                done = False
                while not done:
                    _, done = downloader.next_chunk(num_retries=1)
        except HttpError as exc:
            raise _wrap_http_error(exc) from exc

        self._logger.info(
            "Archivo '%s' descargado en %s (usuario %s)",
            meta.get("name"), destination_path, self.user_email,
        )
        return str(dest)

    # ------------------------------------------------------------------ #
    # Capacidad 4 — Subir un archivo local a Drive
    # ------------------------------------------------------------------ #

    def upload_file(
        self,
        local_path: str,
        name: str | None = None,
        parent_folder_id: str | None = None,
    ) -> dict[str, Any]:
        """Sube un archivo local al Drive del usuario impersonado.

        Args:
            local_path: ruta local del archivo a subir (máx. 20 MB).
            name: nombre del archivo en Drive (default: nombre del archivo local).
            parent_folder_id: ID de la carpeta destino (default: raíz de Mi unidad).

        Returns:
            Dict con: id, name, mime_type, web_view_link.

        Ejemplo:
            >>> client.upload_file("/tmp/reporte.pdf", parent_folder_id="1xYz")
            {'id': '1a2b3c', 'name': 'reporte.pdf', ...}
        """
        path = Path(local_path)
        if not path.is_file():
            raise DriveDataError(f"El archivo a subir no existe: {local_path}")
        size = path.stat().st_size
        if size > _MAX_UPLOAD_BYTES:
            raise DriveDataError(
                f"El archivo pesa {size / 1_048_576:.1f} MB, supera el límite de "
                f"{_MAX_UPLOAD_BYTES / 1_048_576:.0f} MB soportado por el conector."
            )

        service = self._get_service()
        content_type, _ = mimetypes.guess_type(path.name)
        content_type = content_type or "application/octet-stream"
        file_metadata: dict[str, Any] = {"name": name or path.name}
        if parent_folder_id:
            file_metadata["parents"] = [parent_folder_id]
        media = MediaFileUpload(str(path), mimetype=content_type, resumable=False)
        try:
            created = (
                service.files()
                .create(
                    body=file_metadata,
                    media_body=media,
                    fields=_FILE_FIELDS,
                    supportsAllDrives=True,
                )
                .execute(num_retries=1)
            )
        except HttpError as exc:
            raise _wrap_http_error(exc) from exc
        self._logger.info(
            "Archivo '%s' subido al Drive de %s", created.get("name"), self.user_email
        )
        return _format_file(created)


def _format_file(f: dict[str, Any]) -> dict[str, Any]:
    owners = f.get("owners") or []
    return {
        "id": f.get("id"),
        "name": f.get("name"),
        "mime_type": f.get("mimeType"),
        "size": int(f["size"]) if f.get("size") else None,
        "modified_time": f.get("modifiedTime"),
        "web_view_link": f.get("webViewLink"),
        "owner": owners[0]["emailAddress"] if owners else None,
    }
