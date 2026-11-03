#!/usr/bin/env python3
"""Comprobaciones de seguridad de la página y del flujo de EVA.

    python3 scripts/verificar.py                  # comprueba todo
    python3 scripts/verificar.py --actualizar-csp # recalcula los hashes de la CSP

Comprueba:
  1. Que la CSP autoriza exactamente los scripts en línea de index.html.
  2. Que las librerías de vendor/ coinciden con su huella SRI del importmap.
  3. Que el flujo exportado de Typebot (flujo/eva-chatbot.json) es determinista:
     solo texto y botones, sin modelo de lenguaje, sin texto libre y sin
     variables. Es lo que hace imposible la inyección de prompt y la mezcla de
     datos entre usuarios: no hay modelo al que engañar ni datos que mezclar.
  4. Que solo enlaza a emalsa.es, solo da los teléfonos oficiales, no contiene
     datos personales y solo se puede incrustar en los dominios previstos.

Sale con código 1 si algo falla, para poder usarlo en CI. Solo usa la
biblioteca estándar.
"""
import base64
import hashlib
import json
import re
import sys
from pathlib import Path
from urllib.parse import urlparse

RAIZ = Path(__file__).resolve().parent.parent
HTML = RAIZ / "index.html"
FLUJO = RAIZ / "flujo" / "eva-chatbot.json"

# Lo único que el bot puede contener. Si se añade algo legítimo, se añade aquí
# a propósito, en un commit que se pueda revisar. Un bloque de IA (OpenAI,
# Anthropic, Mistral...), un campo de texto libre, un webhook o un script no
# entran sin revisión de seguridad: con ellos dejan de valer las garantías de
# arriba.
BLOQUES_PERMITIDOS = {"text", "choice input"}
DOMINIOS_PERMITIDOS = {"emalsa.es", "www.emalsa.es"}
TELEFONOS_PERMITIDOS = {"928926033", "928010334"}
ORIGENES_PERMITIDOS = {"https://pablo11107.github.io", "https://emalsa.es", "https://www.emalsa.es"}

RE_SCRIPT = re.compile(r"<script([^>]*)>(.*?)</script>", re.S)
RE_CSP = re.compile(r'(<meta http-equiv="Content-Security-Policy" content=")([^"]*)(")')
RE_TELEFONO = re.compile(r"(?<![\d/])(?:\+34[\s.]?)?([6789]\d{2})[\s.]?(\d{3})[\s.]?(\d{3})(?!\d)")
RE_URL = re.compile(r"""\b(?:https?|ftp|javascript|data|mailto|tel):[^\s"'<>\\)]*""", re.I)

# Datos personales o confidenciales que nunca deben estar en el contenido del bot.
DATOS_PERSONALES = {
    "DNI/NIE": re.compile(r"(?<![\w])(?:\d{8}|[XYZ]\d{7})[-\s]?[A-HJ-NP-TV-Z](?![\w])", re.I),
    "IBAN": re.compile(r"\b[A-Z]{2}\d{2}(?:[\s-]?[A-Z0-9]{4}){4,7}\b"),
    "tarjeta": re.compile(r"(?<!\d)(?:\d{4}[\s-]?){3}\d{4}(?!\d)"),
    "correo": re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+"),
    "credencial": re.compile(r"(?:sk-[A-Za-z0-9_-]{16,}|ghp_[A-Za-z0-9]{20,}|AKIA[A-Z0-9]{16}|xox[bp]-[A-Za-z0-9-]{10,}"
                             r"|-----BEGIN [A-Z ]*PRIVATE KEY-----)"),
}


def hashes_en_linea(html):
    """Hashes CSP de los scripts en línea, y errores si hay scripts con src."""
    hashes, errores = [], []
    for atributos, cuerpo in RE_SCRIPT.findall(html):
        if "src=" in atributos:
            errores.append(f"script con src= en index.html: {atributos.strip()} (usar imports desde vendor/)")
            continue
        digest = base64.b64encode(hashlib.sha256(cuerpo.encode("utf-8")).digest()).decode()
        hashes.append(f"'sha256-{digest}'")
    return hashes, errores


def actualizar_csp(ruta=HTML):
    html = ruta.read_text(encoding="utf-8")
    m = RE_CSP.search(html)
    if not m:
        sys.exit("No se encuentra la CSP en index.html")
    directivas = [d.strip() for d in m.group(2).split(";")]
    nuevos, _ = hashes_en_linea(html)
    for i, d in enumerate(directivas):
        if d.startswith("script-src"):
            fuentes = [f for f in d.split()[1:] if not f.startswith("'sha256-")]
            directivas[i] = " ".join(["script-src"] + fuentes + nuevos)
    html = html[: m.start(2)] + "; ".join(directivas) + html[m.end(2):]
    ruta.write_text(html, encoding="utf-8")
    print("CSP actualizada:", " ".join(nuevos))


def verificar_pagina(html, raiz=RAIZ):
    errores = []
    m = RE_CSP.search(html)
    if not m:
        return ["index.html no tiene CSP"]
    csp = {d.split()[0]: d.split()[1:] for d in m.group(2).split(";") if d.strip()}

    script_src = csp.get("script-src", [])
    declarados = {f for f in script_src if f.startswith("'sha256-")}
    reales, errores_src = hashes_en_linea(html)
    errores += errores_src
    for h in sorted(set(reales) - declarados):
        errores.append(f"script en línea sin autorizar en la CSP: {h} (ejecutar con --actualizar-csp)")
    for h in sorted(declarados - set(reales)):
        errores.append(f"hash en la CSP que no corresponde a ningún script: {h}")
    for f in script_src:
        if f in ("'unsafe-inline'", "'unsafe-eval'") or f.startswith(("http:", "https:")) or f == "*":
            errores.append(f"script-src no debe permitir {f}: las librerías se sirven desde vendor/")
    if csp.get("default-src") != ["'none'"]:
        errores.append("la CSP debe empezar por default-src 'none'")

    # Huellas SRI de las librerías propias.
    mapa = re.search(r'<script type="importmap">(.*?)</script>', html, re.S)
    integridad = json.loads(mapa.group(1)).get("integrity", {}) if mapa else {}
    importados = set(re.findall(r"""import(?:\s+\w+\s+from\s*|\s*\(\s*)['"]([^'"]+)['"]""", html))
    for ruta in importados:
        if ruta not in integridad:
            errores.append(f"{ruta} se importa sin huella SRI en el importmap")
    for ruta, esperado in integridad.items():
        fichero = raiz / ruta
        if not fichero.is_file():
            errores.append(f"el importmap cita {ruta}, que no existe")
            continue
        real = "sha384-" + base64.b64encode(hashlib.sha384(fichero.read_bytes()).digest()).decode()
        if real != esperado:
            errores.append(f"{ruta} no coincide con su huella SRI (esperada {esperado}, real {real})")

    # La burbuja no debe pasar datos al bot ni apuntar a otro servidor.
    burbuja = re.search(r"Typebot\.initBubble\(\{(.*?)\n  \}\);", html, re.S)
    if burbuja:
        for clave in ("prefilledVariables", "apiHost", "wsHost", "sessionId", "resultId"):
            if re.search(rf"\b{clave}\s*:", burbuja.group(1)):
                errores.append(f"initBubble no debe definir {clave}")
    return errores


def textos(nodo):
    """Recorre el JSON y devuelve todas las cadenas, para buscar enlaces, teléfonos y datos."""
    if isinstance(nodo, dict):
        for v in nodo.values():
            yield from textos(v)
    elif isinstance(nodo, list):
        for v in nodo:
            yield from textos(v)
    elif isinstance(nodo, str):
        yield nodo


def verificar_flujo(bot):
    errores = []
    bot = bot.get("typebot", bot)

    for g in bot.get("groups", []):
        for b in g.get("blocks", []):
            if b.get("type") not in BLOQUES_PERMITIDOS:
                errores.append(f"bloque no permitido «{b.get('type')}» en el grupo «{g.get('title')}»"
                               " (IA, texto libre, webhooks o scripts necesitan revisión de seguridad)")
            if b.get("type") == "choice input":
                opciones = b.get("options") or {}
                if opciones.get("isMultipleChoice") or opciones.get("isSearchable"):
                    errores.append(f"botones con búsqueda o selección múltiple en «{g.get('title')}»:"
                                   " admiten texto escrito por el usuario")
                if any(i.get("displayCondition") or i.get("value") for i in b.get("items", [])):
                    errores.append(f"botones con condiciones o valores en «{g.get('title')}»")

    if bot.get("variables"):
        errores.append("el flujo define variables: podría guardar datos del usuario o recibirlos de fuera")

    general = bot.get("settings", {}).get("general", {})
    if general.get("rememberUser", {}).get("isEnabled"):
        errores.append("rememberUser está activado: la sesión quedaría guardada en el navegador")
    if general.get("isInputPrefillEnabled"):
        errores.append("isInputPrefillEnabled está activado: la URL podría precargar respuestas")
    if general.get("isHideQueryParamsEnabled") is False:
        errores.append("isHideQueryParamsEnabled está desactivado: los parámetros de la URL quedarían a la vista")

    origenes = set(bot.get("settings", {}).get("security", {}).get("allowedOrigins") or [])
    if not origenes:
        errores.append("allowedOrigins está vacío: cualquier web podría incrustar el bot")
    elif origenes - ORIGENES_PERMITIDOS:
        errores.append(f"allowedOrigins incluye dominios no previstos: {sorted(origenes - ORIGENES_PERMITIDOS)}")

    contenido = {"groups": bot.get("groups"), "events": bot.get("events")}
    for texto in textos(contenido):
        for url in RE_URL.findall(texto):
            p = urlparse(url)
            if p.scheme == "tel":
                continue
            if p.scheme != "https" or p.hostname not in DOMINIOS_PERMITIDOS:
                errores.append(f"enlace no permitido en el flujo: {url}")
        for m in RE_TELEFONO.finditer(texto):
            numero = "".join(m.groups())
            if numero not in TELEFONOS_PERMITIDOS:
                errores.append(f"teléfono no permitido en el flujo: {m.group(0)}")
        sin_urls = RE_URL.sub(" ", texto)
        for tipo, patron in DATOS_PERSONALES.items():
            for m in patron.finditer(sin_urls):
                errores.append(f"posible dato personal o secreto ({tipo}) en el flujo: {m.group(0)}")
    return errores


def main():
    if "--actualizar-csp" in sys.argv:
        actualizar_csp()
    errores = verificar_pagina(HTML.read_text(encoding="utf-8"))
    if FLUJO.is_file():
        errores += verificar_flujo(json.loads(FLUJO.read_text(encoding="utf-8")))
    else:
        errores.append(f"falta {FLUJO.relative_to(RAIZ)}: exporte el flujo desde Typebot")
    if errores:
        print("Verificación fallida:")
        for e in errores:
            print("  -", e)
        sys.exit(1)
    print("Todo correcto: CSP, huellas SRI y flujo de Typebot.")


if __name__ == "__main__":
    main()
