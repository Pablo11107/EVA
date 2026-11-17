# Revisión de seguridad del despliegue en servidor propio

Noviembre de 2026. Typebot 3.19.1 (publicada el 20 de octubre de 2026), burbuja `@typebot.io/js`
0.10.11, flujo de EVA v9.

## Método

Se ha atacado el despliegue como se ataca a un chatbot incrustado en una web: primero la
infraestructura (qué hay expuesto, cómo se entra al editor, cómo viaja el tráfico), después el
canal entre la web y el bot (quién puede hablar con él y desde dónde), y por último la
conversación en sí (texto libre, inyecciones, sesiones ajenas, variables). Para cada vector se
ha leído el código de Typebot 3.19.1 que lo gobierna y, donde ha sido posible, se ha probado
contra el bot real en la nube.

**Qué no se ha podido hacer aquí**: no hay Docker en el equipo donde se preparó el paquete, así
que el despliegue no se ha levantado. Por eso el paquete incluye `pruebas/atacar.py`: la
batería de ataques, lista para ejecutarla contra el servidor real desde Internet. Hasta que todas
den OK, nada de lo que sigue debe darse por hecho. Tampoco se ha validado la sintaxis del
Caddyfile ni de la configuración de nginx (no estaban instalados): el paso 3 de la instalación lo
hace con el propio Caddy.

## Lo que la empresa planteó, y qué pasa con ello

**Propiedad intelectual.** Con el servidor propio, EMALSA tiene el software, la base de datos y
el flujo. El flujo (`flujo/eva-chatbot.json`) es un archivo JSON que se exporta e importa
libremente; no tiene formato propietario cerrado. La licencia de Typebot (FSL-1.1-Apache-2.0)
permite el uso interno y publicar bots propios en productos propios; cada versión pasa a Apache
2.0 a los dos años. No permite revender el editor ni alojarlo para terceros, que no es el caso.

**Protección de datos.** Las conversaciones dejan de salir de la empresa: Typebot ya no es
encargado del tratamiento y el DPA que había que pedirles deja de ser necesario. Lo que se
guarda de cada conversación es fecha, botones pulsados y si se llegó al final; no hay texto
libre, ni IP, ni datos del navegador (la IP la ve el proxy, que no guarda registros de acceso
salvo que se activen). El plazo de conservación, que en la nube era una tarea manual, lo hace
`scripts/purgar-resultados.sh` cada noche. Quien mantiene el contenido sigue siendo encargado
del tratamiento si accede a los resultados: el contrato de encargo sigue haciendo falta.
Para el informe mensual no necesita ese acceso: `scripts/estadisticas-mes.py` se ejecuta en el
servidor y solo guarda recuentos (sin identificadores, horas exactas ni recorridos individuales),
y el informe se genera a partir de ellos. La consulta usa variables de psql y valida el mes y el
identificador del bot antes de ejecutarse; el informe escapa todo texto que venga del flujo y no
carga nada de fuera.
El informe y las estadísticas salen de la empresa por correo (`scripts/enviar-informe.py`, a
`EVA_INFORME_PARA`): solo llevan recuentos. El envío usa el buzón de salida de la empresa y no
manda la contraseña del buzón si el servidor de correo no ofrece TLS.

**Mantenimiento.** Aparece una tarea nueva, actualizar Typebot una vez al mes (cada versión
trae correcciones de seguridad, y 3.19.0 trajo varias). Está descrita en el README con las
huellas de las imágenes para que no se actualice a ciegas. Desaparece otra: vigilar el cupo del
plan. El resto del mantenimiento (contenido, enlaces, revisión mensual) no cambia.

## Hallazgos

Ordenados por lo que le costaría a un atacante y lo que ganaría. «De fábrica» es el
`docker-compose.yml` oficial de Typebot con su `.env.example`; «paquete» es lo que hace este.

### 1. Cualquier script puede hablar con el bot aunque no sea emalsa.es

**Ataque.** El bot tiene una lista de orígenes permitidos (emalsa.es). Un atacante escribe un
script que llama a la API del visor sin cabecera `Origin`, o con cualquier otra cosa.

**Qué hace Typebot.** `assertOriginIsAllowed` (en `packages/bot-engine`) deja pasar la petición
cuando *no hay* cabecera `Origin`. La lista solo la hacen cumplir los navegadores. Comprobado
contra el bot en la nube: sin `Origin`, 200; con `Origin: https://evil.example`, 403. La
documentación de autoalojamiento no menciona ningún ajuste para cambiarlo.

**Impacto.** Bajo para los datos (el bot no tiene nada que no esté en la web de EMALSA), pero
permite llenar los resultados de conversaciones falsas, que son las que se usan para medir qué
preguntan los clientes, y usar el visor de EMALSA como servicio para una web ajena.

**Paquete.** El proxy exige siempre `Origin` con el patrón `^https://(www\.)?emalsa\.es$`; sin
él o con otro, 404. Un script puede falsificar la cabecera, pero ya no basta con olvidarla, y el
clon de la web en otro dominio queda fuera. `atacar.py` prueba seis variantes (sin Origin, web
ajena, dominios parecidos, `http://`, `null`).

### 2. El editor expuesto a Internet sin TLS y con registro abierto

**Ataque.** De fábrica, el editor escucha en el puerto 8080 en claro, en todas las interfaces,
con `DISABLE_SIGNUP` desactivado: cualquiera con un correo se registra, crea su espacio de
trabajo y usa el servidor de EMALSA para sus propios bots (o para intentar escalar desde dentro).
Los registros de Typebot muestran correcciones de seguridad precisamente en espacios de trabajo
de invitados (3.19.0).

**Paquete.** El editor no publica ningún puerto; solo llega a él Caddy, con TLS, y solo desde las
redes internas (403 desde fuera). `DISABLE_SIGNUP=true`: solo entran invitados. No hay
contraseñas que adivinar: el acceso es por código de un solo uso al correo (o cuenta corporativa
de Microsoft), y Redis limita los intentos por IP. `atacar.py` comprueba que el editor no
responde desde Internet.

### 3. Base de datos con contraseña «typebot» y clave de cifrado de ejemplo

**Ataque.** El `.env.example` oficial trae `ENCRYPTION_SECRET=do+UspMmB/rewbX2K/rskFmtgGSSZ8Ta`
y `POSTGRES_PASSWORD=typebot`. Quien no los cambie tiene una base de datos con la contraseña
pública y credenciales cifradas con una clave pública. PostgreSQL no publica puerto de fábrica,
pero sí está en la misma red que todo.

**Paquete.** `generar-secretos.sh` genera ambos; `docker compose` se niega a arrancar si
`POSTGRES_PASSWORD` está vacío; `test_paquete.py` comprueba que el ejemplo nunca lleve la clave
oficial ni ningún valor. PostgreSQL y Redis en una red interna sin salida a Internet, a la que
el proxy no llega. `atacar.py` escanea 5432, 6379, 8080, 8081 y 3000.

### 4. Superficie del visor: páginas, API del editor, plantillas

**Ataque.** El visor sirve mucho más que la burbuja: la portada (que enlaza al editor y revela su
URL), la página independiente de cada bot, las plantillas de Typebot (`/api/v1/templates/...`,
que permiten arrancar conversaciones con bots de demostración en el servidor de EMALSA), la
documentación OpenAPI, y rutas de la API v2.

**Paquete.** Desde Internet, el visor solo responde a las tres rutas de la burbuja
(`/api/v1/typebots/eva/startChat`, `/api/v1/sessions/*/continueChat`,
`/api/v1/sessions/*/clientLogs`), solo con `POST`/`OPTIONS`, solo con el `Origin` correcto y solo
para el identificador `eva`. Todo lo demás, 404. La red interna ve el visor completo porque el
editor lo necesita para la vista previa. `atacar.py` recorre diez rutas y cuatro métodos.

### 5. Sin cabeceras de seguridad en las respuestas públicas

**Ataque.** El visor solo pone `Content-Security-Policy` y `Referrer-Policy` en `/__preview`
(`apps/viewer/src/proxy.ts`). El resto de respuestas sale sin HSTS, sin `frame-ancestors`, sin
`X-Content-Type-Options`, y con la cabecera `Server`. La documentación de Typebot no dice nada de
cabeceras; da por hecho que las pone el proxy.

**Paquete.** Caddy añade HSTS (un año), `X-Content-Type-Options: nosniff`,
`Referrer-Policy: no-referrer`, `Permissions-Policy` restrictiva, `CSP: default-src 'none';
frame-ancestors 'none'` y `Cache-Control: no-store` en la API, y quita `Server` y
`X-Powered-By`. TLS lo termina Caddy (Typebot no hace TLS). `atacar.py` comprueba cada una y la
versión de TLS.

### 6. Preflight CORS para cualquier origen

**Ataque.** La API responde al `OPTIONS` de cualquier web con
`Access-Control-Allow-Origin: <esa web>` (comprobado en la nube con `evil.example`). Es
necesario para que Typebot sirva burbujas en cualquier web, pero aquí solo hay una web.

**Paquete.** El `OPTIONS` pasa por el mismo filtro de `Origin` que el `POST`: desde otra web, 404
sin cabeceras CORS. `atacar.py` lo comprueba.

### 7. Texto libre, inyecciones y manipulación de la conversación

**Ataque.** Enviar texto en lugar de pulsar un botón: instrucciones «al sistema», HTML, SQL,
5 000 caracteres, JSON con forma de bloque. Reutilizar el `resultId` de otro visitante o
precargar variables al iniciar. Adivinar o recorrer sesiones ajenas.

**Qué hace Typebot.** `parseSingleChoiceReply` solo acepta una respuesta si coincide con el
identificador, el valor o el texto exacto de un botón; lo demás es «fail» y el flujo no avanza.
No hay modelo de lenguaje al que engañar. El flujo de EVA no define variables, así que
`prefilledVariables` no tiene dónde caer (y el verificador del repositorio impide que se
definan). Las sesiones tienen identificadores aleatorios de 25 caracteres y caducan.

**Paquete.** Nada que añadir en el servidor; lo que protege es el flujo y las reglas del
repositorio (`scripts/verificar.py`, `tests/`). El proxy limita el cuerpo a 64 KB, con lo que
los 5 000 caracteres ni llegan. `atacar.py` repite los ataques de `tests/test_en_vivo.py` contra
el servidor nuevo y comprueba que la bienvenida publicada es la del flujo revisado.

### 8. Cadena de suministro

**Ataque.** `image: baptistearno/typebot-builder:latest` se actualiza solo a lo que haya en Docker
Hub en cada `pull`; una cuenta comprometida o una etiqueta movida cambiarían el software sin que
nadie lo revise. Lo mismo para la burbuja si se cargara de un CDN.

**Paquete.** Las cinco imágenes van fijadas por versión y huella SHA-256; `test_paquete.py` falla
si alguna deja de estarlo. La burbuja se sirve desde la propia web, con la huella SRI del
repositorio. Las actualizaciones son una decisión explícita, con copia previa y ataque posterior.

### 9. Lo que no se ha cubierto, y por qué

- **Denegación de servicio.** Caddy sin complementos no limita peticiones por IP. EVA es ligero y
  el filtro de `Origin` deja fuera la mayor parte del ruido automático, pero un atacante decidido
  puede saturar el visor. Si pasa, la respuesta es un cortafuegos de aplicación o `fail2ban`
  sobre los registros del proxy; no está en el paquete porque depende de lo que ya tenga la
  empresa.
- **Falsificar `Origin` desde un script.** El proxy exige la cabecera, pero un script puede
  escribirla. Ninguna configuración de servidor puede distinguir un navegador real de un script
  que lo imita; el impacto se queda en resultados falsos en las estadísticas.
- **Un intruso en la red interna.** Desde dentro, el editor pide un código al correo invitado y
  Redis limita los intentos. Si la red interna no es de confianza, restringir el editor a la VPN
  o a las IP del equipo de mantenimiento, en el Caddyfile.
- **El servidor en sí.** Actualizaciones del sistema operativo y de Docker, SSH con clave,
  cortafuegos que solo abra 80 y 443: es lo habitual de cualquier servidor de la empresa y no
  es específico de EVA.
- **La web de emalsa.es.** La burbuja se ejecuta dentro de esa web; si la web tiene una
  vulnerabilidad XSS, la burbuja la hereda. La CSP recomendada en el README limita el daño.

## Lo que hay que hacer antes de abrir EVA al público

1. Instalar siguiendo el README, incluido `caddy validate`.
2. Ejecutar `pruebas/atacar.py` desde fuera de la red de la empresa y conseguir que todo dé OK.
3. Ejecutar `EVA_PRUEBAS_EN_VIVO=1` con `tests/test_en_vivo.py` apuntado al visor nuevo (cambiar
   `API` y `BOT` en el archivo, o mejor, parametrizarlos cuando se haga la migración de la web).
4. Firmar el contrato de encargo del tratamiento con quien mantenga el contenido.
5. Entonces, y no antes, `scripts/apuntar-web.py` para la página de demostración, y publicar.
