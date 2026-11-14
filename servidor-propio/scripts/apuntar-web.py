#!/usr/bin/env python3
"""Apunta la página index.html al visor de la empresa en lugar de a la nube de
Typebot, y recalcula los hashes de la CSP.

    python3 servidor-propio/scripts/apuntar-web.py --visor https://asistente.emalsa.es --bot eva
    python3 servidor-propio/scripts/apuntar-web.py --nube      # vuelve a typebot.io

Solo hay que ejecutarlo cuando el servidor de EMALSA esté en marcha y el bot
publicado en él: hasta entonces, la página de demostración sigue usando la
nube. Cambia tres cosas en index.html:

  - Typebot.initBubble: el identificador del bot y apiHost (el visor).
  - CSP: connect-src e img-src pasan de typebot.io al visor.
  - Los hashes de la CSP, con scripts/verificar.py --actualizar-csp.

Después hay que pasar el verificador y las pruebas, revisar el diff y hacer
commit, como con cualquier otro cambio.
"""
import argparse
import re
import subprocess
import sys
from pathlib import Path
from urllib.parse import urlparse

RAIZ = Path(__file__).resolve().parents[2]
HTML = RAIZ / "index.html"
BOT_NUBE = "eva-asistente-virtual-de-emalsa-oi2fy0m"
FUENTES_NUBE = "https://typebot.io https://*.typebot.io"


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--visor", help="URL del visor de la empresa, p. ej. https://asistente.emalsa.es")
    p.add_argument("--bot", default="eva", help="identificador público del bot en ese visor")
    p.add_argument("--nube", action="store_true", help="volver a la nube de Typebot")
    a = p.parse_args()
    if bool(a.visor) == a.nube:
        p.error("indique --visor URL o --nube")

    html = HTML.read_text(encoding="utf-8")
    if a.nube:
        bot, visor, fuentes = BOT_NUBE, None, FUENTES_NUBE
    else:
        u = urlparse(a.visor)
        if u.scheme != "https" or not u.hostname or u.path not in ("", "/"):
            sys.exit("--visor debe ser https://host sin ruta")
        bot, visor, fuentes = a.bot, f"https://{u.hostname}", f"https://{u.hostname}"

    # Burbuja: identificador y apiHost.
    nuevo, n = re.subn(r'(Typebot\.initBubble\(\{\n    typebot: ")[^"]*(",)(?:\n    apiHost: "[^"]*",)?',
                       lambda m: m.group(1) + bot + m.group(2) + (f'\n    apiHost: "{visor}",' if visor else ""),
                       html, count=1)
    if n != 1:
        sys.exit("no encuentro Typebot.initBubble en index.html")

    # CSP: a quién puede conectar la página y de dónde carga imágenes.
    nuevo, n2 = re.subn(r"connect-src [^;]*;", f"connect-src {fuentes};", nuevo, count=1)
    nuevo, n3 = re.subn(r"img-src 'self' data: blob: [^;]*;", f"img-src 'self' data: blob: {fuentes};", nuevo, count=1)
    if n2 != 1 or n3 != 1:
        sys.exit("no encuentro connect-src o img-src en la CSP de index.html")

    HTML.write_text(nuevo, encoding="utf-8")
    subprocess.run([sys.executable, str(RAIZ / "scripts" / "verificar.py"), "--actualizar-csp"], check=True)
    print(f"index.html apunta a {visor or 'la nube de Typebot'} (bot «{bot}»). Ahora: "
          "python3 scripts/verificar.py && python3 -m unittest discover -s tests")


if __name__ == "__main__":
    main()
