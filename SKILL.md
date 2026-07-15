---
name: drive
description: >
  Usa la librería ruvic_drive_connector para listar, leer, descargar y
  subir archivos en el Google Drive de usuarios de un dominio Google
  Workspace, vía cuenta de servicio con delegación de dominio
  (impersonación) - buscar/listar archivos con filtros (list_files),
  leer los metadatos de un archivo (get_file), descargar el contenido de
  un archivo (download_file) y subir un archivo local a Drive
  (upload_file). Úsala cuando el usuario pida buscar, listar, leer,
  descargar o subir archivos en el Drive corporativo de Google Workspace,
  especialmente si menciona varios usuarios/buzones del mismo dominio
  sin volver a autorizar cada uno por separado.
triggers:
- drive
- google drive
- archivo
- archivos
- documento
- documentos
- carpeta
- subir archivo
- descargar archivo
- unidad compartida
- workspace
- delegación de dominio
---

# Conector Drive (ruvic_drive_connector)

Librería Python para listar, leer, descargar y subir archivos en el Google Drive de usuarios de un dominio **Google Workspace**, usando una **cuenta de servicio con delegación de dominio**. Está **preinstalada en el runtime** cuando el conector está configurado (si no, instálala con `pip install git+https://github.com/Dgirto/Drive.git#subdirectory=lib`).

Este conector **no funciona con cuentas Gmail/Drive personales** — Google no permite delegación de dominio fuera de Workspace.

## Regla crítica de credenciales

El código generado **NUNCA hardcodea credenciales**. Siempre se leen de variables de entorno, disponibles cuando el conector `drive` está configurado:

| Variable | Contenido |
|----------|-----------|
| `RUVIC_DRIVE_SERVICE_ACCOUNT_JSON` | JSON completo de la cuenta de servicio de Google Cloud |
| `RUVIC_DRIVE_DEFAULT_USER` | Usuario usado solo para el test de conexión |
| `RUVIC_DRIVE_REQUEST_TIMEOUT` | (opcional) timeout en segundos, default 30 |

Si estas variables NO existen, el conector no está configurado: no generes código que lo use; indica al usuario que lo configure en **Settings → Conectores**. El código generado **NUNCA** usa nombres con segmento de alias (`_DEFAULT_INSTANCIA_`, `_PRODUCCION_`, etc.) salvo que aparezcan en una sección autogenerada `## Variables en tu entorno` al final de este skill.

## Autenticación / conexión (siempre igual)

El usuario a impersonar se pasa en el **constructor**, no en cada método — así se comparte la misma sesión/servicio autenticado entre varias llamadas al mismo usuario:

```python
from ruvic_drive_connector import DriveClient

# Impersona a cualquier usuario autorizado del dominio (no hace falta
# que sea el mismo que RUVIC_DRIVE_DEFAULT_USER)
client = DriveClient(user_email="facturacion@tuempresa.com")
```

Para trabajar con varios usuarios, crea una instancia por usuario:

```python
usuarios = ["facturacion@tuempresa.com", "soporte@tuempresa.com"]
clientes = {u: DriveClient(user_email=u) for u in usuarios}
```

## Capacidad 1 — Buscar/listar archivos con filtros

```python
archivos = client.list_files(query="name contains 'factura'", max_results=20)
for f in archivos:
    print(f"{f['modified_time']} | {f['name']} | {f['mime_type']}")
```

## Capacidad 2 — Leer los metadatos de un archivo

```python
detail = client.get_file(archivos[0]["id"])
print(detail["name"], detail["mime_type"], detail["owner"])
```

## Capacidad 3 — Descargar el contenido de un archivo

```python
ruta = client.download_file(archivos[0]["id"], "/tmp/reporte.pdf")
```

Los archivos nativos de Google (Docs, Sheets, Slides) se exportan automáticamente a PDF; el resto se descarga tal cual.

## Capacidad 4 — Subir un archivo local a Drive

```python
result = client.upload_file(
    "/tmp/reporte.pdf",
    name="Reporte mensual.pdf",
    parent_folder_id="1xYzCarpetaDestino",  # opcional
)
```

## Manejo de errores

```python
from ruvic_drive_connector import DriveAuthError, DriveDataError, DriveNetworkError

try:
    client.upload_file("/tmp/reporte.pdf")
except DriveAuthError:
    print("Delegación de dominio no autorizada para este usuario — revisa el Admin Console")
except DriveNetworkError:
    print("Drive API no respondió — puede ser un límite de cuota temporal")
except DriveDataError as e:
    print(f"Error de datos: {e}")  # ej. archivo inexistente o demasiado grande
```

`DriveAuthError` incluye en su mensaje el Client ID exacto que debe estar autorizado en el Admin Console, y qué revisar (Client ID, scope, dominio del usuario) — muéstraselo tal cual al usuario cuando ocurra.

## Buenas prácticas al generar código

1. Lee credenciales SOLO de las variables `RUVIC_DRIVE_*` (el constructor de `DriveConfig` ya lo hace).
2. Nunca imprimas `RUVIC_DRIVE_SERVICE_ACCOUNT_JSON` en logs ni en la salida — es una credencial de máximo cuidado (da acceso potencial al Drive de cualquier usuario del dominio, no solo a uno).
3. El `user_email` del constructor puede ser **cualquier** usuario del dominio autorizado, no solo el de prueba (`DEFAULT_USER`) — no asumas que son el mismo.
4. Usa `max_results` razonable en `list_files` (default 20, máximo 100).
5. `local_path` en `upload_file` debe ser una ruta local accesible en el runtime; el conector rechaza archivos mayores a 20 MB.
6. El scope del conector (`drive`) da acceso completo de lectura y escritura al Drive del usuario impersonado — no lo uses para operaciones que el usuario no pidió explícitamente (ej. no elimines ni sobrescribas archivos sin confirmación).
