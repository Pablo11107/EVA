#!/usr/bin/env python3
"""Envía por correo el informe mensual de EVA y sus estadísticas.

    python3 scripts/enviar-informe.py                    # el mes anterior
    python3 scripts/enviar-informe.py --mes 2026-11
    python3 scripts/enviar-informe.py --mes 2026-11 --guardar prueba.eml   # sin enviar

Usa el mismo buzón de salida que el editor de Typebot (SMTP_* del .env) y envía a las direcciones
de EVA_INFORME_PARA, separadas por comas. Si EVA_INFORME_PARA está vacío, no envía nada.

Adjunta tres archivos:
  - informes/AAAA-MM.html: el informe, para leerlo en el navegador o guardarlo como PDF.
  - estadisticas/AAAA-MM.json y el del mes anterior: solo recuentos. Con ellos, quien mantiene
    el contenido regenera el informe en su ordenador con sus propuestas y su seguimiento, sin
    necesitar acceso a este servidor:
        python3 servidor-propio/scripts/informe-mensual.py --mes AAAA-MM --estadisticas <carpeta>

Nada de lo adjunto es un dato personal: no hay identificadores, ni horas exactas, ni recorridos
individuales. La contraseña del buzón nunca viaja sin cifrar: si el servidor de correo no ofrece
TLS, el script se niega a autenticarse.
"""
import argparse
import datetime as dt
import json
import os
import re
import smtplib
import ssl
import sys
from email.message import EmailMessage
from email.utils import formatdate, make_msgid, parseaddr
from pathlib import Path

PAQUETE = Path(__file__).resolve().parents[1]
DIR_ESTADISTICAS = PAQUETE / "estadisticas"
DIR_INFORMES = PAQUETE / "informes"
MESES = ["enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto",
         "septiembre", "octubre", "noviembre", "diciembre"]
RE_MES = re.compile(r"^\d{4}-(0[1-9]|1[0-2])$")
RE_CORREO = re.compile(r"^[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}$")


def leer_env(ruta=PAQUETE / ".env"):
    """Lee el .env (CLAVE=valor, comillas opcionales). Las variables de entorno mandan."""
    conf = {}
    if ruta.exists():
        for linea in ruta.read_text(encoding="utf-8").splitlines():
            linea = linea.strip()
            if not linea or linea.startswith("#") or "=" not in linea:
                continue
            clave, valor = linea.split("=", 1)
            valor = valor.strip()
            if len(valor) >= 2 and valor[0] == valor[-1] and valor[0] in "'\"":
                valor = valor[1:-1]
            conf[clave.strip()] = valor
    for clave in list(conf) + [k for k in os.environ if k.startswith(("SMTP_", "EVA_INFORME_"))]:
        if clave in os.environ:
            conf[clave] = os.environ[clave]
    return conf


def destinatarios(texto):
    lista = [d.strip() for d in (texto or "").split(",") if d.strip()]
    malas = [d for d in lista if not RE_CORREO.match(d)]
    if malas:
        raise ValueError(f"direcciones no válidas en EVA_INFORME_PARA: {', '.join(malas)}")
    return lista


def mes_previo(mes):
    anio, num = map(int, mes.split("-"))
    return f"{anio - 1}-12" if num == 1 else f"{anio}-{num - 1:02d}"


def nombre_mes(mes):
    anio, num = map(int, mes.split("-"))
    return f"{MESES[num - 1]} de {anio}"


def componer(mes, para, remitente, dir_est=DIR_ESTADISTICAS, dir_inf=DIR_INFORMES):
    informe = dir_inf / f"{mes}.html"
    estad = dir_est / f"{mes}.json"
    for ruta in (informe, estad):
        if not ruta.exists():
            raise FileNotFoundError(f"falta {ruta}: ejecutar antes estadisticas-mes.py e informe-mensual.py")
    d = json.loads(estad.read_text(encoding="utf-8"))
    conv, res = d["conversaciones"], d["resolucion"]
    pct = (lambda a: round(100 * a / conv) if conv else 0)
    previo = dir_est / f"{mes_previo(mes)}.json"

    m = EmailMessage()
    m["Subject"] = f"EVA · informe de {nombre_mes(mes)}" + (" (datos simulados)" if d.get("simulado") else "")
    m["From"] = remitente
    m["To"] = ", ".join(para)
    m["Date"] = formatdate(localtime=True)
    m["Message-ID"] = make_msgid(domain=parseaddr(remitente)[1].split("@")[-1] or "localhost")
    m.set_content(f"""Informe mensual de EVA, {nombre_mes(mes)}.
{"ATENCIÓN: las estadísticas de este mes están marcadas como simuladas. No son datos reales." + chr(10) if d.get("simulado") else ""}
En resumen: {f"{conv:,}".replace(",", ".")} conversaciones; {pct(res["respuesta"])} % llegaron a una respuesta sin pedir ayuda, {pct(res["persona"])} % pidieron hablar con una persona y {pct(d["fuera_de_horario"])} % llegaron fuera del horario telefónico.

Adjuntos:
  - {informe.name}: el informe. Se abre con cualquier navegador; para el PDF, Imprimir > Guardar como PDF.
  - {estad.name}{" y " + previo.name if previo.exists() else ""}: las estadísticas del mes, solo recuentos, para regenerar el informe.

Para añadir propuestas y seguimiento antes de enviarlo a la empresa:
  1. Guardar los .json en una carpeta, por ejemplo ~/EVA-informes/.
  2. Escribir ahí {mes}.notas.md con las secciones «## Propuestas» y «## Seguimiento».
  3. Desde el repositorio de EVA:
     python3 servidor-propio/scripts/informe-mensual.py --mes {mes} --estadisticas ~/EVA-informes --salida ~/EVA-informes/{mes}.html
  4. Abrir el HTML y guardarlo como PDF.

Correo automático del servidor de EVA. No contiene datos personales.
""")
    adjuntos = [(informe, "text", "html"), (estad, "application", "json")]
    if previo.exists():
        adjuntos.append((previo, "application", "json"))
    for ruta, tipo, subtipo in adjuntos:
        m.add_attachment(ruta.read_bytes(), maintype=tipo, subtype=subtipo, filename=ruta.name)
    return m


def enviar(m, conf):
    host = conf.get("SMTP_HOST")
    if not host:
        raise RuntimeError("falta SMTP_HOST en el .env")
    puerto = int(conf.get("SMTP_PORT") or 587)
    usuario, clave = conf.get("SMTP_USERNAME"), conf.get("SMTP_PASSWORD")
    contexto = ssl.create_default_context()
    if (conf.get("SMTP_SECURE") or "").lower() == "true":
        servidor = smtplib.SMTP_SSL(host, puerto, context=contexto, timeout=30)
    else:
        servidor = smtplib.SMTP(host, puerto, timeout=30)
        servidor.ehlo()
        if servidor.has_extn("starttls"):
            servidor.starttls(context=contexto)
            servidor.ehlo()
        elif clave:
            servidor.quit()
            raise RuntimeError(f"{host} no ofrece TLS: no se envía la contraseña del buzón sin cifrar")
    with servidor:
        if usuario and clave:
            servidor.login(usuario, clave)
        servidor.send_message(m)


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    hoy = dt.date.today().replace(day=1) - dt.timedelta(days=1)
    p.add_argument("--mes", default=hoy.strftime("%Y-%m"))
    p.add_argument("--para", help="direcciones, separadas por comas (por defecto, EVA_INFORME_PARA)")
    p.add_argument("--guardar", type=Path, help="escribir el correo en un .eml en lugar de enviarlo")
    p.add_argument("--estadisticas", type=Path, default=DIR_ESTADISTICAS)
    p.add_argument("--informes", type=Path, default=DIR_INFORMES)
    a = p.parse_args(argv)
    if not RE_MES.match(a.mes):
        p.error("--mes debe tener el formato AAAA-MM")

    conf = leer_env()
    try:
        para = destinatarios(a.para if a.para is not None else conf.get("EVA_INFORME_PARA"))
    except ValueError as error:
        sys.exit(str(error))
    if not para and not a.guardar:
        print("EVA_INFORME_PARA está vacío: el informe queda en el servidor y no se envía.")
        return
    remitente = conf.get("EVA_INFORME_DE") or conf.get("NEXT_PUBLIC_SMTP_FROM") or conf.get("SMTP_USERNAME") or "eva@localhost"
    try:
        m = componer(a.mes, para or ["sin-destinatario@localhost"], remitente, a.estadisticas, a.informes)
    except FileNotFoundError as error:
        sys.exit(str(error))
    if a.guardar:
        a.guardar.write_bytes(bytes(m))
        print(f"Correo guardado en {a.guardar} (no enviado)")
        return
    try:
        enviar(m, conf)
    except (OSError, smtplib.SMTPException, RuntimeError) as error:
        sys.exit(f"No se pudo enviar el informe de {a.mes}: {error}")
    print(f"Informe de {nombre_mes(a.mes)} enviado a {', '.join(para)}")


if __name__ == "__main__":
    main()
