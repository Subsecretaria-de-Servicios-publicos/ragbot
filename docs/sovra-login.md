# Login al dashboard con Sovra ID — guía de despliegue y operación

Segundo método de ingreso al dashboard, junto al de usuario/contraseña: el usuario presenta una
**credencial verificable** desde su wallet de Sovra y entra sin contraseña. Está **apagado por
defecto**; el login con contraseña no cambia.

> **Estado al escribir esta guía:** implementado y probado con un Sovra simulado (66 pruebas
> automáticas y prueba manual en el navegador). **No se probó una presentación real con la
> wallet**; ver [Lo que falta verificar](#7-lo-que-falta-verificar) antes de usarlo con usuarios reales.

---

## 1. Cómo funciona

1. En la pantalla de login aparece **"Ingresar con Sovra ID"** (solo si el backend lo tiene activo).
2. El backend crea una sesión de verificación en Sovra y el dashboard muestra un **QR** (3 minutos de vida).
3. El usuario lo escanea con su wallet y aprueba compartir **un solo dato: su DNI**.
4. El backend consulta a Sovra hasta que confirma. Sovra informa el **`holder_did`** (la wallet) y el
   DNI; el backend busca al usuario por **la wallet que vinculó antes**, comprueba que el DNI sea el
   de ese usuario y que esté activo, y emite los **mismos JWT** que el login con contraseña.

**Vinculación previa obligatoria.** Sovra no informa quién emitió la credencial ni de qué tipo, así
que un DNI solo no prueba nada (cualquier credencial con el DNI de otra persona serviría). Lo que ata
el login a una persona es la wallet. Por eso cada usuario tiene que **vincularla una vez**, entrando
con su contraseña y usando "Vincular Sovra ID". Sin eso no puede entrar por Sovra, aunque el admin le
haya cargado el DNI.

Reglas que conviene tener claras:

- **La credencial solo prueba quién es.** El **rol** y los permisos salen siempre de la tabla
  `users`. Un DNI sin usuario asociado no crea ninguna cuenta.
- Cualquier rechazo (wallet sin vincular, usuario inactivo, DNI distinto…) se muestra al
  usuario con el **mismo mensaje genérico**, para no revelar qué cuentas existen. El motivo real queda
  en el log (ver [Problemas frecuentes](#6-problemas-frecuentes)).
- Cada intento es de **un solo uso** y vence a los 3 minutos.

Para vincular (ver [sección 4](#4-administración-de-usuarios)): el usuario entra con su contraseña y
usa **"Vincular Sovra ID"**. El DNI puede cargarlo antes un superadmin (entonces debe coincidir) o
salir de la propia credencial.

---

## 2. Requisitos en Sovra

Se necesita, en el entorno de Sovra que corresponda (test o producción):

| Qué | Detalle |
|---|---|
| **Workspace** con DID activo | Settings → DID & keys. |
| **Esquema de credencial** | Con un claim cuya *key* literal sea la de `SOVRA_LOGIN_CLAIM` (por defecto `dni`). La *key* es un contrato literal: `dni` ≠ `DNI`. |
| **API key del workspace** | Settings → Workspaces → API keys. Empieza con `sovra_sk_`. **Se muestra una sola vez.** |
| **Wallet de Sovra actualizada** | La versión nueva (holder `did:sovra:0x…`). La anterior (`did:quarkid:…`) rechaza los pedidos de verificación. |
| **Wallet de la misma red que el workspace** | Hay que usar la wallet de prueba que Sovra distribuye por TestFlight. Una wallet de otra red no encuentra la llave `#key-assert` y falla con *"DID … publishes no P-256 assertion key #key-assert"*. |

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
| `SOVRA_LOGIN_VCT` | no | — | Tipo de credencial (el `credential_type` del esquema, ej. `EmpleadoPublico`). Se pide a la wallet como `meta.vct_values`, pero **no es la defensa**: Sovra no informa el tipo en el resultado ni confirmó que lo haga cumplir. |
| `SOVRA_LOGIN_CLAIM` | no | `dni` | *Key* del claim que identifica al usuario. |
| `SOVRA_LOGIN_TTL_SECONDS` | no | `180` | Vida de cada intento (máximo 600, el tope de Sovra). |
| `SOVRA_START_RATE_LIMIT` | no | `10` | Intentos por IP y ventana (cada uno crea una sesión en Sovra). |
| `SOVRA_START_RATE_WINDOW_SECONDS` | no | `60` | Ventana del límite anterior. |
| `SOVRA_HTTP_TIMEOUT_SECONDS` | no | `10` | Timeout de las llamadas a Sovra. |

Ejemplo (test):

```env
SOVRA_LOGIN_ENABLED=true
SOVRA_BASE_URL=https://test-api-sovra.flagonsa.com
# La API key no va en chats, tickets ni commits. Comentarios en línea aparte (ver nota de systemd, sección 5).
SOVRA_API_KEY=sovra_sk_...
SOVRA_LOGIN_CLAIM=dni
SOVRA_LOGIN_VCT=EmpleadoPublico
```

Notas:

- **No hace falta webhook.** El backend consulta el estado a Sovra, así que no se expone ninguna URL
  pública nueva ni hay que tocar nginx/apache.
- **Límite de intentos por IP:** `TRUST_PROXY_HEADERS` ya está en `true` en los dos despliegues
  (`docs/ragbot.service` y `docker-compose.prod.yml`), por lo que el límite se aplica por IP real
  del cliente. Con esa variable en `false` detrás de un proxy, **todos** compartirían el mismo cupo
  de 10 intentos/min. El límite usa Redis; si Redis no está disponible no se aplica (mismo criterio
  que el límite general del backend).
- Para rotar la API key: crear una nueva en Sovra, actualizar `.env`, reiniciar el backend (`sudo systemctl restart ragbot`) y revocar la vieja.

---

## 4. Administración de usuarios

**Cargar el DNI (superadmin, opcional).** Usuarios → *Editar* → campo **"DNI para entrar con Sovra ID"**.
Solo el número; se ignoran puntos y espacios. Un DNI ya asignado a otro usuario se rechaza. **Cargarlo
no habilita el ingreso**: el usuario igual tiene que vincular su wallet, y su credencial tiene que traer
ese mismo DNI. **Cambiar o quitar el DNI desvincula la wallet** (hay que volver a vincular).

**Vincular (cada usuario, una vez).** Con la sesión iniciada con contraseña: botón **"Vincular Sovra ID"**
en el menú lateral → escanear con la wallet. Se guarda la wallet (`holder_did`) y el DNI de la
credencial. Solo se puede si el usuario **todavía no tiene wallet vinculada** y su DNI está sin cargar o
es el mismo de la credencial; si no, se rechaza con un mensaje.

**Cambio de celular o de wallet.** El `holder_did` cambia con la wallet nueva. Un superadmin desvincula
al usuario (Editar → quitar el DNI y guardar, o ponerle otro) y el usuario vuelve a vincular.

**Qué ve cada rol.** La columna "Sovra ID" de Usuarios muestra al superadmin el DNI y si ya vinculó
(`✓`) o está "sin vincular"; el admin solo ve "✓ vinculado" cuando hay wallet. El `holder_did` no sale
por la API.

**Dar de baja a alguien.**
1. *Desactivar* al usuario en el dashboard: corta el acceso en el siguiente request (cada request
   revalida contra la base).
2. Si corresponde, revocar su credencial en Sovra: impide nuevos ingresos con ella.

**Salida de emergencia.** El login con usuario y contraseña sigue funcionando para todos. Si Sovra
falla, nadie queda afuera. Para apagar la función: `SOVRA_LOGIN_ENABLED=false` y reiniciar el backend.

---

## 5. Despliegue

### Sin Docker (`deploy-nodocker.sh`, el del servidor actual)

```bash
# 1. En el servidor, agregar las variables SOVRA_* a backend/.env  (ver sección 3)
# 2. Desplegar
./deploy-nodocker.sh
```

El script **no necesitó cambios** para esta función; ya hace todo lo necesario:

| Paso del script | Qué pasa con Sovra ID |
|---|---|
| `git pull --ff-only` | Trae el código. El dashboard es HTML estático que Apache sirve desde `frontend/dashboard`: **llega con el pull, sin reiniciar nada** (refrescar con Ctrl+F5 por la caché del navegador). |
| `pip install -r requirements.txt` | Instala la dependencia nueva `segno` (dibuja el QR). |
| `alembic upgrade head` | Aplica la migración `0019_sovra_login` (columnas `users.sovra_identifier` y `users.sovra_holder_did` y tabla `sovra_login_sessions`). |
| `systemctl restart ragbot` | Reinicia el backend, que lee el `.env` (la unidad usa `EnvironmentFile`). |

**Apache no necesita cambios.** Las rutas nuevas están bajo `/api/v1/auth/…`, que ya se proxea
completa desde `/ragbot/api/` y `/matriabot/api/` (`docs/apache-ragbot.conf`), y el header
`X-Poll-Secret` pasa sin configuración extra.

**Cuidado con el formato del `.env`.** La unidad de systemd lo lee con `EnvironmentFile`, que
**no admite comentarios en la misma línea** que un valor (`SOVRA_LOGIN_VCT=Tipo # comentario` tomaría
todo como valor). Los comentarios van en líneas aparte, como en `.env.example`.

Si solo se cambió el `.env` (sin código nuevo): `sudo systemctl restart ragbot`.

**Verificar después de desplegar:**

```bash
# La migración quedó aplicada (debe mostrar 0019_sovra_login (head))
cd backend && PYTHONPATH=. .venv/bin/alembic current

# El backend ofrece el login con Sovra (true solo si está activado Y configurado)
curl -s https://subsecretar-ia.salta.gob.ar/matriabot/api/v1/auth/methods
# → {"password":true,"sovra":true}

# Redis (lo usa el límite de intentos; si no está, el límite simplemente no se aplica)
systemctl is-active redis-server
```

Si `sovra` da `false` con `SOVRA_LOGIN_ENABLED=true`, falta alguna de `SOVRA_BASE_URL`,
`SOVRA_API_KEY` o `SOVRA_LOGIN_VCT`. Si la URL no es `https`, el inicio responde 503 y queda el
motivo en el log.

**Varios workers:** la unidad corre uvicorn con `--workers 2`. Es compatible: el estado de cada
intento vive en la base de datos, no en memoria, y el canje de un solo uso es atómico en SQL.

### Con Docker (`deploy.sh`)

Mismo resultado: `./deploy.sh` reconstruye la imagen (instala `segno`) y el contenedor ejecuta
`alembic upgrade head` al arrancar. Para verificar:

```bash
docker exec ragbot_backend alembic current
curl -s https://subsecretar-ia.salta.gob.ar/matriabot/api/v1/auth/methods
```

### Prueba de punta a punta recomendada (primero contra el entorno de test de Sovra)

1. Con tu usuario logueado con contraseña: "Vincular Sovra ID" → escanear. Tiene que quedar vinculado.
2. Cerrar sesión → "Ingresar con Sovra ID" → escanear → deberías entrar con tu rol.
3. Probar con **otra wallet** (sin vincular): mensaje genérico y `holder_not_linked` en el log.
4. Probar con un usuario **desactivado**: mismo mensaje genérico, `user_inactive` en el log.
5. Probar un usuario con DNI cargado por el admin que **no** vinculó: `holder_not_linked`.

### Rollback

`SOVRA_LOGIN_ENABLED=false` y reiniciar (`sudo systemctl restart ragbot`). No hace falta revertir la
migración: las tablas quedan sin uso. Si de verdad se quiere deshacer:
`cd backend && PYTHONPATH=. .venv/bin/alembic downgrade 0018_web_search` (borra la tabla de
intentos y la columna del DNI).

---

## 6. Problemas frecuentes

Los rechazos se explican en el log del backend (nunca en pantalla):

```bash
# Sin Docker (systemd)
sudo journalctl -u ragbot --no-pager | grep -E "sovra_login_(rejected|poll_error|replay)|sovra_link_ok"
# Con Docker
docker logs ragbot_backend 2>&1 | grep -E "sovra_login_(rejected|poll_error|replay)|sovra_link_ok"
```

| Motivo en el log (`reason=`) | Qué significa |
|---|---|
| `holder_not_linked` | Esa wallet no está vinculada a ningún usuario (nunca vinculó, o es otra wallet). |
| `user_inactive` | El usuario existe pero está desactivado. |
| `identifier_mismatch` | La wallet es de un usuario, pero el DNI de la credencial no es el suyo (el admin le cambió el DNI, o credencial distinta). |
| `no_holder_did` | Sovra no informó un `holder_did` válido en la verificación. |
| `no_identifier_in_presentation` | La presentación no trae el claim, o el valor no parece un DNI (6 a 10 dígitos). Revisar `SOVRA_LOGIN_CLAIM` y la *key* del esquema. |
| `sovra_failed:<error>` | Sovra rechazó la presentación (ej. `credential_revoked`, `credential_expired`). |
| `link_taken` / `link_already_linked` / `link_mismatch` | Al vincular: el DNI o la wallet son de otro usuario / el usuario ya tenía wallet / su DNI cargado es otro. |

| Síntoma | Causa probable |
|---|---|
| El botón "Ingresar con Sovra ID" no aparece | `GET /auth/methods` da `sovra:false`: falta activar o configurar (ver sección 5). |
| Al tocar el botón: "No se pudo iniciar el ingreso" (503) | Sovra no responde, API key inválida/revocada (`invalid_api_key` en el log), o `SOVRA_BASE_URL` mal. |
| "Demasiados intentos" (429) | Se superó `SOVRA_START_RATE_LIMIT` desde esa IP. Esperar un minuto. |
| La wallet dice *"invalid OID4VP URL, missing required parameters"* | Wallet **vieja** (holder `did:quarkid:…`). Actualizar a la versión nueva. |
| La wallet dice *"…publishes no P-256 assertion key #key-assert"* | La wallet está conectada a otra red de prueba que el workspace. Usar la wallet de prueba de TestFlight que distribuye Sovra. |
| El QR no se escanea / el escáner se pone negro | Bajar el brillo de la pantalla y alejar el celular unos 30 cm. En celulares hay un botón "Abrir en mi wallet". |
| El intento queda "esperando" y vence | La wallet no llegó a enviar la presentación. Revisar que apruebe en la wallet y los errores de la propia app. |
| "El código venció" | Pasaron 3 minutos. Generar uno nuevo. |

---

## 7. Lo que falta verificar

Esto no se pudo comprobar contra Sovra real y **conviene cerrarlo antes de usarlo con usuarios reales**:

1. **Prueba con la wallet correcta.** La que usé estaba en otra red de prueba, por eso fallaba con
   `#key-assert`. Sovra indicó que hay que usar la wallet de prueba que distribuyen por TestFlight.
   Todo lo demás (incluida la forma de `presentation_data`, que Sovra confirmó con un ejemplo real:
   `credentials[].claims` y `holder_did` a nivel de la verificación) se probó solo contra un Sovra simulado.
2. **Emisor y tipo de credencial: no se pueden comprobar.** Sovra aclaró que no vienen en el
   resultado. Por eso el login no se apoya en ellos sino en el `holder_did` vinculado (sección 1).
3. **La migración contra una base real**, y **pantallas angostas** (celular) del dashboard.

---

## 8. Seguridad: decisiones de diseño

- **Autenticar no es autorizar:** el rol viene de la base, nunca de la credencial.
- **Un solo uso** (`UPDATE … WHERE status='verified'` atómico): dos consultas simultáneas no emiten tokens dos veces.
- **`poll_secret` por navegador:** conocer el `login_id` no alcanza para consultar un intento. Va en el
  header `X-Poll-Secret`, nunca en la URL; en la base queda solo su hash.
- **Intentos de "vincular" y de "login" separados:** uno no se puede cobrar como el otro, y el usuario a
  vincular sale del token de quien inicia el flujo, nunca del navegador.
- **El login se ata a la wallet (`holder_did`), no al DNI ni al emisor:** Sovra no informa emisor ni tipo,
  así que otra credencial con el DNI de un usuario no sirve si la wallet no es la vinculada. Además se
  exige que el DNI de la credencial sea el del usuario.
- **Vincular no pisa una wallet ya vinculada:** con un token robado no se puede agregar una wallet propia
  a una cuenta ajena que ya tiene una. Cambiarla lo hace un superadmin. Dos usuarios no pueden tener el
  mismo DNI ni la misma wallet (restricciones únicas en la base). Un token robado de un usuario **sin**
  vincular sí permitiría vincular una wallet ajena: por eso conviene que los usuarios vinculen al activar la función.
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
| Modelos y migración | `models.py` (`SovraLoginSession`, `User.sovra_identifier`, `User.sovra_holder_did`) y `alembic/versions/0019_sovra_login.py` |
| Pantalla de login, vincular y usuarios | `frontend/dashboard/index.html` (`createSovraFlow`) |

**Pruebas automáticas** (sin red ni base de datos; usan `unittest`, no hace falta instalar nada más):

```bash
cd backend
./venv/bin/python -m unittest discover -s tests -v
```

Cubren: un solo uso del canje, secreto de consulta, separación login/vincular, rechazos sin revelar
motivo, atadura a la wallet, vinculación previa, vencimiento, errores transitorios de Sovra, permisos del listado de usuarios y
validación del DNI. **No** cubren la base real ni la wallet.

Endpoints (todos bajo `/api/v1`):

| Método y ruta | Auth | Qué hace |
|---|---|---|
| `GET /auth/methods` | no | Indica si se ofrece el login con Sovra. |
| `POST /auth/sovra/start` | no | Crea un intento de login; devuelve QR, `login_id` y `poll_secret`. |
| `GET /auth/sovra/{login_id}` | `X-Poll-Secret` | Estado; al aprobarse devuelve los JWT. |
| `POST /auth/sovra/link/start` | sí (token) | Crea un intento de vinculación para el usuario del token. |
| `GET /auth/sovra/link/{login_id}` | token + `X-Poll-Secret` | Estado de la vinculación. |
| `PATCH /users/{id}` | superadmin | Acepta `sovra_identifier` (DNI; `""` lo quita). Cambiarlo o quitarlo desvincula la wallet. |
