# Manual del administrador — RAGBot

Este manual explica cómo usar el **dashboard** de RAGBot para crear y configurar chatbots,
cargar documentos, controlar accesos y gasto, y atender las consultas de las personas.
Está pensado para administradores y operadores del sistema; no requiere conocimientos de
programación.

> Para los aspectos técnicos del despliegue (servidor, base de datos, SMTP, Apache), ver el
> `README` y los archivos de `docs/`.

---

## 1. Conceptos básicos

- **Chatbot (bot):** un asistente con su propia personalidad, sus documentos, su API key de
  IA, su límite de gasto y sus contactos. Cada bot es independiente de los demás.
- **Documentos (base de conocimiento):** PDF, TXT o DOCX que el bot usa para responder. El
  sistema los procesa (los divide en fragmentos y los indexa) en segundo plano.
- **Archivos descargables:** PDFs que el bot ofrece como link cuando el usuario los pide
  (formularios, guías). **No** se usan para responder preguntas; ver sección 6.
- **Consultas ("Hablar con una persona"):** pedidos de contacto humano que deja el usuario
  final desde el chat.
- **Dashboard:** la aplicación web de administración. El usuario final **no** la usa; solo
  interactúa con el chat.

---

## 2. Ingreso y roles

Se ingresa con usuario y contraseña. Las pantallas y acciones que ve cada persona dependen de
su **rol**:

| Rol | Qué puede hacer |
|---|---|
| **Viewer** (visualizador) | Ver los bots a los que tiene acceso, sus conversaciones, estadísticas y consultas. No modifica nada. |
| **Operator** (operador) | Todo lo de viewer, más: editar la personalidad del bot (nombre, descripción, bienvenida, system prompt, contacto, preguntas de ejemplo), subir y borrar documentos y archivos descargables, y marcar consultas como resueltas. |
| **Admin** | Todo lo de operador, más: crear y borrar bots, configurar el modelo de IA y la API key del bot, el límite de gasto, el RAG (Top K y umbral), la publicación del bot, asignar accesos a otros usuarios y crear API keys de acceso al chat. Ve **todos** los bots. |
| **Superadmin** | Todo lo anterior, más: crear y editar usuarios, administrar los proveedores de IA globales, subir los logos institucionales (Gobierno y Modernización) y ver el listado global de consultas de todos los bots. |

**Alcance por bot:** un operador o viewer solo ve y edita los bots que **creó** o a los que
fue **asignado** (ver sección 11). Dentro de un bot asignado, un operador puede editar los
textos de personalidad y contacto, pero **no** el modelo, el gasto ni la publicación.

---

## 3. Pantalla principal (Dashboard)

Muestra los totales de la cuenta: cantidad de bots, documentos listos, conversaciones y
tokens usados, más la lista de los bots recientes. Los totales se limitan a los bots que la
persona puede ver.

---

## 4. Crear y configurar un chatbot

### 4.1 Crear el bot (admin)
En **Chatbots → Nuevo chatbot** se completa el nombre, la descripción, el proveedor y modelo
de IA y el system prompt inicial. Luego se entra al bot para completar el resto.

### 4.2 Pestaña Configuración

**Personalidad (admin, operador y dueño):**
- **Nombre del bot** y **descripción**.
- **Avatar:** imagen del bot (PNG, JPG, GIF, WEBP o SVG; máx. 2 MB).
- **Logo del organismo:** logo institucional del área dueña del bot (aparece junto al logo de
  Gobierno en el encabezado del chat).
- **Mensaje de bienvenida:** lo primero que ve el usuario al abrir el chat.
- **System prompt (personalidad):** la forma de hablar del bot. Describí el tono, el personaje
  o rol y las restricciones. Ver la sección 12 sobre cómo se comporta el bot.
- **Preguntas de ejemplo (hasta 4):** botones que aparecen al inicio del chat para guiar al
  usuario. Al tocar una, el texto se copia al campo de escritura para que el usuario lo edite
  o lo complete antes de enviarlo. Dejarlas vacías oculta la sección.
- **Contacto para intervención humana:** email y/o WhatsApp (con código de país, sin `+`).
  Si se carga al menos uno, aparece el botón 🆘 en el chat y las consultas se pueden enviar
  por el formulario (sección 8).

**Modelo de IA (solo admin):**
- **Proveedor y modelo:** OpenAI, Anthropic, Google u Ollama (local) y el modelo específico.
- **Temperatura:** qué tan creativas son las respuestas (más alta = más variación).
- **Max tokens:** largo máximo de cada respuesta.

**RAG — búsqueda en documentos (solo admin):**
- **Top K:** cuántos fragmentos de documentos se le pasan al modelo en cada pregunta. Más
  fragmentos dan más información pero también más contexto (más costo y, con algunos modelos,
  menos fidelidad a la personalidad). Un valor de 3 a 5 suele alcanzar.
- **Umbral de similitud:** qué tan parecido tiene que ser un fragmento a la pregunta para
  usarse. Más alto = respuestas más estrictas.

**API key y consumo (solo admin):** ver sección 5.

**Publicación (solo admin):**
- **Bot público:** si está desmarcado, el widget y la página de chat no responden a nadie,
  aunque se tenga el enlace.
- **Permitir subir un PDF en el chat:** el usuario puede adjuntar un PDF para preguntar sobre
  su contenido (ver sección 10).

Al terminar, tocar **Guardar configuración**.

---

## 5. API key del bot y control de gasto (admin)

### 5.1 API key propia
**Cada bot necesita su propia API key del proveedor de IA** (OpenAI, Anthropic, Google). Sin
key, el bot no responde al usuario: devuelve un aviso genérico y, si hay contacto configurado,
ofrece el formulario. Ollama (local) no necesita key.

- Se carga en **Configuración → API Key y consumo**. El sistema la verifica contra el proveedor
  antes de guardarla.
- **Por seguridad, la key nunca se vuelve a mostrar.** En pantalla solo aparecen sus últimos
  4 caracteres. Para cambiarla, se carga una nueva.
- Si se cambia el proveedor del bot, la key anterior se descarta y hay que cargar la del nuevo.
- **Quitar la key** deja el bot sin respuesta hasta que se cargue otra.

### 5.2 Límite mensual de tokens
- En **Límite mensual de tokens** se fija un tope. **0 o vacío = sin límite.**
- Se muestra el consumo del mes en curso con una barra de progreso.
- Al **80 %** y al **100 %** se envía un aviso (si el sistema tiene alertas de correo o webhook
  configuradas), una sola vez por mes y por nivel.
- Al llegar al **100 %** el bot deja de responder hasta el mes siguiente o hasta que se
  suba el límite.
- El contador se reinicia automáticamente al cambiar de mes.

### 5.3 Qué se cuenta y cómo se estima el gasto
- El límite mensual cuenta **todos los tokens** del bot: entrada y salida del modelo de chat,
  más los embeddings (la pregunta de cada consulta y la carga de documentos).
- Se cuenta también el razonamiento interno de los modelos que lo cobran como salida (por ejemplo,
  algunos modelos de Google).
- El **costo estimado en USD** usa los precios de lista del proveedor para cada modelo, separando
  entrada, salida (con descuento por caché cuando el proveedor lo aplica) y embeddings. Cada consulta
  guarda su costo al momento de hacerse, así que un cambio de precio futuro no altera el histórico.
- Los embeddings de Google no informan sus tokens, así que se **estiman** por longitud del texto.
- Si un modelo no tiene precio cargado en el sistema, sus consultas cuentan tokens pero no costo; el
  desglose lo marca como "sin precio".
- El costo es una **aproximación**, no la factura real. Para el monto exacto, consultar el panel del
  proveedor.

### 5.4 Desglose del consumo
- En **Estadísticas** de cada bot, la sección **Consumo por modelo y por día** muestra entrada,
  salida, embeddings, total y costo por modelo, y la serie de los últimos 30 días.
- La diferencia entre los embeddings del total y los de las consultas es la carga de documentos.

---

## 6. Documentos y archivos descargables

### 6.1 Documentos (base de conocimiento) — pestaña Documentos (operador)
- No confundir con la *base de conocimiento estructurada* (sección 7): esto son archivos que subís
  (PDF, TXT, DOCX); aquello son tablas con columnas que vos definís.
- Formatos: **PDF, TXT y DOCX**. Tamaño máximo **50 MB** por archivo.
- Al subir, el documento pasa por los estados **pendiente → procesando → listo** (o **error**,
  con el motivo visible). Solo los documentos **listos** se usan para responder.
- Los PDF escaneados (solo imagen) requieren que el servidor tenga instalado el OCR; si no,
  el documento queda con error.
- **Borrar un documento** elimina también sus fragmentos indexados: el bot deja de usarlo
  de inmediato.
- El bot responde **solo** con lo que encuentra en los documentos y en su personalidad. Si la
  información no está, lo dice explícitamente (ver sección 12).

### 6.2 Archivos descargables — pestaña Archivos (operador)
Son PDFs de uso práctico: formularios para completar, guías de presentación, instructivos.
- Se cargan con un **título** (obligatorio, ej. "Formulario de reclamo") y una **descripción**
  opcional (ej. "para reclamos ante la Subsecretaría; enviar completo a calidad@…"). La
  descripción es lo que el bot lee para decidir cuál ofrecer: conviene escribirla con
  claridad.
- Cuando el usuario pide algo que coincide ("necesito el formulario de reclamo"), el bot
  responde con el link clicable del archivo.
- El bot **no inventa links**: solo ofrece los archivos cargados.
- Se puede **copiar el link** de cada archivo y **borrarlo** (deja de estar disponible).
- Límite de tamaño: el mismo que los documentos (50 MB), solo PDF.

**Diferencia clave:** los *documentos* sirven para que el bot **responda preguntas**; los
*archivos descargables* sirven para que el bot **entregue el archivo**.

---

## 7. Base de conocimiento estructurada (tablas) — pestaña Base de conocimiento (operador)

Una tabla con las columnas que elijas (ej. "Empleados": DNI, nombre, área; o "Trámites": nombre,
costo, contacto) para que el bot la consulte al responder. A diferencia de los Documentos
(sección 6.1), acá no subís un archivo: cargás los datos directamente, fila por fila, como una
planilla.

### 7.1 Crear una tabla
- **Nombre** y, opcional, una **descripción**.
- **Columnas:** cada una tiene un nombre y un tipo — **texto, número, email o fecha**
  (AAAA-MM-DD).
- Las columnas se pueden **agregar** después de creada la tabla, pero **no se pueden borrar ni
  renombrar**: si cambiás la clave de una columna, las filas ya cargadas quedarían con datos
  guardados bajo una clave que ya no existe. Si necesitás otro esquema, creá una tabla nueva.

### 7.2 Cargar filas
- Desde **Ver filas**, en la lista de tablas: se agregan, editan y borran filas una por una,
  como una planilla simple. Una celda vacía es válida (no hace falta completar todas las
  columnas).
- Cada fila que cargás o editás se indexa igual que un fragmento de documento: el bot la
  encuentra por el **contenido**, no por una clave exacta. Funciona bien para "¿cuál es el
  teléfono de tal área?"; no está pensado para una búsqueda exacta por un dato puntual (ej.
  "buscame el trámite con número de expediente X") — para eso conviene un documento o
  archivo descargable.
- Cargar y editar filas **consume embeddings** (se cobra igual que subir un documento): se ve
  reflejado en el costo estimado del bot (sección 5.3).

### 7.3 Borrar
- **Borrar una fila** la saca de inmediato de lo que el bot puede encontrar.
- **Borrar la tabla completa** borra también todas sus filas: no se puede deshacer.

---

## 8. Consultas de "Hablar con una persona"

Cuando el bot tiene contacto configurado, el usuario puede:
- Tocar el botón 🆘 del encabezado, o
- Usar la opción que aparece debajo de una respuesta en la que el bot no encontró la
  información.

Se abre un **formulario** con nombre, email, teléfono (al menos uno de email o teléfono es
obligatorio) y la consulta. Además, si el bot tiene WhatsApp, el usuario puede escribir
directo por ahí.

### 7.1 Dónde se ven
- **Dentro de cada bot → pestaña Consultas:** las consultas de ese bot. Las ve quien tenga
  acceso al bot.
- **Menú "Consultas (todos los bots)":** solo superadmin. Lista todas, con filtro por
  pendientes o resueltas.

### 7.2 Gestión
- Cada consulta tiene estado **Pendiente** o **Resuelta**. Operador, admin y superadmin pueden
  marcarla como resuelta; queda registrado **quién** la resolvió y **cuándo**.
- Si se reabre, se borra ese registro (refleja la resolución vigente).
- ⚠️ junto a una consulta indica que **no se pudo enviar el aviso por correo**. La consulta
  igual quedó guardada y visible en el dashboard; conviene revisarla desde ahí.

### 7.3 Aviso por correo
- Cada consulta nueva se envía por correo a la dirección de **contacto para intervención
  humana** del bot (si está cargada).
- El correo depende de la configuración SMTP del servidor, que administra el equipo técnico.

---

## 9. Formularios al usuario — pestaña Formularios (operador)

A diferencia de "Hablar con una persona" (sección 8), que es un formulario fijo, acá **vos
definís los campos**. Sirve para pedirle datos estructurados al usuario y, si hace falta, que
adjunte un archivo — por ejemplo, un bot de Recursos Humanos que pida DNI y nombre, y permita
subir el certificado médico.

### 8.1 Crear un formulario
- **Título** y, opcional, una **descripción** (el usuario la ve antes de completar los campos)
  y un **mensaje de confirmación** (lo que ve al enviarlo; si no se carga, usa uno genérico).
- **Campos:** cada uno tiene una etiqueta, un tipo (**texto, número, email o archivo**) y si es
  obligatorio. Se pueden agregar, quitar y reordenar con las flechas. No hay un formulario fijo:
  se arma campo por campo, en el orden que elijas.
- Los campos tipo **archivo** aceptan PDF, JPG o PNG (hasta 10 MB). Puede haber más de uno
  (por ejemplo, "certificado médico" y "DNI escaneado" por separado).
- El formulario se puede dejar **inactivo**: deja de aparecer en el chat sin perder las
  respuestas ya recibidas.

### 8.2 Dónde lo ve el usuario
Si el bot tiene al menos un formulario activo, aparece el botón 🆘 del encabezado (el mismo
que "Hablar con una persona"): ahí se listan todos los formularios activos y, si corresponde,
la opción de contacto. Al completarlo y enviarlo, el usuario ve el mensaje de confirmación
como respuesta del bot.

### 8.3 Respuestas
- Se ven desde **Ver respuestas**, en la lista de formularios. Cada una muestra los datos
  cargados, el o los archivos adjuntos (se descargan desde ahí) y la fecha.
- Mismo flujo que las consultas: estado **Pendiente/Resuelta**, con quién y cuándo la resolvió.
- **El bot no vuelve a consultar estos datos**: quedan para que el equipo las revise. Si
  necesitás que el bot responda preguntas usando esta información, es una funcionalidad
  distinta (está en evaluación).
- Los DNI, certificados y demás datos del formulario pueden ser información sensible: los ve
  quien ya tiene acceso a ese bot (los mismos roles que las consultas y los documentos), no hay
  un permiso aparte. Tenerlo en cuenta antes de asignar operadores a un bot con formularios
  sensibles.
- **Borrar un formulario** borra también sus respuestas y los archivos adjuntos.

---

## 10. Subida de PDF por el usuario en el chat

Si está habilitado (admin, en Publicación), el usuario puede adjuntar un PDF y preguntar sobre
su contenido.
- Tamaño máximo **8 MB** y hasta **30 páginas** analizadas (si el documento es más largo, se
  avisa que se analizó un extracto).
- El documento se usa **solo en esa conversación**. No se incorpora a la base de conocimiento
  del bot ni lo ven otros usuarios. Subir otro PDF en la misma conversación reemplaza al
  anterior.
- El texto queda guardado en el historial de esa conversación (como todos los mensajes).

---

## 11. Accesos: quién ve cada bot (admin)

Pestaña **Acceso**:
- El **dueño** (quien creó el bot) y los **admin / superadmin** ven siempre el bot.
- Para dar acceso a alguien más, se lo **asigna** al bot. Un usuario asignado ve el bot y,
  según su rol (viewer, operator), puede hacer lo que su rol permite dentro de ese bot.
- Quitar la asignación le quita el acceso al bot.

---

## 12. Cómo se comporta el bot (importante para configurar bien)

- **Responde con lo que dicen sus documentos** y, si no encuentra la información, lo dice:
  *"No tengo información sobre eso en mis documentos."* No debe inventar datos (fechas,
  nombres, cantidades). Si nota que una pregunta no está en sus documentos, sugiere reformularla.
- **Personalidad:** el system prompt define cómo habla. Funciona mejor cuando describe el tono
  con claridad y ejemplos concretos. Si se deja vacío, el bot usa un tono neutral y profesional.
- **Documentos muy extensos y en tono académico:** con muchos fragmentos, algunos modelos tienden
  a repetir el estilo del documento en lugar de la personalidad configurada. Si pasa, probar
  **bajar el Top K** o usar un **modelo más capaz** (ambos en Configuración).
- **Seguridad:** el bot no revela sus instrucciones internas, no accede a otros bots ni al
  sistema, e ignora intentos de cambiar sus reglas desde el chat.
- **Mensajes de falla:** si el sistema tiene un problema técnico, el usuario ve un mensaje
  genérico y la oferta de contacto humano, nunca el error técnico.

---

## 13. Estadísticas y conversaciones

- **Estadísticas (por bot):** conversaciones, mensajes, tokens usados (desglosados), costo estimado en
  USD y consumo por modelo y por día.
- **Conversaciones:** listado de las sesiones del bot. Se puede abrir cada una para leer el
  intercambio completo. Es útil para revisar la calidad de las respuestas y detectar preguntas
  frecuentes sin respuesta (que luego pueden pasar a documentos).
- Las conversaciones quedan guardadas en la base de datos.

---

## 14. Embed: publicar el bot en un sitio

Pestaña **Embed** (operador y superior):
- **Script del widget:** burbuja flotante para pegar en cualquier sitio web.
- **iframe:** chat embebido en una página.
- **Abrir en nueva pestaña:** enlace directo a la página de chat.

Si el bot tiene **API keys de acceso** (admin, en la misma pestaña), el widget ya incluye la key
y el chat solo funciona desde los dominios permitidos por esa key.

---

## 15. Logos institucionales (superadmin)

En **Proveedores de IA → Marca institucional**:
- **Logo del Gobierno:** aparece en el encabezado de todos los bots.
- **Logo de Modernización:** aparece como pie del chat en todos los bots (con fondo de color
  del bot, por eso conviene un logo claro o blanco con fondo transparente).

---

## 16. Usuarios y proveedores globales (superadmin)

- **Usuarios:** crear usuarios con su rol, editar datos y rol.
- **Proveedores de IA:** claves globales por proveedor, usadas para actualizar la lista de
  modelos disponibles, y la URL de Ollama. Cada bot sigue usando su propia API key para
  responder (sección 5). Las claves se guardan cifradas y no se muestran después de cargarlas.

---

## 17. Buenas prácticas

1. Cargar primero los documentos y luego probar el bot con preguntas reales antes de publicarlo.
2. Escribir la descripción de cada archivo descargable pensando en lo que va a preguntar el usuario.
3. Revisar periódicamente las consultas pendientes y los ⚠️ de correo.
4. Revisar las conversaciones para detectar preguntas sin respuesta y cargar esos temas en los documentos.
5. Configurar el límite mensual de tokens para evitar gastos sorpresa.
6. No compartir las API keys por chat o correo; cargarlas directamente en el dashboard.
7. Dar a cada persona el rol mínimo que necesita.

---

## 18. Limitaciones conocidas

- El bot responde según sus documentos y su configuración: no reemplaza la verificación humana
  en trámites o decisiones formales. Para eso está el contacto humano.
- El costo estimado de Estadísticas es una aproximación según los precios de lista (ver sección 5.3).
- Los PDF escaneados requieren OCR en el servidor para poder leerse.
- Si el modelo elegido tarda demasiado, el proxy del servidor puede cortar la respuesta; en ese
  caso el usuario ve el mensaje genérico. Un modelo más rápido o menos contexto lo evitan.
- Los **archivos descargables** son accesibles para cualquiera que tenga el link (son públicos
  por naturaleza). No cargar allí información confidencial. Los documentos de la base de
  conocimiento no se publican como archivos: solo el bot los usa para responder.
