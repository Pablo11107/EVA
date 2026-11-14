# EVA en servidor propio

Paquete para alojar EVA en un servidor de EMALSA, sin depender de la nube de Typebot. Está pensado
para el equipo de sistemas: un servidor Linux con Docker, dos nombres DNS y una tarde.

Lo que cambia respecto a la nube, en una frase: **todo (el editor, el bot publicado y las
conversaciones) pasa a estar en la empresa**. Typebot deja de ser encargado del tratamiento, no
hay cupo de conversaciones ni cuota mensual, y la licencia del software (FSL-1.1-Apache-2.0)
permite expresamente este uso: una empresa que publica sus propios bots en su propia web.
Lo que no permite es revender el acceso al editor o alojar Typebot para terceros.

## Qué hay en el paquete

| Archivo | Para qué |
|---|---|
| `docker-compose.yml` | Los cinco servicios: proxy (Caddy), editor, visor, PostgreSQL y Redis. Imágenes fijadas por huella |
| `.env.ejemplo` | Configuración comentada. Se copia a `.env` y se rellena |
| `proxy/Caddyfile` | TLS automático, cabeceras de seguridad y quién puede hablar con qué |
| `proxy/nginx-eva.conf` | Lo mismo para quien ya tenga nginx (sin probar aquí; validar con `nginx -t`) |
| `scripts/generar-secretos.sh` | Genera la clave de cifrado y la contraseña de la base de datos |
| `scripts/copia-seguridad.sh` | Copia diaria de la base de datos, 30 días de histórico |
| `scripts/purgar-resultados.sh` | Plazo de conservación automático de las conversaciones (90 días) |
| `scripts/preparar-flujo.py` | Genera `flujo/eva-chatbot.servidor-propio.json`, el flujo a importar |
| `scripts/apuntar-web.py` | Cuando todo funcione: apunta la página de demostración al visor nuevo |
| `web/incrustar-eva.html` | El bloque que se pega en emalsa.es |
| `pruebas/atacar.py` | Ataca el despliegue desde Internet y comprueba que todo queda fuera |
| `pruebas/test_paquete.py` | Pruebas sin conexión del propio paquete (se ejecutan en CI) |
| `REVISION-SEGURIDAD.md` | Qué ataques se han contemplado, qué se encontró y qué hace el paquete con cada uno |

## Arquitectura

```
Internet ──443──▶ Caddy ──▶ visor  (solo 3 rutas de la API, solo desde emalsa.es)
                   │
Red interna ─443─▶ Caddy ──▶ editor (solo desde la red interna)
                            visor completo (vista previa del editor)

editor ◀──red interna sin salida──▶ PostgreSQL, Redis ◀──▶ visor
```

- **Visor** (`asistente.emalsa.es`): lo que usa la burbuja de la web. Desde Internet solo responde
  a tres rutas (`startChat`, `continueChat`, `clientLogs`) y solo si la petición trae
  `Origin: https://emalsa.es` o `https://www.emalsa.es`. Todo lo demás, 404.
- **Editor** (`eva-editor.emalsa.es`): donde se cambia el contenido. Solo desde la red interna
  (o VPN). Nadie puede registrarse: solo entran las personas invitadas.
- **Base de datos y Redis**: en una red Docker interna sin acceso a Internet. Ningún puerto suyo
  llega al servidor ni a la red.

Los nombres son ejemplos: se cambian en `.env`. Lo único obligatorio es que sean **dos nombres
distintos** (Typebot lo exige: comparten cookies si solo cambia el puerto).

## Requisitos

- Servidor Linux x86_64 o ARM64 con Docker Engine 24 o posterior y Docker Compose v2. 2 CPU, 4 GB
  de RAM y 20 GB de disco sobran: EVA atiende unas decenas de conversaciones al día.
- Dos registros DNS tipo A apuntando al servidor, para que Caddy obtenga los certificados de
  Let's Encrypt. Puertos 80 y 443 abiertos desde Internet al servidor. Si el editor debe ser
  solo interno también a nivel de DNS, usar un certificado de la CA de la empresa
  (`tls /ruta/cert.pem /ruta/clave.pem` en el bloque del editor del Caddyfile).
- Un buzón de correo saliente (SMTP) para que el editor envíe los códigos de inicio de sesión.
  Alternativa: inicio de sesión con la cuenta corporativa de Microsoft 365 (ver `.env.ejemplo`).
- Python 3 en el equipo desde el que se ejecuten las pruebas (no hace falta en el servidor).

## Instalación

1. **Copiar el paquete** al servidor, por ejemplo en `/opt/eva`, con un usuario sin privilegios
   que pertenezca al grupo `docker`.

2. **Configurar**:
   ```bash
   cd /opt/eva
   cp .env.ejemplo .env && chmod 600 .env
   scripts/generar-secretos.sh        # ENCRYPTION_SECRET y contraseña de PostgreSQL
   nano .env                          # dominios, correo del administrador, SMTP
   ```
   El script avisa de lo que queda por rellenar. Ajustar también las redes internas en
   `proxy/Caddyfile` (aparecen dos veces, en el visor y en el editor).

3. **Comprobar la configuración del proxy** antes de arrancar:
   ```bash
   docker compose run --rm proxy caddy validate --config /etc/caddy/Caddyfile
   ```

4. **Arrancar**:
   ```bash
   docker compose up -d
   docker compose logs -f typebot-builder   # la primera vez crea las tablas; esperar a «Ready»
   ```

5. **Entrar en el editor** desde la red interna: `https://eva-editor.emalsa.es`. Escribir el
   correo de `ADMIN_EMAIL`; llega un código de un solo uso. Esa cuenta tiene plan ilimitado.

6. **Importar EVA**: en el editor, *Create a typebot → Import a file* y elegir
   `flujo/eva-chatbot.servidor-propio.json`. Es el flujo revisado del repositorio con los
   orígenes permitidos de la empresa; `scripts/preparar-flujo.py` lo regenera y
   `pruebas/test_paquete.py` comprueba que es idéntico al revisado.

7. **Publicar**: botón *Publish*. En *Share*, cambiar el identificador público a `eva` (o el que
   se haya puesto en `EVA_PUBLIC_ID`). Si no coincide, Caddy responderá 404 a la web.
   El flujo preparado ya trae desactivada la marca «Made with Typebot»; si aun así apareciera,
   es que el espacio de trabajo está en plan *Free* (ver «Si algo falla») y el interruptor está
   en *Theme → General → Typebot.io branding*.

8. **Atacar el despliegue desde fuera** (desde una conexión que no sea la red de la empresa):
   ```bash
   python3 pruebas/atacar.py --visor https://asistente.emalsa.es --editor https://eva-editor.emalsa.es --bot eva
   ```
   Todas las pruebas deben dar OK. Abre unas diez conversaciones de prueba, que aparecerán en los
   resultados del editor y se pueden borrar.

9. **Incrustar en emalsa.es**: ver `web/incrustar-eva.html`. Copiar `vendor/typebot-web.js` del
   repositorio a la web (no se carga de ningún CDN) y pegar el bloque antes de `</body>`.

10. **Programar las tareas** (usuario `eva`, `/etc/cron.d/eva`):
    ```
    15 3 * * * eva /opt/eva/scripts/copia-seguridad.sh   >> /var/log/eva-copias.log 2>&1
    45 3 * * * eva /opt/eva/scripts/purgar-resultados.sh >> /var/log/eva-purga.log  2>&1
    ```

## La web de la empresa

La burbuja se carga en emalsa.es y habla con el visor. El servidor web de emalsa.es debería
enviar una Content-Security-Policy que lo permita y nada más. Si la web ya tiene una, añadir el
visor a `connect-src` e `img-src`; si no la tiene, este es un punto de partida para la página que
lleve la burbuja:

```
Content-Security-Policy: default-src 'self'; script-src 'self'; connect-src 'self' https://asistente.emalsa.es;
  img-src 'self' data: blob: https://asistente.emalsa.es; style-src 'self' 'unsafe-inline';
  font-src 'self'; frame-ancestors 'self'; object-src 'none'; base-uri 'none'
```

(`'unsafe-inline'` en `style-src` lo necesita la propia burbuja de Typebot para sus estilos.)

## Operación

**Actualizar Typebot** (una vez al mes; cada versión trae correcciones de seguridad):

1. Mirar la versión y las notas en https://github.com/baptisteArno/typebot.io/releases y los
   cambios que rompen en https://docs.typebot.com/self-hosting/breaking-changes.
2. Obtener las huellas nuevas: `docker buildx imagetools inspect baptistearno/typebot-builder:3.X.Y`
   (y `typebot-viewer`). Cambiar versión y huella en `docker-compose.yml`, en los dos servicios.
3. `scripts/copia-seguridad.sh && docker compose pull && docker compose up -d`.
4. Abrir la web, hablar con EVA, y pasar `pruebas/atacar.py`.

Lo mismo, con menos frecuencia, para `postgres`, `redis` y `caddy`. Una versión mayor de
PostgreSQL (16 → 17) requiere migrar los datos: no cambiarla sin leer su guía.

**Copias**: `scripts/copia-seguridad.sh` guarda `copias/typebot-AAAAMMDD-HHMM.sql.gz` con
permisos 600 y borra las de más de 30 días. Guardar `.env` aparte, en el gestor de secretos de la
empresa: sin `ENCRYPTION_SECRET` la copia no restaura lo cifrado. Restaurar:
`gunzip -c copias/X.sql.gz | docker compose exec -T typebot-db psql -U postgres typebot`.

**Conservación de datos**: `scripts/purgar-resultados.sh` borra cada noche las conversaciones con
más de 90 días (`EVA_RETENCION_DIAS` para cambiarlo) y las sesiones inactivas. Un resultado de EVA
contiene fecha, botones pulsados y si llegó al final; no hay texto libre, IP ni datos del
navegador. Los registros de acceso de Caddy no están activados; si se activan, fijarles también
un plazo.

**Cuentas**: se invita desde el editor (*Settings & Members*). Cada persona con su correo, nunca
cuentas compartidas, y se retira al dejar el proyecto. La persona que mantiene el contenido
necesita acceso al editor desde la red interna o por VPN.

**Cambios de contenido**: igual que en la nube, con el ciclo del repositorio: exportar el flujo,
`python3 scripts/verificar.py`, pruebas, commit, y solo entonces publicar. Después,
`python3 servidor-propio/scripts/preparar-flujo.py` para que el flujo del paquete siga al día.

**Monitorización**: `https://asistente.emalsa.es/healthz` responde 200 mientras el visor esté
vivo; sirve para el sistema de monitorización de la empresa.

## Si algo falla

| Síntoma | Causa habitual |
|---|---|
| La web no muestra la burbuja o dice «No encontrado» | `EVA_PUBLIC_ID` no coincide con el identificador puesto en *Share*; o la web no es `emalsa.es`/`www.emalsa.es` (el proxy exige ese `Origin`) |
| «Origin not allowed» (403) | Los orígenes del flujo importado no incluyen la web. Importar el JSON preparado, no el de la nube |
| El editor no carga la vista previa | Editor y visor en el mismo nombre de dominio; o la red interna no está en la lista del Caddyfile |
| No llega el código de inicio de sesión | SMTP mal configurado, o el servidor de correo es interno y falta `SSRF_ALLOWED_HOSTS` |
| El administrador aparece con plan *Free* | `ADMIN_EMAIL` no coincide con el correo con el que se entró |
| `docker compose up` falla en la base de datos | `POSTGRES_PASSWORD` y la contraseña de `DATABASE_URL` no coinciden |

Logs: `docker compose logs --since 1h typebot-viewer` (o `typebot-builder`, `proxy`).
`TYPEBOT_DEBUG=true` en `.env` da más detalle; quitarlo después.
