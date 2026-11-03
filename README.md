# EVA
Emalsa Virtual Assistant — página de demostración del asistente virtual de atención al cliente de EMALSA.

Publicada en GitHub Pages: https://pablo11107.github.io/EVA/ (marcada `noindex`: es una demo, no un canal oficial).

## Qué hay en el repositorio

| Ruta | Qué es |
|---|---|
| `index.html` | La página completa: HTML, CSS y JavaScript sin paso de compilación |
| `vendor/three.module.js` | three.js 0.160.0, para la escena 3D. Si no carga, la página sigue funcionando |
| `vendor/typebot-web.js` | `@typebot.io/js` 0.10.11, la burbuja del asistente |
| `vendor/fonts/` | Fuente Outfit (licencia OFL, en `OFL.txt`) |
| `flujo/eva-chatbot.json` | Exportación del flujo de Typebot que está publicado |
| `scripts/verificar.py` | Comprobaciones de seguridad (ver más abajo) |
| `tests/` | Pruebas de seguridad de IA: sin conexión (CI) y contra el bot real |
| `.github/workflows/verificar.yml` | Ejecuta el verificador y las pruebas en cada push |

Las librerías y la fuente se sirven desde el propio sitio: la página no depende de ningún CDN
ni envía la IP de los visitantes a Google. No hay base de datos ni servidor propio. Las cifras
de la sección de analíticas son de ejemplo.

## El asistente

El flujo se edita y publica en [Typebot](https://typebot.io). La página solo lo incrusta con
su identificador (`eva-asistente-virtual-de-emalsa-oi2fy0m`).

Lo que dice EVA cambia en cuanto se publica en Typebot, sin pasar por este repositorio. Por eso
cada versión del flujo debe guardarse aquí y pasar el verificador **antes** de publicarla:

1. En Typebot: *Share → Export* y guardar el JSON como `flujo/eva-chatbot.json`.
2. `python3 scripts/verificar.py && python3 -m unittest discover -s tests`
3. Revisar el diff, hacer commit y, solo entonces, publicar en Typebot.
4. Tras publicar: `EVA_PRUEBAS_EN_VIVO=1 python3 -m unittest tests.test_en_vivo -v`, que comprueba
   que lo publicado es exactamente lo revisado.

El bot solo acepta peticiones de los orígenes permitidos en Typebot (`pablo11107.github.io`,
`emalsa.es` y `www.emalsa.es`). Si se abre la página en local, responde «Origin not allowed»
(403). Esa lista solo la comprueban los navegadores: un script puede saltársela, así que
**no sirve como control de acceso** y las métricas pueden incluir conversaciones automatizadas.

## Seguridad

GitHub Pages no permite cabeceras propias, así que la Content-Security-Policy va en una
etiqueta `<meta>` al principio de `index.html`. Solo permite scripts del propio sitio y los
scripts en línea autorizados por su hash, y solo conecta con Typebot.

`scripts/verificar.py` (solo biblioteca estándar de Python) comprueba:

- que la CSP autoriza exactamente los scripts en línea de la página;
- que las librerías de `vendor/` coinciden con su huella SRI del `importmap`;
- que el flujo solo tiene bloques de texto, botones y redirecciones (nada de webhooks, IA, campos
  de texto ni scripts), sin variables, con *Remember user* desactivado y orígenes permitidos acotados;
- que los botones «Rellenar formulario», «Llamar» y «Escribir por formulario» solo abren páginas de
  `https://emalsa.es` o llaman a los teléfonos oficiales, y que cada trámite abre el mismo
  formulario que indica por escrito;
- que las cifras de la portada (pantallas, mensajes, trámites) coinciden con el flujo;
- que todos los enlaces del flujo van a `https://emalsa.es` y que solo aparecen los teléfonos
  oficiales (928 926 033 y 928 010 334).

Si se modifica un `<script>` en línea, hay que recalcular la CSP o el navegador lo bloqueará:

```sh
python3 scripts/verificar.py --actualizar-csp
```

Para cambiar la versión de una librería: sustituir el fichero en `vendor/` y actualizar su huella
en el `importmap` (`openssl dgst -sha384 -binary vendor/<fichero> | base64`).

Para añadir algo nuevo al flujo (un dominio, un teléfono, un tipo de bloque), se amplían las
listas al principio de `scripts/verificar.py` en un commit aparte que se pueda revisar.

### Seguridad de IA

EVA no usa ningún modelo de lenguaje: es un árbol de botones con respuestas escritas y revisadas.
No hay prompt de sistema, ni RAG, ni texto libre, ni datos del usuario guardados en variables.
La protección contra inyección de prompt, jailbreak y mezcla de datos entre usuarios es esa
estructura, y el verificador impide que cambie sin revisión: rechaza cualquier bloque que no sea
de texto, de botones o una redirección a emalsa.es o a un teléfono oficial (IA, campos de texto,
webhooks, código), las variables, la precarga por URL
y *Remember user*.

- `tests/test_seguridad_ia.py` (sin conexión, en CI): introduce cada vulnerabilidad en una copia
  del flujo o de la página y demuestra que el verificador la bloquea.
- `tests/test_en_vivo.py` (manual, abre unas trece conversaciones reales): ataca al bot publicado
  con inyecciones directas, disfrazadas de opción válida, con caracteres invisibles, HTML, falsos
  turnos de conversación y variables inyectadas; comprueba que el bot solo responde con contenido
  idéntico al del flujo revisado y que una sesión no puede leer ni reanudar otra.

Si algún día se añade la opción de escribir la consulta con sus palabras, el modelo debe limitarse
a devolver un identificador de una lista cerrada, validado en el servidor antes de seguir el flujo.
Nunca debe redactar la respuesta ni recibir datos de otras sesiones. Esas pruebas tendrán que
ampliarse antes de publicarlo.

## Instalarlo en emalsa.es

El bot ya admite `emalsa.es` y `www.emalsa.es` como orígenes. Basta con copiar a la web
`vendor/typebot-web.js` y añadir antes de `</body>`, en las páginas donde deba aparecer:

```html
<script type="module">
  import Typebot from '/ruta/a/typebot-web.js'
  Typebot.initBubble({
    typebot: "eva-asistente-virtual-de-emalsa-oi2fy0m",
    theme: { button: { backgroundColor: "#214881" }, chatWindow: { backgroundColor: "#FFFFFF" } },
  });
</script>
```

Si la web tiene Content-Security-Policy, debe permitir como mínimo:
`connect-src https://typebot.io https://*.typebot.io`,
`img-src https://typebot.io https://*.typebot.io data:`,
`style-src 'unsafe-inline' https://fonts.bunny.net` y `font-src https://fonts.bunny.net`.

## Traspaso a la empresa

Hoy el bot está en una cuenta personal de Typebot y esta página en una cuenta personal de GitHub.
Antes de ponerlo en producción hay que decidir:

- **Plan de Typebot.** El plan gratuito muestra «Made with Typebot» y limita las conversaciones
  mensuales. Un plan de pago quita la marca, amplía el cupo y permite alertas de uso.
- **Titularidad.** Pasar el bot a un espacio de trabajo de la empresa (o añadirla como miembro)
  y decidir quién puede publicar cambios.
- **Protección de datos.** Typebot guarda cada conversación (respuestas pulsadas, navegador e IP).
  Hace falta su contrato de encargado de tratamiento y fijar cuánto tiempo se conservan los
  resultados.

### Pendiente fuera del repositorio

- **Typebot:** activar la verificación en dos pasos, dejar en el espacio de trabajo solo a quien
  necesite editar, configurar alertas de uso y revisar el tiempo de conservación de resultados.
- **GitHub:** verificación en dos pasos en la cuenta que publica la página.
- **Al pasar a emalsa.es:** enviar la CSP como cabecera HTTP, con `frame-ancestors 'self'` para
  impedir que otra web incruste la página (en GitHub Pages no es posible).
