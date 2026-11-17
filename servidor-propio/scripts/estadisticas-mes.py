#!/usr/bin/env python3
"""Estadísticas mensuales de EVA, para el informe que se entrega a la empresa.

    python3 scripts/estadisticas-mes.py                  # el mes anterior
    python3 scripts/estadisticas-mes.py --mes 2026-11

Lee de la base de datos de Typebot las conversaciones del mes y escribe
estadisticas/AAAA-MM.json. Después, scripts/informe-mensual.py convierte ese
archivo en el informe.

Por qué hace falta. Typebot guarda cada conversación: la fecha, los botones
pulsados y el recorrido por las pantallas. Pero scripts/purgar-resultados.sh
la borra a los 90 días, porque ese es el plazo de conservación. Sin este
script, la empresa no tendría con qué comparar un mes con otro. Aquí se
cuentan las conversaciones del mes antes de que se borren, y se guardan solo
los recuentos.

Qué se guarda y qué no. Solo números: cuántas conversaciones, cuántas
llegaron a una respuesta, cuántas pasaron por cada pantalla y cuántas veces
se pulsó cada botón, y el reparto por hora del día y por día de la semana.
No se guarda ningún identificador, ni la hora exacta de ninguna conversación,
ni ningún recorrido individual. No son datos personales, así que pueden
conservarse sin plazo.

Programar el día 1 de cada mes, después de la copia y antes de la purga, para
que todas las conversaciones del mes anterior sigan en la base de datos:
  30 3 1 * * eva cd /opt/eva && python3 scripts/estadisticas-mes.py && python3 scripts/informe-mensual.py

Para pruebas y para el informe de ejemplo, --filas lee las conversaciones de
un archivo (una por línea, el mismo formato que devuelve la consulta) en lugar
de la base de datos.
"""
import argparse
import datetime as dt
import json
import os
import re
import statistics
import subprocess
import sys
from collections import Counter
from pathlib import Path

PAQUETE = Path(__file__).resolve().parents[1]
DIR_ESTADISTICAS = PAQUETE / "estadisticas"
FLUJO_PREPARADO = PAQUETE / "flujo" / "eva-chatbot.servidor-propio.json"
VERSION = 1
ZONA = "Atlantic/Canary"

# El horario de atención telefónica que da el propio flujo: «de lunes a viernes, de 8:00 a 20:00».
# Los festivos no se descuentan.
HORARIO_DIAS = range(0, 5)
HORARIO_DESDE, HORARIO_HASTA = 8, 20

# Pantallas con un papel especial, por su título en el flujo.
MENU_PRINCIPAL = "Menú principal"
FIN = "Despedida"
PERSONA = "Hablar con una persona"
PREFIJO_LLAMADA = "Llamar a "
PREFIJO_FORMULARIO = "Formulario: "

RE_MES = re.compile(r"^\d{4}-(0[1-9]|1[0-2])$")
RE_PUBLIC_ID = re.compile(r"^[a-z0-9][a-z0-9-]{0,62}$")

# Dos consultas, cada fila de salida es un objeto JSON en una línea. Los valores van como variables
# de psql (:'publico', :'desde'…), nunca pegados al texto: psql los entrecomilla. Las fechas de
# Typebot se guardan en UTC; los límites del mes se calculan en hora de Canarias.
SQL = r"""
\set ON_ERROR_STOP on
SELECT json_build_object('flujo', json_build_object('groups', p.groups, 'edges', p.edges))
  FROM "PublicTypebot" p JOIN "Typebot" t ON t.id = p."typebotId"
 WHERE t."publicId" = :'publico';
SELECT json_build_object('conversacion', json_build_object(
         'hora', to_char(r."createdAt" AT TIME ZONE 'UTC' AT TIME ZONE :'zona', 'YYYY-MM-DD"T"HH24:MI'),
         'empezada', coalesce(r."hasStarted", false),
         'completada', r."isCompleted",
         'recorrido', coalesce((SELECT json_agg(v."edgeId" ORDER BY v."index")
                                  FROM "VisitedEdge" v WHERE v."resultId" = r.id), '[]'::json)))
  FROM "Result" r JOIN "Typebot" t ON t.id = r."typebotId"
 WHERE t."publicId" = :'publico'
   AND r."createdAt" >= (:'desde'::timestamp AT TIME ZONE :'zona') AT TIME ZONE 'UTC'
   AND r."createdAt" <  (:'hasta'::timestamp AT TIME ZONE :'zona') AT TIME ZONE 'UTC';
"""


# ── El flujo: qué es cada pantalla y adónde lleva cada flecha ────────────────────────────────

def clasificar(*flujos):
    """Devuelve {aristas, tipos} a partir de uno o varios flujos.

    aristas: id de flecha -> {a: pantalla destino, desde: pantalla del botón, boton: texto}
    tipos:   título de pantalla -> menu | respuesta | formulario | persona | llamada | fin | otro

    Con varios flujos (el publicado y versiones anteriores), manda el primero: así se reconocen
    también las flechas de conversaciones que empezaron antes de un cambio de contenido.
    """
    aristas, tipos = {}, {}
    for flujo in reversed(flujos):
        bot = flujo.get("typebot", flujo)
        grupos = {g["id"]: g for g in bot.get("groups", [])}
        botones = {}
        for g in grupos.values():
            for b in g.get("blocks", []):
                if b.get("type") == "choice input":
                    for it in b.get("items", []):
                        botones[it.get("id")] = (it.get("content") or "", g["title"])
        for e in bot.get("edges", []):
            destino = grupos.get((e.get("to") or {}).get("groupId"))
            if not destino:
                continue
            boton, desde = botones.get((e.get("from") or {}).get("itemId"), (None, None))
            aristas[e["id"]] = {"a": destino["title"], "desde": desde, "boton": boton}
        for g in grupos.values():
            tipos[g["title"]] = _tipo(g)
    return {"aristas": aristas, "tipos": tipos}


def _tipo(grupo):
    titulo = grupo["title"]
    textos = {it.get("content") for b in grupo.get("blocks", []) if b.get("type") == "choice input"
              for it in b.get("items", [])}
    if titulo == FIN:
        return "fin"
    if titulo == PERSONA:
        return "persona"
    if titulo.startswith(PREFIJO_LLAMADA):
        return "llamada"
    if titulo.startswith(PREFIJO_FORMULARIO):
        return "formulario"
    if "Finalizar" in textos:          # las respuestas terminan ofreciendo «Finalizar»
        return "respuesta"
    if textos:
        return "menu"
    return "otro"                      # la bienvenida


# ── Las cuentas del mes ───────────────────────────────────────────────────────────────────────

def en_horario(momento):
    return momento.weekday() in HORARIO_DIAS and HORARIO_DESDE <= momento.hour < HORARIO_HASTA


def agregar(filas, clasif, mes, simulado=False):
    """Convierte las conversaciones del mes en recuentos. Cada conversación cuenta una sola vez en
    cada apartado, aunque pase varias veces por la misma pantalla o pulse el mismo botón."""
    aristas, tipos = clasif["aristas"], clasif["tipos"]
    anio, num = map(int, mes.split("-"))
    dias_mes = ((dt.date(anio + num // 12, num % 12 + 1, 1)) - dt.date(anio, num, 1)).days

    aperturas = conversaciones = completadas = fuera = incompletos = 0
    resolucion = Counter()
    visitas, ultima, abandonos = Counter(), Counter(), Counter()
    botones = {}
    llamadas = Counter()
    por_hora, por_dia_semana, por_dia = [0] * 24, [0] * 7, [0] * dias_mes
    pasos = []

    for fila in filas:
        momento = dt.datetime.strptime(fila["hora"], "%Y-%m-%dT%H:%M")
        if momento.strftime("%Y-%m") != mes:
            continue
        aperturas += 1
        if not fila.get("empezada"):
            continue
        conversaciones += 1
        completadas += bool(fila.get("completada"))
        por_hora[momento.hour] += 1
        por_dia_semana[momento.weekday()] += 1
        por_dia[momento.day - 1] += 1
        fuera += not en_horario(momento)

        vistas, pulsados, ruta, clics, desconocida = set(), set(), [], 0, False
        for eid in fila.get("recorrido") or []:
            a = aristas.get(eid)
            if not a:
                desconocida = True
                continue
            vistas.add(a["a"])
            ruta.append(a["a"])
            if a["boton"] is not None:
                clics += 1
                pulsados.add((a["desde"], a["boton"]))
        incompletos += desconocida
        pasos.append(clics)
        visitas.update(vistas)
        for desde, boton in pulsados:
            botones.setdefault(desde, Counter())[boton] += 1

        tipos_vistos = {tipos.get(t) for t in vistas}
        llamadas.update(t for t in vistas if tipos.get(t) == "llamada")
        if "persona" in tipos_vistos:
            categoria = "persona"
        elif "llamada" in tipos_vistos:
            categoria = "llamada"
        elif tipos_vistos & {"respuesta", "formulario"}:
            categoria = "respuesta"
        else:
            categoria = "sin_respuesta"
        resolucion[categoria] += 1

        if ruta and not fila.get("completada"):
            ultima[ruta[-1]] += 1
            if categoria == "sin_respuesta":
                abandonos[ruta[-1]] += 1

    return {
        "version": VERSION,
        "mes": mes,
        "simulado": bool(simulado),
        "horario": f"lunes a viernes, {HORARIO_DESDE}:00–{HORARIO_HASTA}:00",
        "aperturas": aperturas,
        "conversaciones": conversaciones,
        "completadas": completadas,
        "fuera_de_horario": fuera,
        "recorridos_incompletos": incompletos,
        "resolucion": {k: resolucion.get(k, 0) for k in ("respuesta", "llamada", "persona", "sin_respuesta")},
        "llamadas": dict(sorted(llamadas.items())),
        "por_hora": por_hora,
        "por_dia_semana": por_dia_semana,
        "por_dia": por_dia,
        "pasos": {"mediana": statistics.median(pasos) if pasos else 0,
                  "p90": sorted(pasos)[int(len(pasos) * 0.9)] if pasos else 0},
        "visitas": dict(sorted(visitas.items())),
        "botones": {m: dict(sorted(c.items())) for m, c in sorted(botones.items())},
        "ultima_pantalla": dict(sorted(ultima.items())),
        "abandonos_sin_respuesta": dict(sorted(abandonos.items())),
        "pantallas": dict(sorted(tipos.items())),
    }


# ── Lectura de la base de datos ───────────────────────────────────────────────────────────────

def limites(mes):
    anio, num = map(int, mes.split("-"))
    desde = dt.date(anio, num, 1)
    hasta = dt.date(anio + num // 12, num % 12 + 1, 1)
    return desde.isoformat(), hasta.isoformat()


def orden_psql(mes, public_id):
    if not RE_MES.match(mes):
        raise ValueError(f"mes no válido: {mes!r} (formato AAAA-MM)")
    if not RE_PUBLIC_ID.match(public_id):
        raise ValueError(f"identificador público no válido: {public_id!r}")
    desde, hasta = limites(mes)
    return ["docker", "compose", "exec", "-T", "typebot-db",
            "psql", "-U", "postgres", "-d", "typebot", "-X", "-q", "-t", "-A",
            "-v", f"publico={public_id}", "-v", f"desde={desde}", "-v", f"hasta={hasta}",
            "-v", f"zona={ZONA}"]


def leer_bd(mes, public_id):
    salida = subprocess.run(orden_psql(mes, public_id), input=SQL, text=True, capture_output=True,
                            cwd=PAQUETE, check=False)
    if salida.returncode != 0:
        sys.exit(f"psql falló:\n{salida.stderr.strip()}")
    flujo, filas = None, []
    for linea in salida.stdout.splitlines():
        if not linea.strip():
            continue
        dato = json.loads(linea)
        if "flujo" in dato:
            flujo = dato["flujo"]
        else:
            filas.append(dato["conversacion"])
    return flujo, filas


def public_id_configurado():
    if os.environ.get("EVA_PUBLIC_ID"):
        return os.environ["EVA_PUBLIC_ID"]
    env = PAQUETE / ".env"
    if env.exists():
        for linea in env.read_text(encoding="utf-8").splitlines():
            if linea.startswith("EVA_PUBLIC_ID="):
                return linea.split("=", 1)[1].strip().strip("'\"")
    return "eva"


def mes_anterior(hoy=None):
    hoy = hoy or dt.date.today()
    ultimo = hoy.replace(day=1) - dt.timedelta(days=1)
    return ultimo.strftime("%Y-%m")


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    p.add_argument("--mes", default=mes_anterior(), help="AAAA-MM; por defecto, el mes anterior")
    p.add_argument("--bot", default=None, help="identificador público (EVA_PUBLIC_ID del .env)")
    p.add_argument("--filas", type=Path, help="leer las conversaciones de un archivo, no de la base de datos")
    p.add_argument("--flujo", type=Path, action="append", default=[],
                   help="flujo para reconocer las pantallas (se puede repetir); por defecto, el publicado")
    p.add_argument("--simulado", action="store_true", help="marca los datos como simulados (informe de ejemplo)")
    p.add_argument("--salida", type=Path, default=DIR_ESTADISTICAS)
    a = p.parse_args(argv)
    if not RE_MES.match(a.mes):
        p.error("--mes debe tener el formato AAAA-MM")

    flujos = [json.loads(f.read_text(encoding="utf-8")) for f in a.flujo]
    if a.filas:
        filas = [json.loads(l) for l in a.filas.read_text(encoding="utf-8").splitlines() if l.strip()]
    else:
        publicado, filas = leer_bd(a.mes, a.bot or public_id_configurado())
        if publicado:
            flujos.insert(0, publicado)
    if FLUJO_PREPARADO.exists():
        flujos.append(json.loads(FLUJO_PREPARADO.read_text(encoding="utf-8")))
    if not flujos:
        sys.exit("No hay flujo con el que reconocer las pantallas")

    datos = agregar(filas, clasificar(*flujos), a.mes, simulado=a.simulado)
    a.salida.mkdir(parents=True, exist_ok=True)
    destino = a.salida / f"{a.mes}.json"
    destino.write_text(json.dumps(datos, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(f"{a.mes}: {datos['conversaciones']} conversaciones ({datos['aperturas']} aperturas) -> {destino}")
    if datos["recorridos_incompletos"]:
        print(f"  aviso: {datos['recorridos_incompletos']} conversaciones pasan por flechas que no están en "
              "ningún flujo conocido; añadir la versión anterior con --flujo", file=sys.stderr)


if __name__ == "__main__":
    main()
