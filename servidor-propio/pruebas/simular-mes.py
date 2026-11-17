#!/usr/bin/env python3
"""Simula un mes de conversaciones con EVA, para las pruebas y el informe de ejemplo.

    python3 pruebas/simular-mes.py --mes 2026-11 --aperturas 1400 --semilla 7 > filas.jsonl

Recorre el flujo real pulsando botones al azar, con más peso en los temas habituales de una
empresa de aguas, y escribe una conversación por línea en el mismo formato que devuelve la
consulta de scripts/estadisticas-mes.py. Los datos son INVENTADOS: sirven para ver el formato del
informe y para probar las cuentas, nunca para sacar conclusiones. El informe hecho con ellos lleva
en cada página el aviso de que son simulados.
"""
import argparse
import calendar
import json
import random
import sys
from pathlib import Path

PAQUETE = Path(__file__).resolve().parents[1]
FLUJO = PAQUETE / "flujo" / "eva-chatbot.servidor-propio.json"

# Peso de cada botón cuando aparece; el resto pesa 1. Inventado, para que el ejemplo se parezca a
# un mes plausible (más altas y cambios de titular que autorizaciones de vertido).
PESOS = {
    "Trámites": 9, "Incidencia o avería": 5, "Contacto": 2.5, "Hablar con alguien": 1.2,
    "Contrato": 6, "Pagos y recibos": 3, "Contador": 2.5, "Alcantarillado": 0.6,
    "Alta de suministro": 5, "Cambio de titular": 5, "Baja de suministro": 2, "Datos de contacto": 1,
    "No tengo agua": 4, "Falta de presión": 2, "Comunicar avería": 2.5, "El agua sale turbia": 1,
    "Atasco alcantarilla": 1, "Daños a terceros": 0.4, "Agua por obras": 0.6, "Otra incidencia": 0.8,
    "Vivienda": 4, "Local comercial": 1.2, "Propietario": 3, "Inquilino": 2.5,
    "Rellenar formulario": 5, "Finalizar": 3.5, "Otra gestión": 1, "Menú principal": 0.6,
    "No es mi caso": 0.5, "No encuentro mi caso": 0.6, "Volver": 0.35, "Más contacto": 0.6,
}
# Probabilidad de cerrar la ventana en cada pantalla, según su tipo.
CIERRE = {"menu": 0.07, "respuesta": 0.30, "formulario": 0.45, "persona": 0.35, "llamada": 0.4, "otro": 0.0}
# Reparto horario (0–23 h) y semanal (lunes–domingo), también inventado.
HORAS = [1, 0.5, 0.3, 0.2, 0.2, 0.4, 1, 2.5, 5, 7, 8, 8, 7.5, 6, 5, 5, 5.5, 6, 6.5, 6.5, 6, 5, 3.5, 2]
DIAS = [1.15, 1.1, 1.05, 1.0, 0.95, 0.55, 0.45]


def cargar(nombre):
    import importlib.util
    spec = importlib.util.spec_from_file_location(nombre, PAQUETE / "scripts" / f"{nombre}.py")
    modulo = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(modulo)
    return modulo


def simular(flujo, mes, aperturas, semilla, sin_clic=0.14):
    tipo_de = cargar("estadisticas-mes")._tipo
    azar = random.Random(semilla)
    bot = flujo.get("typebot", flujo)
    grupos = {g["id"]: g for g in bot["groups"]}
    aristas = {e["id"]: e for e in bot["edges"]}
    inicio = bot["events"][0]["outgoingEdgeId"]
    anio, num = map(int, mes.split("-"))
    dias = [d for d in range(1, calendar.monthrange(anio, num)[1] + 1)]
    peso_dia = [DIAS[calendar.weekday(anio, num, d)] for d in dias]

    for _ in range(aperturas):
        dia = azar.choices(dias, peso_dia)[0]
        hora = azar.choices(range(24), HORAS)[0]
        fila = {"hora": f"{mes}-{dia:02d}T{hora:02d}:{azar.randrange(60):02d}",
                "empezada": False, "completada": False, "recorrido": []}
        eid = inicio
        for _paso in range(40):
            fila["recorrido"].append(eid)
            grupo = grupos[aristas[eid]["to"]["groupId"]]
            menu = next((b for b in grupo["blocks"] if b["type"] == "choice input"), None)
            if menu is None:
                siguiente = next((b.get("outgoingEdgeId") for b in grupo["blocks"] if b.get("outgoingEdgeId")), None)
                if siguiente is None:              # la despedida: fin de la conversación
                    fila["completada"] = fila["empezada"]
                    break
                eid = siguiente
                continue
            if not fila["empezada"] and azar.random() < sin_clic:
                break                              # abre EVA, lee el saludo y se va
            if fila["empezada"] and azar.random() < CIERRE.get(tipo_de(grupo), 0.1):
                break
            items = [it for it in menu["items"] if it.get("outgoingEdgeId")]
            elegido = azar.choices(items, [PESOS.get(it.get("content"), 1) for it in items])[0]
            fila["empezada"] = True
            eid = elegido["outgoingEdgeId"]
        yield fila


def main():
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    p.add_argument("--mes", required=True)
    p.add_argument("--aperturas", type=int, default=1400)
    p.add_argument("--semilla", type=int, default=1)
    a = p.parse_args()
    flujo = json.loads(FLUJO.read_text(encoding="utf-8"))
    for fila in simular(flujo, a.mes, a.aperturas, a.semilla):
        sys.stdout.write(json.dumps(fila, ensure_ascii=False) + "\n")


if __name__ == "__main__":
    main()
