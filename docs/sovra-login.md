# Login al dashboard con Sovra ID — guía de despliegue y operación

Segundo método de ingreso al dashboard, junto al de usuario/contraseña: el usuario presenta una
**credencial verificable** desde su wallet de Sovra y entra sin contraseña. Está **apagado por
defecto**; el login con contraseña no cambia.

> **Estado al escribir esta guía:** implementado y probado con un Sovra simulado (57 pruebas
> automáticas y prueba manual en el navegador). **No se probó una presentación real con la
> wallet**; ver [Lo que falta verificar](#7-lo-que-falta-verificar) antes de usarlo con usuarios reales.

---

## 1. Cómo funciona

1. En la pantalla de login aparece **"Ingresar con Sovra ID"** (solo si el backend lo tiene activo).
2. El backend crea una sesión de verificación en Sovra y el dashboard muestra un **QR** (3 minutos de vida).
3. El usuario lo escanea con su wallet y aprueba compartir **un solo dato: su DNI**.
4. El backend consulta a Sovra hasta que confirma, busca al usuario por ese DNI y, si existe y está
   activo, emite los **mismos JWT** que el login con contraseña.

Reglas que conviene tener claras:

- **La credencial solo prueba quién es.** El **rol** y los permisos salen siempre de la tabla
  `users`. Un DNI sin usuario asociado no crea ninguna cuenta.
- Cualquier rechazo (DNI sin usuario, usuario inactivo, credencial de otro emisor…) se muestra al
  usuario con el **mismo mensaje genérico**, para no revelar qué DNIs existen. El motivo real queda
  en el log (ver [Problemas frecuentes](#6-problemas-frecuentes)).
- Cada intento es de **un solo uso** y vence a los 3 minutos.

Para vincular un usuario con su DNI hay dos caminos (ver [sección 4](#4-administración-de-usuarios)):
lo carga un superadmin, o el propio usuario usa **"Vincular Sovra ID"** estando logueado.

---

## 2. Requisitos en Sovra

Se necesita, en el entorno de Sovra que corresponda (test o producción):

| Qué | Detalle |
|---|---|
| **Workspace** con DID activo | Settings → DID & keys. |
| **Esquema de credencial** | Con un claim cuya *key* literal sea la de `SOVRA_LOGIN_CLAIM` (por defecto `dni`). La *key* es un contrato literal: `dni` ≠ `DNI`. |
| **API key del workspace** | Settings → Workspaces → API keys. Empieza con `sovra_sk_`. **Se muestra una sola vez.** |
| **Wallet de Sovra actualizada** | La versión nueva (holder `did:sovra:0x…`). La anterior (`did:quarkid:…`) rechaza los pedidos de verificación. |
| **Llave P-256 `#key-assert` en el DID** | Sovra firma los pedidos de verificación con ES256 y `kid …#key-assert`. Si el DID no publica esa llave, la wallet falla con *"DID … publishes no P-256 assertion key #key-assert"*. |

| Entorno | API (`SOVRA_BASE_URL`) | Dashboard de Sovra |
|---|---|---|
| Test | `https://test-api-sovra.flagonsa.com` | `https://test-issuer-sovra.flagonsa.com` |
| Producción | `https://api.sovra.io` | `https://issuer.sovra.io` |

---

## 3. Configuración

Todo va en `backend/.env` del servidor (no está en el repo; `deploy.sh` lo deja con permisos 600).
`backend/.env.example` trae el bloque con comentarios.

| Variable | Obligatoria | Por defecto | Para qué |
|---|---|---|---|
| `SOVRA_LOGIN_ENABLED` | sí, para activar | `false` | Interruptor general. Apagado = los endpoints responden 404 y el botón no se muestra. |
| `SOVRA_BASE_URL` | sí | — | URL de la API de Sovra. Solo `https` (o `http` hacia `localhost`). |
| `SOVRA_API_KEY` | sí | — | `sovra_sk_…` del workspace. **Secreto de servidor.** |
| `SOVRA_LOGIN_VCT` | **sí** | — | Tipo de credencial aceptado (el `credential_type` del esquema, ej. `EmpleadoPublico`). Se pide como `meta.vct_values`. Sin él el login responde 503: sin fijar el tipo, serviría cualquier credencial con ese claim. |
| `SOVRA_LOGIN_ISSUER_DID` | recomendada | — | DID del emisor aceptado (`did:sovra:0x…`). Si se define, el login **falla cerrado** salvo que Sovra informe un emisor que coincida. |
| `SOVRA_LOGIN_CLAIM` | no | `dni` | *Key* del claim que identifica al usuario. |
| `SOVRA_LOGIN_TTL_SECONDS` | no | `180` | Vida de cada intento (máximo 600, el tope de Sovra). |
| `SOVRA_START_RATE_LIMIT` | no | `10` | Intentos por IP y ventana (cada uno crea una sesión en Sovra). |
| `SOVRA_START_RATE_WINDOW_SECONDS` | no | `60` | Ventana del límite anterior. |
| `SOVRA_HTTP_TIMEOUT_SECONDS` | no | `10` | Timeout de las llamadas a Sovra. |

Ejemplo (test):

```env
SOVRA_LOGIN_ENABLED=true
SOVRA_BASE_URL=https://test-api-sovra.flagonsa.com
SOVRA_API_KEY=sovra_sk_...            # no la pegues en chats, tickets ni commits
SOVRA_LOGIN_CLAIM=dni
SOVRA_LOGIN_VCT=EmpleadoPublico
SOVRA_LOGIN_ISSUER_DID=did:sovra:0x...
```

Notas:

- **No hace falta webhook.** El backend consulta el estado a Sovra, así que no se expone ninguna URL
  pública nueva ni hay que tocar nginx/apache.
- **Límite de intentos por IP:** en producción `TRUST_PROXY_HEADERS` ya está en `true`
  (`docker-compose.prod.yml`), por lo que el límite se aplica por IP real del cliente. Con esa
  variable en `false` detrás de un proxy, **todos** compartirían el mismo cupo de 10 intentos/min.
- Para rotar la API key: crear una nueva en Sovra, actualizar `.env`, reiniciar el backend y revocar la vieja.

---

## 4. Administración de usuarios

**Cargar el DNI (superadmin).** Usuarios → *Editar* → campo **"DNI para entrar con Sovra ID"**. Solo el
número; se ignoran puntos y espacios. Vacío = el usuario no puede entrar por Sovra. Un DNI ya
asignado a otro usuario se rechaza.

**Vincular por cuenta propia (cualquier usuario).** Con la sesión iniciada: botón **"Vincular Sovra ID"**
en el menú lateral → escanear con la wallet. El DNI se toma de la credencial. Solo se puede si el
usuario **todavía no tiene DNI vinculado**; cambiar uno ya cargado lo hace un superadmin.

**Qué ve cada rol.** La columna "Sovra ID" de Usuarios muestra el DNI al superadmin; el admin solo ve
"✓ vinculado".

**Dar de baja a alguien.**
1. *Desactivar* al usuario en el dashboard: corta el acceso en el siguiente request (cada request
   revalida contra la base).
2. Si corresponde, revocar su credencial en Sovra: impide nuevos ingresos con ella.

**Salida de emergencia.** El login con usuario y contraseña sigue funcionando para todos. Si Sovra
falla, nadie queda afuera. Para apagar la función: `SOVRA_LOGIN_ENABLED=false` y reiniciar.

---

## 5. Despliegue

El flujo normal ya hace todo lo necesario:

```bash
# 1. En el servidor, agregar las variables SOVRA_* a backend/.env  (ver sección 3)
# 2. Desplegar
./deploy.sh
```

- La imagen se reconstruye, así que se instala la dependencia nueva (`segno`, para dibujar el QR).
- El contenedor ejecuta `alembic upgrade head` al arrancar: aplica la migración `0019_sovra_login`
  (columna `users.sovra_identifier` y tabla `sovra_login_sessions`). Con `deploy-nodocker.sh` pasa lo mismo.

**Verificar después de desplegar:**

```bash
# La migración quedó aplicada
docker exec ragbot_backend alembic current          # debe mostrar 0019_sovra_login (head)

# El backend ofrece el login con Sovra (true solo si está activado Y configurado)
curl -s https://subsecretar-ia.salta.gob.ar/matriabot/api/v1/auth/methods
# → {"password":true,"sovra":true}
```

Si `sovra` da `false` con `SOVRA_LOGIN_ENABLED=true`, falta alguna de `SOVRA_BASE_URL`,
`SOVRA_API_KEY` o `SOVRA_LOGIN_VCT`. Si hay una URL inválida (no `https`), el inicio responde 503 y
queda el motivo en el log.

**Prueba de punta a punta recomendada** (primero en test):
1. Cargar tu DNI en tu usuario (o usar "Vincular Sovra ID").
2. Cerrar sesión → "Ingresar con Sovra ID" → escanear → deberías entrar con tu rol.
3. Probar con una credencial de **otro** DNI (sin usuario): debe mostrar el mensaje genérico y
   quedar `no_user_for_identifier` en el log.
4. Probar con un usuario **desactivado**: mismo mensaje genérico, `user_inactive` en el log.

**Rollback:** `SOVRA_LOGIN_ENABLED=false` y reiniciar. No hace falta revertir la migración (las
tablas quedan sin uso). Si de verdad se quiere deshacer: `alembic downgrade 0018_web_search`
(borra la tabla de intentos y la columna del DNI).

---

## 6. Problemas frecuentes

Los rechazos se explican en el log del backend (nunca en pantalla):

```bash
docker logs ragbot_backend 2>&1 | grep -E "sovra_login_(rejected|poll_error|replay)|sovra_link_ok"
```

| Motivo en el log (`reason=`) | Qué significa |
|---|---|
| `no_user_for_identifier` | El DNI de la credencial no está cargado en ningún usuario. |
| `user_inactive` | El usuario existe pero está desactivado. |
| `issuer_mismatch` | El emisor no coincide con `SOVRA_LOGIN_ISSUER_DID`, **o** Sovra no informó emisor (falla cerrado). |
| `no_identifier_in_presentation` | La presentación no trae el claim, o el valor no parece un DNI (6 a 10 dígitos). Revisar `SOVRA_LOGIN_CLAIM` y la *key* del esquema. |
| `sovra_failed:<error>` | Sovra rechazó la presentación (ej. `credential_revoked`, `credential_expired`). |
| `link_taken` / `link_already_linked` | Al vincular: el DNI es de otro usuario / el usuario ya tenía uno. |

| Síntoma | Causa probable |
|---|---|
| El botón "Ingresar con Sovra ID" no aparece | `GET /auth/methods` da `sovra:false`: falta activar o configurar (ver sección 5). |
| Al tocar el botón: "No se pudo iniciar el ingreso" (503) | Sovra no responde, API key inválida/revocada (`invalid_api_key` en el log), o `SOVRA_BASE_URL` mal. |
| "Demasiados intentos" (429) | Se superó `SOVRA_START_RATE_LIMIT` desde esa IP. Esperar un minuto. |
| La wallet dice *"invalid OID4VP URL, missing required parameters"* | Wallet **vieja** (holder `did:quarkid:…`). Actualizar a la versión nueva. |
| La wallet dice *"…publishes no P-256 assertion key #key-assert"* | El DID del workspace no publica esa llave. Lo corrige Sovra, no se arregla acá. |
| El QR no se escanea / el escáner se pone negro | Bajar el brillo de la pantalla y alejar el celular unos 30 cm. En celulares hay un botón "Abrir en mi wallet". |
| El intento queda "esperando" y vence | La wallet no llegó a enviar la presentación. Revisar que apruebe en la wallet y los errores de la propia app. |
| "El código venció" | Pasaron 3 minutos. Generar uno nuevo. |

---

## 7. Lo que falta verificar

Esto no se pudo comprobar contra Sovra real y **conviene cerrarlo antes de usarlo con usuarios reales**:

1. **Forma de `presentation_data`.** Sovra la documenta solo como "object". El backend asume
   `credentials[].claims` (lo que indica su guía de webhooks). Si la forma real es otra, hay que
   ajustar **una sola función**: `extract_presented` en `backend/app/services/sovra_login.py`.
2. **Que Sovra haga cumplir `vct` y emisor.** Sovra acepta `meta.vct_values` y lo copia al pedido
   firmado, pero no está confirmado que el servidor rechace una credencial de otro tipo o emisor.
   Hasta saberlo, **`SOVRA_LOGIN_ISSUER_DID` es la defensa** (si Sovra no informa emisor, el login
   falla cerrado). Riesgo si no se cubre: alguien con una credencial propia que tenga el mismo
   claim `dni` de otra persona.
3. **La llave `#key-assert`** del DID (sección 2). Sin ella la wallet no puede validar el pedido.
4. **La migración contra una base real**, y **pantallas angostas** (celular) del dashboard.

---

## 8. Seguridad: decisiones de diseño

- **Autenticar no es autorizar:** el rol viene de la base, nunca de la credencial.
- **Un solo uso** (`UPDATE … WHERE status='verified'` atómico): dos consultas simultáneas no emiten tokens dos veces.
- **`poll_secret` por navegador:** conocer el `login_id` no alcanza para consultar un intento. Va en el
  header `X-Poll-Secret`, nunca en la URL; en la base queda solo su hash.
- **Intentos de "vincular" y de "login" separados:** uno no se puede cobrar como el otro, y el usuario a
  vincular sale del token de quien inicia el flujo, nunca del navegador.
- **Vincular no pisa un DNI ya cargado:** con un token robado no se puede agregar una credencial propia a
  una cuenta ajena. Cambiarlo lo hace un superadmin. Dos usuarios no pueden tener el mismo DNI (restricción
  única en la base).
- **Mensajes genéricos** hacia el navegador; el motivo real solo en el log. No se registran DNIs ni claims.
- **Errores sin secretos:** ni la API key ni la URL de Sovra aparecen en mensajes de error.
- **QR con fondo blanco fijo** y link `openid4vp://` aceptado solo con ese esquema.
- **Riesgo conocido (QR phishing):** un atacante puede iniciar un login y pedirle a otra persona que lo
  apruebe en su wallet. Mitigaciones: vida corta (3 min) y secreto atado al navegador que inició el intento.
  Lo que la wallet muestra al aprobar depende de Sovra (hoy el nombre del workspace).
- **Limpieza de datos:** la tabla `sovra_login_sessions` **no guarda claims ni DNIs**, solo identificadores
  y estados, pero **no se purga sola**. Si crece, se puede limpiar a mano:

  ```sql
  DELETE FROM sovra_login_sessions WHERE expires_at < now() - interval '30 days';
  ```

---

## 9. Para quien mantiene el código

| Qué | Dónde |
|---|---|
| Lógica del login y de la vinculación (sin base, testeable) | `backend/app/services/sovra_login.py` |
| Cliente HTTP de Sovra | `backend/app/services/sovra_client.py` |
| Acceso a la base | `backend/app/services/sovra_login_store.py` |
| Endpoints (`/auth/methods`, `/auth/sovra/*`) | `backend/app/api/routers.py` (sección AUTH) |
| Modelos y migración | `models.py` (`SovraLoginSession`, `User.sovra_identifier`) y `alembic/versions/0019_sovra_login.py` |
| Pantalla de login, vincular y usuarios | `frontend/dashboard/index.html` (`createSovraFlow`) |

**Pruebas automáticas** (sin red ni base de datos; usan `unittest`, no hace falta instalar nada más):

```bash
cd backend
./venv/bin/python -m unittest discover -s tests -v
```

Cubren: un solo uso del canje, secreto de consulta, separación login/vincular, rechazos sin revelar
motivo, fijado de emisor, vencimiento, errores transitorios de Sovra, permisos del listado de usuarios y
validación del DNI. **No** cubren la base real ni la wallet.

Endpoints (todos bajo `/api/v1`):

| Método y ruta | Auth | Qué hace |
|---|---|---|
| `GET /auth/methods` | no | Indica si se ofrece el login con Sovra. |
| `POST /auth/sovra/start` | no | Crea un intento de login; devuelve QR, `login_id` y `poll_secret`. |
| `GET /auth/sovra/{login_id}` | `X-Poll-Secret` | Estado; al aprobarse devuelve los JWT. |
| `POST /auth/sovra/link/start` | sí (token) | Crea un intento de vinculación para el usuario del token. |
| `GET /auth/sovra/link/{login_id}` | token + `X-Poll-Secret` | Estado de la vinculación. |
| `PATCH /users/{id}` | superadmin | Acepta `sovra_identifier` (DNI; `""` lo quita). |
