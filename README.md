# Conector Drive (CON-007)

Conector Ruvic para Google Drive en un dominio **Google Workspace**, vía
**cuenta de servicio con delegación de dominio**. Una sola credencial
puede impersonar a cualquier usuario autorizado del dominio y operar
sobre su Drive (`facturacion@empresa.com`, `soporte@empresa.com`, …)
sin re-autorizar cada uno individualmente y sin tokens que expiren.

Usa el mismo patrón de autenticación que [CON-005.2](../CON-005.2)
(Gmail Workspace) — si ya tienes esa cuenta de servicio configurada,
puedes reutilizarla agregando el scope de Drive a la misma entrada de
delegación en el Admin Console.

**Solo funciona con Google Workspace** — Google no permite delegación de
dominio en cuentas Gmail/Drive personales.

## Instalación

```bash
pip install git+https://github.com/Dgirto/Drive.git#subdirectory=lib
```

Python 3.10+. Dependencias: `google-auth` y `google-api-python-client`.

## Obtener credenciales (una sola vez, por dominio Workspace)

### 1. Proyecto y cuenta de servicio en Google Cloud Console

1. Crea (o reutiliza) un proyecto en [Google Cloud Console](https://console.cloud.google.com/).
2. Habilita la **Google Drive API**.
3. Ve a **IAM y administración → Cuentas de servicio → Crear cuenta de servicio**. Dale un nombre (ej. `ruvic-drive`) y termina el asistente sin roles adicionales de proyecto. (Si ya tienes la cuenta de servicio de CON-005.2, puedes reutilizarla en lugar de crear una nueva.)
4. Abre la cuenta de servicio → pestaña **Claves** → **Agregar clave → Crear clave nueva → JSON**. Se descarga un archivo `.json` — este es el que va al formulario del conector.
5. En la pestaña **Detalles**, copia el **ID de cliente único**.

### 2. Delegación de dominio (solo el superadministrador de Workspace puede hacer esto)

1. El superadministrador entra a [admin.google.com](https://admin.google.com/) → **Seguridad → Control de acceso a las API → Delegación en todo el dominio**.
2. Si el Client ID ya está agregado (ej. porque ya configuraste Gmail Workspace), edita esa misma entrada y agrega el scope de Drive a la lista. Si no, clic en **Agregar nuevo**.
3. **ID de cliente**: el ID de cliente único del paso anterior.
4. **Alcances OAuth**:
   ```
   https://www.googleapis.com/auth/drive
   ```
   (si reutilizas la entrada de Gmail Workspace, la lista completa quedaría: `https://www.googleapis.com/auth/gmail.readonly,https://www.googleapis.com/auth/gmail.send,https://www.googleapis.com/auth/drive`)
5. Guardar.

> Sin este paso, cualquier intento de conexión falla con `unauthorized_client` — el conector detecta este error específico y explica exactamente qué revisar.

## Variables de entorno (`RUVIC_DRIVE_*`)

| Variable | Obligatoria | Descripción |
|----------|-------------|-------------|
| `RUVIC_DRIVE_SERVICE_ACCOUNT_JSON` | Sí | JSON completo de la cuenta de servicio |
| `RUVIC_DRIVE_DEFAULT_USER` | Sí | Usuario del dominio usado para el botón "Probar conexión" |
| `RUVIC_DRIVE_REQUEST_TIMEOUT` | No (default `30`) | Timeout de solicitud en segundos |

## Pruebas locales

```bash
python -m venv .venv && source .venv/bin/activate
pip install -e ./lib

export RUVIC_DRIVE_SERVICE_ACCOUNT_JSON='{"type": "service_account", ...}'
export RUVIC_DRIVE_DEFAULT_USER=facturacion@tudominio.com

python test_connection.py
python validate_local.py
```

`validate_local.py` lista los archivos recientes, lee el detalle del
primero, sube un archivo de prueba y lo vuelve a descargar.

Prueba también los casos de error (delegación no configurada — el más
importante y el que da `unauthorized_client`, cuenta de servicio con
clave inválida, archivo inexistente) y verifica que los mensajes sean
claros.

## Notas de integración

- **Mismo patrón que CON-005.2**: mismo constructor (`user_email` en
  lugar de `mailbox`), misma clasificación de errores
  (Auth/Network/Data), mismo manejo explícito de `unauthorized_client`.
- **Una credencial, N usuarios**: `DriveClient(user_email="...")` acepta
  cualquier usuario autorizado del dominio, no solo el `DEFAULT_USER` de
  prueba.
- **Sin expiración de tokens**: la delegación de dominio no genera un
  `refresh_token` que pueda vencer — el acceso dura mientras la
  delegación siga activa en el Admin Console.
- **Scope amplio**: `https://www.googleapis.com/auth/drive` da acceso
  completo de lectura y escritura al Drive del usuario impersonado (no
  solo a los archivos creados por el conector). Es la credencial de
  mayor cuidado de este conector — trátala igual que la de CON-005.2.
- **Revocación**: para revocar el acceso, el superadministrador elimina
  o edita la entrada de delegación en el Admin Console, o se
  elimina/rota la clave de la cuenta de servicio en Google Cloud Console.
- Los errores HTTP 401/403 de la API se clasifican como `DriveAuthError`;
  404 como `DriveDataError`; 429 y 5xx como `DriveNetworkError`
  (reintentable).

## Limitaciones conocidas

- Solo funciona con dominios **Google Workspace** — no hay forma de
  usarlo con cuentas Gmail/Drive personales (@gmail.com), Google no
  permite delegación de dominio fuera de Workspace.
- `upload_file` rechaza archivos mayores a **20 MB**; para adjuntos más
  grandes no hay soporte de subida por partes (resumable) en esta versión.
- El conector solo expone `file.list`, `file.read`, `file.download` y
  `file.upload` — no incluye eliminar, renombrar, mover ni compartir
  archivos, aunque el scope `drive` técnicamente lo permitiría.
- `download_file` exporta los archivos nativos de Google (Docs, Sheets,
  Slides) siempre a **PDF**; no soporta otros formatos de exportación.
- Requiere que un superadministrador del dominio haga el paso de
  delegación en el Admin Console — no es autoservicio para el usuario
  final del conector.
