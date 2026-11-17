#!/usr/bin/env python3
"""Informe mensual de EVA para la empresa, a partir de las estadísticas del mes.

    python3 scripts/informe-mensual.py                   # el mes anterior
    python3 scripts/informe-mensual.py --mes 2026-11

Lee estadisticas/AAAA-MM.json (lo escribe scripts/estadisticas-mes.py) y, si existe, el del mes
anterior para comparar. Escribe informes/AAAA-MM.html: un archivo autónomo, sin nada que se
cargue de fuera, que se abre en cualquier navegador y se guarda como PDF con «Imprimir».

Los seis apartados son los que promete la presentación de EVA: uso, resolución, qué consultan,
dónde se atasca la gente, qué proponemos cambiar y seguimiento del mes anterior. Las propuestas
automáticas salen de reglas fijas (están abajo, en CRITERIOS) y cada una lleva el dato que la
justifica. Quien mantiene el contenido añade las suyas, y el seguimiento de lo acordado, en
estadisticas/AAAA-MM.notas.md:

    ## Propuestas
    - Cambiar el botón «Contador» por «Contador y lecturas».
    ## Seguimiento
    - En octubre se reescribió «Baja de suministro»: los «No es mi caso» bajaron a la mitad.

Si las estadísticas son simuladas, cada página lo dice.
"""
import argparse
import datetime as dt
import html
import json
import re
import sys
from pathlib import Path

PAQUETE = Path(__file__).resolve().parents[1]
DIR_ESTADISTICAS = PAQUETE / "estadisticas"
DIR_INFORMES = PAQUETE / "informes"

MESES = ["enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto",
         "septiembre", "octubre", "noviembre", "diciembre"]
DIAS = ["Lunes", "Martes", "Miércoles", "Jueves", "Viernes", "Sábado", "Domingo"]
NAVEGACION = {"Volver", "Menú principal", "Finalizar", "Otra gestión", "Otra incidencia",
              "Más contacto", "Hablar con alguien", "No es mi caso", "No encuentro mi caso"}
NO_ES_MI_CASO = ("No es mi caso", "No encuentro mi caso")

# Reglas de las propuestas automáticas. Por debajo de MIN_VISITAS no se saca ninguna conclusión.
CRITERIOS = {
    "MIN_VISITAS": 20,
    "MIN_CASOS": 5,             # y al menos 5 casos: con 2 o 3 no hay patrón
    "NO_ES_MI_CASO": 0.10,      # respuestas: «No es mi caso» en el 10 % de las visitas o más
    "ABANDONO_MENU": 0.12,      # menús: el 12 % o más se va de ahí sin haber visto ninguna respuesta
    "NO_ENCUENTRO": 0.02,       # «No encuentro mi caso» en el 2 % de las conversaciones o más
    "PERSONA_DIRECTA": 0.05,    # «Hablar con alguien» desde el menú principal, 5 % o más
    "FUERA_DE_HORARIO": 0.30,   # consultas fuera del horario telefónico, 30 % o más
}


# ── Formato ───────────────────────────────────────────────────────────────────────────────────

def e(texto):
    return html.escape(str(texto), quote=True)


def n(x):
    if isinstance(x, float) and not x.is_integer():
        return f"{x:.1f}".replace(".", ",")
    return f"{int(x):,}".replace(",", ".")


def puntos(x):
    return f"{x} punto" if x == 1 else f"{x} puntos"


def pct(a, b):
    return round(100 * a / b) if b else 0


def nombre_mes(mes):
    anio, num = map(int, mes.split("-"))
    return f"{MESES[num - 1]} de {anio}"


def mes_previo(mes):
    anio, num = map(int, mes.split("-"))
    return f"{anio - 1}-12" if num == 1 else f"{anio}-{num - 1:02d}"


def cambio(actual, anterior, unidad="%"):
    """Texto del cambio respecto al mes anterior: en % para recuentos, en puntos para porcentajes."""
    if anterior is None:
        return ""
    if unidad == "pp":
        d = actual - anterior
        if d == 0:
            return '<span class="igual">igual que el mes anterior</span>'
        return f'<span class="{"sube" if d > 0 else "baja"}">{"+" if d > 0 else "−"}{puntos(abs(d))}</span>'
    if not anterior:
        return ""
    d = round(100 * (actual - anterior) / anterior)
    if d == 0:
        return '<span class="igual">igual que el mes anterior</span>'
    return f'<span class="{"sube" if d > 0 else "baja"}">{"+" if d > 0 else "−"}{abs(d)} % respecto al mes anterior</span>'


def barras(filas, total=None, clase=""):
    """filas: [(etiqueta, valor, detalle)] -> barras horizontales en HTML."""
    if not filas:
        return '<p class="vacio">Sin datos este mes.</p>'
    tope = max(v for _, v, _ in filas) or 1
    out = [f'<div class="barras {clase}">']
    for etiqueta, valor, detalle in filas:
        ancho = max(1.5, 100 * valor / tope)
        extra = f' <small class="det">{detalle}</small>' if detalle else ""
        porc = f' <span class="por">{pct(valor, total)} %</span>' if total else ""
        out.append(f'<div class="fila"><span class="et">{e(etiqueta)}{extra}</span>'
                   f'<span class="pista"><span class="b" style="width:{ancho:.1f}%"></span></span>'
                   f'<span class="val">{n(valor)}{porc}</span></div>')
    out.append("</div>")
    return "".join(out)


def grafica_horas(por_hora, desde, hasta):
    alto, ancho, sep = 120, 22, 4
    tope = max(por_hora) or 1
    x0 = desde * (ancho + sep) - sep / 2
    x1 = hasta * (ancho + sep) - sep / 2
    partes = [f'<svg viewBox="0 -14 {24 * (ancho + sep)} {alto + 34}" class="horas" role="img" '
              f'aria-label="Conversaciones por hora del día">',
              f'<rect x="{x0}" y="-14" width="{x1 - x0}" height="{alto + 14}" class="franja"/>',
              f'<text x="{(x0 + x1) / 2}" y="-3" class="franja-t">horario telefónico</text>']
    for h, v in enumerate(por_hora):
        a = alto * v / tope
        x = h * (ancho + sep)
        clase = "dentro" if desde <= h < hasta else "fuera"
        partes.append(f'<rect x="{x}" y="{alto - a:.1f}" width="{ancho}" height="{a:.1f}" rx="3" class="{clase}"/>')
        if h % 3 == 0:
            partes.append(f'<text x="{x + ancho / 2}" y="{alto + 16}" class="eje">{h:02d}h</text>')
    partes.append("</svg>")
    return "".join(partes)


def barra_apilada(segmentos, total):
    out = ['<div class="apilada">']
    for etiqueta, valor, clase in segmentos:
        if valor:
            out.append(f'<span class="{clase}" style="width:{100 * valor / total:.2f}%" '
                       f'title="{e(etiqueta)}">{f"{pct(valor, total)} %" if valor / total >= 0.06 else ""}</span>')
    out.append("</div><ul class=\"leyenda\">")
    for etiqueta, valor, clase in segmentos:
        out.append(f'<li><span class="pt {clase}"></span>{e(etiqueta)} · <b>{n(valor)}</b> ({pct(valor, total)} %)</li>')
    out.append("</ul>")
    return "".join(out)


def pantalla(titulo):
    """«Grupo: contrato» es un nombre interno del flujo; en el informe, «Trámites › contrato»."""
    if titulo.startswith("Grupo: "):
        return "Trámites › " + titulo.split(": ", 1)[1]
    return titulo


def tabla(cabecera, filas, clase=""):
    if not filas:
        return '<p class="vacio">Nada que destacar este mes.</p>'
    th = "".join(f"<th>{c}</th>" for c in cabecera)
    tr = "".join("<tr>" + "".join(f"<td>{c}</td>" for c in fila) + "</tr>" for fila in filas)
    return f'<table class="{clase}"><thead><tr>{th}</tr></thead><tbody>{tr}</tbody></table>'


def leer_notas(ruta):
    """Notas del mantenedor: secciones «## Propuestas» y «## Seguimiento», con párrafos y guiones."""
    secciones = {}
    if not ruta or not ruta.exists():
        return secciones
    actual = None
    for linea in ruta.read_text(encoding="utf-8").splitlines():
        m = re.match(r"^##\s+(.+?)\s*$", linea)
        if m:
            actual = m.group(1).strip().lower()
            secciones.setdefault(actual, [])
        elif actual and linea.strip():
            secciones[actual].append(linea.strip())
    return secciones


def html_notas(lineas):
    if not lineas:
        return ""
    out, lista = [], []
    for l in lineas + [""]:
        if l.startswith("- "):
            lista.append(f"<li>{e(l[2:])}</li>")
            continue
        if lista:
            out.append("<ul>" + "".join(lista) + "</ul>")
            lista = []
        if l:
            out.append(f"<p>{e(l)}</p>")
    return '<div class="notas"><p class="rotulo-notas">Del equipo de contenido</p>' + "".join(out) + "</div>"


# ── Lo que dicen los datos ────────────────────────────────────────────────────────────────────

def temas(d):
    """Los botones de segundo nivel: qué trámite, qué incidencia o qué forma de contacto."""
    cuenta = {}
    for menu, botones in d["botones"].items():
        if menu.startswith("Grupo: "):
            area = "Trámites · " + menu.split(": ", 1)[1]
        elif menu == "Menú de incidencias":
            area = "Incidencias"
        elif menu == "Menú de contacto":
            area = "Contacto"
        else:
            continue
        for boton, v in botones.items():
            if boton not in NAVEGACION:
                cuenta[(boton, area)] = cuenta.get((boton, area), 0) + v
    return sorted(cuenta.items(), key=lambda kv: (-kv[1], kv[0][0]))


def respuestas(d):
    tipos, visitas = d["pantallas"], d["visitas"]
    filas = []
    for t, tipo in tipos.items():
        if tipo != "respuesta":
            continue
        v = visitas.get(t, 0)
        form = visitas.get("Formulario: " + t) if ("Formulario: " + t) in tipos else None
        no_caso = sum(d["botones"].get(t, {}).get(b, 0) for b in NO_ES_MI_CASO)
        filas.append({"titulo": t, "visitas": v, "formulario": form, "no_es_mi_caso": no_caso})
    return filas


def menus(d):
    filas = []
    for t, tipo in d["pantallas"].items():
        if tipo != "menu" or not d["visitas"].get(t):
            continue
        b = d["botones"].get(t, {})
        filas.append({"titulo": t, "visitas": d["visitas"][t],
                      "abandonos": d["abandonos_sin_respuesta"].get(t, 0),
                      "volver": b.get("Volver", 0), "no_encuentro": b.get("No encuentro mi caso", 0)})
    return filas


def propuestas(d):
    c, conv, out = CRITERIOS, d["conversaciones"], []
    for r in respuestas(d):
        if (r["visitas"] >= c["MIN_VISITAS"] and r["no_es_mi_caso"] >= c["MIN_CASOS"]
                and r["no_es_mi_caso"] / r["visitas"] >= c["NO_ES_MI_CASO"]):
            out.append((r["no_es_mi_caso"],
                        f"Revisar la respuesta «{r['titulo']}»",
                        f"{n(r['no_es_mi_caso'])} de {n(r['visitas'])} conversaciones que la vieron ({pct(r['no_es_mi_caso'], r['visitas'])} %) "
                        "pulsaron «No es mi caso». Puede faltar una variante del trámite o una pregunta previa.",
                        "Bajo: ajustar el texto o añadir una pregunta (1–2 h)."))
    for m in menus(d):
        if (m["visitas"] >= c["MIN_VISITAS"] and m["abandonos"] >= c["MIN_CASOS"]
                and m["abandonos"] / m["visitas"] >= c["ABANDONO_MENU"]):
            out.append((m["abandonos"],
                        f"Revisar las opciones de «{pantalla(m['titulo'])}»",
                        f"{n(m['abandonos'])} de {n(m['visitas'])} conversaciones que llegaron aquí ({pct(m['abandonos'], m['visitas'])} %) "
                        "se cerraron sin ver ninguna respuesta. Los botones pueden no reconocerse.",
                        "Bajo: renombrar o reordenar botones (1 h)."))
    no_enc = d["botones"].get("Menú de trámites", {}).get("No encuentro mi caso", 0)
    if conv and no_enc >= max(10, c["NO_ENCUENTRO"] * conv):
        out.append((no_enc, "Buscar el trámite que falta",
                    f"«No encuentro mi caso» se pulsó en {n(no_enc)} conversaciones en el menú de trámites. "
                    "Conviene preguntar a atención al cliente qué piden quienes llaman tras usar EVA.",
                    "Medio: redactar un trámite nuevo (2–4 h), una vez identificado."))
    directo = d["botones"].get("Menú principal", {}).get("Hablar con alguien", 0)
    if conv and directo / conv >= c["PERSONA_DIRECTA"]:
        out.append((directo, "Ver por qué se pide una persona nada más empezar",
                    f"{n(directo)} conversaciones ({pct(directo, conv)} %) eligieron «Hablar con alguien» en el primer menú, "
                    "sin mirar los temas. Puede que su consulta no esté entre las opciones visibles.",
                    "Bajo: revisar el texto de bienvenida y el menú principal (1 h)."))
    if conv >= 300:
        nadie = [r["titulo"] for r in respuestas(d) if r["visitas"] == 0]
        if nadie:
            muestra = ", ".join(f"«{t}»" for t in nadie[:6]) + (" y otras" if len(nadie) > 6 else "")
            out.append((0, f"Comprobar {n(len(nadie))} respuestas que nadie ha visto",
                        f"Este mes nadie llegó a {n(len(nadie))} de las {n(len(respuestas(d)))} respuestas: {muestra}. "
                        "Puede ser normal (trámites poco frecuentes) "
                        "o que el camino hasta ellas no se entienda.",
                        "Bajo: revisar los botones que llevan a ellas (30 min)."))
    if conv and d["fuera_de_horario"] / conv >= c["FUERA_DE_HORARIO"]:
        out.append((d["fuera_de_horario"], "Dar a conocer EVA donde se informa del horario",
                    f"{pct(d['fuera_de_horario'], conv)} % de las consultas llegan cuando el teléfono está cerrado. "
                    "Mencionar EVA en el mensaje del contestador y en la página de contacto llevaría allí a quien llama fuera de horario.",
                    "Comunicación: no requiere cambios en EVA."))
    out.sort(key=lambda p: -p[0])
    return out[:6]


# ── El informe ────────────────────────────────────────────────────────────────────────────────

def informe(d, anterior=None, notas=None):
    notas = notas or {}
    mes, conv, res = d["mes"], d["conversaciones"], d["resolucion"]
    ant = anterior or {}
    a_conv = ant.get("conversaciones")
    a_res = ant.get("resolucion", {})
    pct_resp = pct(res["respuesta"], conv)
    pct_fuera = pct(d["fuera_de_horario"], conv)
    pct_pers = pct(res["persona"], conv)
    lista_temas = temas(d)
    tema_top = lista_temas[0][0][0] if lista_temas else "—"
    llam_evitadas = res["respuesta"]
    resps = respuestas(d)
    generado = dt.date.today()

    aviso = ('<div class="simulado">EJEMPLO CON DATOS SIMULADOS · no son datos reales de EMALSA</div>'
             if d.get("simulado") else "")

    cifras = [
        (n(conv), "conversaciones", cambio(conv, a_conv)),
        (f"{pct_resp} %", "llegaron a una respuesta sin pedir ayuda",
         cambio(pct_resp, pct(a_res.get("respuesta", 0), a_conv) if a_conv else None, "pp")),
        (f"{pct_fuera} %", "fuera del horario telefónico",
         cambio(pct_fuera, pct(ant.get("fuera_de_horario", 0), a_conv) if a_conv else None, "pp")),
        (n(res["persona"]), "pidieron hablar con una persona",
         cambio(res["persona"], a_res.get("persona")) if a_res else ""),
    ]
    html_cifras = "".join(f'<div class="cifra"><b>{v}</b><span>{t}</span><small>{c}</small></div>'
                          for v, t, c in cifras)

    resumen = (f"En {e(nombre_mes(mes))}, EVA atendió {n(conv)} conversaciones. "
               f"{pct_resp} de cada 100 llegaron a una respuesta sin pedir hablar con nadie, "
               f"{pct_fuera} de cada 100 llegaron con el teléfono cerrado, "
               f"y el tema más consultado fue «{e(tema_top)}».")

    # 01 · Uso
    uso = tabla(["", "Este mes", "Mes anterior"], [
        ["Aperturas de EVA (vio el saludo)", n(d["aperturas"]), n(ant["aperturas"]) if ant else "—"],
        ["Conversaciones (pulsó al menos un botón)", n(conv), n(a_conv) if ant else "—"],
        ["Terminadas con «Finalizar»", f"{n(d['completadas'])} ({pct(d['completadas'], conv)} %)",
         f"{n(ant['completadas'])} ({pct(ant['completadas'], a_conv)} %)" if ant else "—"],
        [f"Fuera del horario telefónico ({e(d['horario'])})", f"{n(d['fuera_de_horario'])} ({pct_fuera} %)",
         f"{n(ant['fuera_de_horario'])} ({pct(ant['fuera_de_horario'], a_conv)} %)" if ant else "—"],
        ["Botones pulsados por conversación (mediana)", n(d["pasos"]["mediana"]),
         n(ant["pasos"]["mediana"]) if ant else "—"],
    ], "datos")
    dias = barras([(DIAS[i], v, "") for i, v in enumerate(d["por_dia_semana"])], total=conv, clase="estrechas")
    desde, hasta = (int(x) for x in re.findall(r"(\d+):00", d["horario"])[:2])

    # 02 · Resolución
    apilada = barra_apilada([
        ("Llegó a una respuesta", res["respuesta"], "s-resp"),
        ("Pulsó llamar (averías u otro teléfono)", res["llamada"], "s-llam"),
        ("Pidió hablar con una persona", res["persona"], "s-pers"),
        ("Se fue sin ver ninguna respuesta", res["sin_respuesta"], "s-sin"),
    ], conv or 1)
    con_form = sorted((r for r in resps if r["formulario"] is not None and r["visitas"]),
                      key=lambda r: -r["visitas"])[:8]
    tabla_form = tabla(["Trámite", "Lo vieron", "Abrieron el formulario"],
                       [[e(r["titulo"]), n(r["visitas"]), f"{n(r['formulario'])} ({pct(r['formulario'], r['visitas'])} %)"]
                        for r in con_form], "datos")
    llamadas = ", ".join(f"{e(k.replace('Llamar a ', ''))}: <b>{n(v)}</b>" for k, v in d["llamadas"].items()) or "ninguna"

    # 03 · Qué consultan
    areas = barras(sorted(((k, v, "") for k, v in d["botones"].get("Menú principal", {}).items()),
                          key=lambda x: -x[1]), total=conv)
    top_temas = barras([(f"{boton}", v, e(area)) for (boton, area), v in lista_temas[:10]], total=conv)
    top_resp = sorted((r for r in resps if r["visitas"]), key=lambda r: -r["visitas"])[:10]
    tabla_resp = tabla(["Respuesta", "Conversaciones"], [[e(r["titulo"]), n(r["visitas"])] for r in top_resp], "datos")
    nadie = [r["titulo"] for r in resps if r["visitas"] == 0]
    html_nadie = (f'<p class="nota">Respuestas que nadie vio este mes ({n(len(nadie))} de {n(len(resps))}): '
                  + ", ".join(e(t) for t in nadie) + ".</p>") if nadie else \
        f'<p class="nota">Todas las respuestas ({n(len(resps))}) se vieron al menos una vez.</p>'

    # 04 · Dónde se atasca
    ms = sorted(menus(d), key=lambda m: (-m["abandonos"], -m["visitas"]))
    tabla_menus = tabla(["Pantalla", "Llegaron", "Se fueron ahí sin respuesta", "«Volver»", "«No encuentro mi caso»"],
                        [[e(pantalla(m["titulo"])), n(m["visitas"]), f"{n(m['abandonos'])} ({pct(m['abandonos'], m['visitas'])} %)",
                          n(m["volver"]) if m["volver"] else "—", n(m["no_encuentro"]) if m["no_encuentro"] else "—"]
                         for m in ms[:8] if m["abandonos"] or m["volver"] or m["no_encuentro"]], "datos")
    no_caso = sorted((r for r in resps if r["no_es_mi_caso"]), key=lambda r: -r["no_es_mi_caso"])[:8]
    tabla_no_caso = tabla(["Respuesta", "La vieron", "«No es mi caso»"],
                          [[e(r["titulo"]), n(r["visitas"]), f"{n(r['no_es_mi_caso'])} ({pct(r['no_es_mi_caso'], r['visitas'])} %)"]
                           for r in no_caso], "datos")

    # 05 · Propuestas
    props = propuestas(d)
    html_props = "".join(
        f'<div class="propuesta"><h4>{e(t)}</h4><p><b>El dato.</b> {e(dato)}</p><p class="esf"><b>Esfuerzo estimado.</b> {e(esf)}</p></div>'
        for _, t, dato, esf in props) or '<p class="vacio">Ningún dato supera los umbrales este mes.</p>'
    html_props += html_notas(notas.get("propuestas", []))

    # 06 · Seguimiento
    if ant:
        def fila(etq, a, b, pp=False):
            dif = (a - b) if pp else None
            txt = ((f"{'+' if dif > 0 else '−'}{puntos(abs(dif))}" if dif else "=") if pp
                   else (f"{'+' if a >= b else '−'}{n(abs(a - b))}"))
            return [etq, f"{a} %" if pp else n(a), f"{b} %" if pp else n(b), txt]
        seguimiento = tabla(["", "Este mes", e(nombre_mes(ant['mes']).capitalize()), "Diferencia"], [
            fila("Conversaciones", conv, a_conv),
            fila("Llegaron a una respuesta", pct_resp, pct(a_res["respuesta"], a_conv), True),
            fila("Pidieron una persona", pct_pers, pct(a_res["persona"], a_conv), True),
            fila("Se fueron sin respuesta", pct(res["sin_respuesta"], conv), pct(a_res["sin_respuesta"], a_conv), True),
            fila("Fuera de horario", pct_fuera, pct(ant["fuera_de_horario"], a_conv), True),
        ], "datos")
    else:
        seguimiento = '<p class="vacio">Es el primer mes con datos: el próximo informe ya podrá comparar.</p>'
    seguimiento += html_notas(notas.get("seguimiento", []))

    criterios = (f"respuestas con «No es mi caso» en el {pct(CRITERIOS['NO_ES_MI_CASO'], 1)} % de las visitas o más; "
                 f"menús de los que se va sin respuesta el {pct(CRITERIOS['ABANDONO_MENU'], 1)} % o más; "
                 f"siempre con un mínimo de {CRITERIOS['MIN_VISITAS']} visitas y {CRITERIOS['MIN_CASOS']} casos")

    return f"""<!doctype html>
<html lang="es"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>EVA · Informe de {e(nombre_mes(mes))}</title>
<style>{CSS}{CSS_SIMULADO if d.get("simulado") else ""}</style></head><body>
{aviso}
<header class="portada"><div class="marca">{GOTA}<div><b>EVA</b><span>Emalsa Virtual Assistant</span></div></div>
<p class="rotulo">Informe mensual</p><h1>{e(nombre_mes(mes).capitalize())}</h1>
<p class="resumen">{resumen}</p>
<div class="cifras">{html_cifras}</div></header>
<main>
<section><div class="cab"><p class="rotulo">01 · Uso del servicio</p><h2>Cuánto se usa y cuándo</h2></div>
{uso}
<h3>Conversaciones por hora del día</h3>{grafica_horas(d["por_hora"], desde, hasta)}
<p class="nota">La franja sombreada es el horario telefónico; los sábados y domingos el teléfono está cerrado todo el día.</p>
<h3>Por día de la semana</h3>{dias}
<p class="nota">Canal: web. WhatsApp no está activado.</p></section>

<section><div class="cab"><p class="rotulo">02 · Resolución</p><h2>Cómo acabaron las conversaciones</h2></div>
{apilada}
<div class="caja"><p><b>Llamadas evitadas, estimación máxima: {n(llam_evitadas)}.</b> Es el número de conversaciones que llegaron a una respuesta sin pedir ayuda ni pulsar llamar. Supone que cada una habría sido una llamada; parte de esas personas habría buscado en la web o no habría llamado, así que la cifra real es menor.</p></div>
<p class="nota">Botones de llamada pulsados: {llamadas}. Con averías es la respuesta correcta: EVA indica llamar.</p>
<h3>Trámites más vistos y cuántos abrieron el formulario</h3>{tabla_form}</section>

<section><div class="cab"><p class="rotulo">03 · Qué consultan sus clientes</p><h2>Temas y respuestas</h2></div>
<h3>Primera elección</h3>{areas}
<h3>Los diez temas más consultados</h3>{top_temas}
<h3>Las diez respuestas más vistas</h3>{tabla_resp}
{html_nadie}</section>

<section><div class="cab"><p class="rotulo">04 · Dónde se atasca la gente</p><h2>Dónde se van sin respuesta</h2></div>
<p>Pantallas de las que la gente se fue sin haber visto ninguna respuesta, y cuántas veces se volvió atrás.</p>
{tabla_menus}
<h3>Respuestas que no encajaban con el caso</h3>{tabla_no_caso}</section>

<section><div class="cab"><p class="rotulo">05 · Qué proponemos cambiar</p><h2>Propuestas</h2></div>
<p class="nota">Las propuestas automáticas salen de reglas fijas: {e(criterios)}. Las demás las añade el equipo de contenido.</p>
{html_props}</section>

<section><div class="cab"><p class="rotulo">06 · Seguimiento</p><h2>Respecto al mes anterior</h2></div>
{seguimiento}</section>

<section class="metodo"><h3>Cómo se calcula</h3><ul>
<li><b>Conversación:</b> alguien abrió EVA y pulsó al menos un botón. Se cuentan conversaciones, no personas: sin cookies ni identificadores, quien vuelve otro día cuenta otra vez.</li>
<li><b>Llegó a una respuesta:</b> vio al menos una respuesta (un trámite, una incidencia o un dato de contacto) y no pasó por «Hablar con una persona» ni pulsó llamar. Las cuatro categorías de la resolución no se solapan.</li>
<li><b>Fuera de horario:</b> fuera de {e(d['horario'])}, en hora de Canarias. No descuenta festivos.</li>
<li><b>Datos:</b> fecha, botones pulsados y pantallas visitadas, que Typebot guarda en el servidor de EMALSA. Las conversaciones se borran a los 90 días; este informe y sus estadísticas solo contienen recuentos, sin identificadores ni horas exactas, y no permiten saber qué hizo ninguna persona concreta.</li>
<li><b>Generado</b> el {generado.day} de {MESES[generado.month - 1]} de {generado.year} a partir de las estadísticas de {e(nombre_mes(mes))}{" (simuladas)" if d.get("simulado") else ""}.</li>
</ul></section>
</main>
<footer>EVA · Informe de {e(nombre_mes(mes))} · generado el {generado.day} de {MESES[generado.month - 1]} de {generado.year}{" · datos simulados" if d.get("simulado") else ""}</footer>
</body></html>
"""


GOTA = ('<svg viewBox="0 0 120 120" aria-hidden="true"><defs><linearGradient id="g" x1="0" y1="0" x2="1" y2="1">'
        '<stop offset="0" stop-color="#2BC8E8"/><stop offset=".55" stop-color="#2A72C4"/><stop offset="1" stop-color="#214881"/>'
        '</linearGradient></defs><path d="M60 10C60 10 24 50 24 74a36 36 0 0 0 72 0C96 50 60 10 60 10Z" fill="url(#g)"/>'
        '<rect x="40" y="58" width="40" height="7" rx="3.5" fill="#fff"/><rect x="34" y="72" width="52" height="7" rx="3.5" fill="#fff"/>'
        '<rect x="44" y="86" width="32" height="7" rx="3.5" fill="#fff"/></svg>')

CSS_SIMULADO = """
@page{@bottom-center{content:"EJEMPLO CON DATOS SIMULADOS · no son datos reales de EMALSA";
 font:700 9px system-ui,sans-serif;letter-spacing:.08em;color:#7A2E0E}}
.simulado{position:sticky}
"""

CSS = """
:root{--azul:#214881;--azul-medio:#2A72C4;--cian:#2BC8E8;--tinta:#0E2238;--cuerpo:#44566B;--gris:#5B6B7F;
 --fondo:#F4F7FB;--borde:#E3E8EF;--noche:#0B1B32;--noche-2:#10294A;--noche-texto:#B9C9DD;
 --ok:#17845A;--aviso:#9A6406;--media:#B5481C}
*{box-sizing:border-box}
body{margin:0;background:#fff;color:var(--cuerpo);font:400 14px/1.55 Outfit,system-ui,-apple-system,"Segoe UI",Roboto,sans-serif;
 -webkit-print-color-adjust:exact;print-color-adjust:exact}
h1,h2,h3,h4{color:var(--tinta);margin:0;line-height:1.2}
.simulado{position:fixed;top:0;left:0;right:0;z-index:5;background:#FBE7DE;color:#7A2E0E;text-align:center;
 font-weight:700;letter-spacing:.08em;font-size:11px;padding:5px;border-bottom:1px solid #F0B9A0}
.portada{background:linear-gradient(160deg,var(--noche),var(--noche-2));color:var(--noche-texto);padding:44px 48px 36px}
.marca{display:flex;align-items:center;gap:12px}.marca svg{width:40px;height:40px}
.marca b{display:block;color:#fff;font-size:20px}.marca span{font-size:12px;letter-spacing:.04em}
.rotulo{font-size:11px;font-weight:600;letter-spacing:.16em;text-transform:uppercase;color:var(--azul-medio);margin:0 0 6px}
.portada .rotulo{color:var(--cian);margin-top:28px}
.portada h1{color:#fff;font-size:40px;font-weight:600;letter-spacing:-.01em}
.resumen{font-size:16px;max-width:46em;margin:12px 0 0}
.cifras{display:grid;grid-template-columns:repeat(4,1fr);gap:1px;margin-top:26px;background:rgba(185,201,221,.2);
 border:1px solid rgba(185,201,221,.2);border-radius:12px;overflow:hidden}
.cifra{background:rgba(11,27,50,.55);padding:14px 16px}
.cifra b{display:block;color:#fff;font-size:28px;font-weight:600}.cifra span{display:block;font-size:12.5px}
.cifra small{display:block;font-size:11.5px;margin-top:4px;color:var(--noche-texto)}
.cifra .sube,.cifra .baja,.cifra .igual{color:#D6E2F0}
main{padding:0 48px}
section{padding:28px 0 8px;border-top:1px solid var(--borde)}
main section:first-child{border-top:0}
h2{font-size:24px;font-weight:600;margin-bottom:14px}
h3{font-size:15px;font-weight:600;margin:20px 0 8px}
h4{font-size:14.5px;font-weight:600;margin-bottom:4px}
table{width:100%;border-collapse:collapse;font-size:13px;border:1px solid var(--borde);border-radius:10px;overflow:hidden}
th{text-align:left;font-size:10.5px;letter-spacing:.1em;text-transform:uppercase;color:var(--gris);background:#FAFBFD;
 padding:8px 10px;border-bottom:1px solid var(--borde)}
td{padding:7px 10px;border-bottom:1px solid var(--borde);vertical-align:top}
tr:last-child td{border-bottom:0}
table.datos td:not(:first-child),table.datos th:not(:first-child){text-align:right;white-space:nowrap}
tr{break-inside:avoid}
table:not(.datos) td:first-child,table.datos td:first-child{width:34%}
.cab{break-inside:avoid;break-after:avoid}
.barras{display:grid;gap:5px}
.fila{display:grid;grid-template-columns:minmax(150px,30%) 1fr 92px;gap:10px;align-items:center;font-size:13px}
.fila .det{font-size:11px;color:var(--gris)}
.et{color:var(--tinta)}
.pista{background:var(--fondo);border-radius:4px;height:12px;overflow:hidden}
.pista .b{display:block;height:100%;background:linear-gradient(90deg,var(--azul),var(--azul-medio));border-radius:4px}
.val{text-align:right;color:var(--tinta);font-variant-numeric:tabular-nums}.por{color:var(--gris);font-size:11.5px}
.estrechas .fila{grid-template-columns:90px 1fr 92px}
svg.horas{width:100%;height:auto;display:block}
svg .dentro{fill:var(--azul-medio)} svg .fuera{fill:var(--cian)} svg .franja{fill:#EEF3FA}
svg .eje{font-size:10px;fill:var(--gris);text-anchor:middle} svg .franja-t{font-size:9.5px;fill:var(--azul-medio);text-anchor:middle}
.apilada{display:flex;height:34px;border-radius:8px;overflow:hidden;margin:4px 0 10px}
.apilada span{display:flex;align-items:center;justify-content:center;color:#fff;font-weight:600;font-size:12px;min-width:0;overflow:hidden}
.s-resp{background:var(--ok)}.s-llam{background:var(--azul-medio)}.s-pers{background:var(--aviso)}.s-sin{background:var(--media)}
.leyenda{list-style:none;padding:0;margin:0 0 12px;display:grid;grid-template-columns:1fr 1fr;gap:4px 18px;font-size:13px}
.pt{display:inline-block;width:10px;height:10px;border-radius:3px;margin-right:7px;vertical-align:middle}
.caja{background:var(--fondo);border:1px solid var(--borde);border-radius:10px;padding:12px 16px;margin:10px 0;break-inside:avoid}
.caja b{color:var(--tinta)}
.nota{font-size:12px;color:var(--gris);margin:8px 0}
.vacio{color:var(--gris);font-style:italic}
.propuesta{border:1px solid var(--borde);border-left:4px solid var(--azul-medio);border-radius:10px;padding:10px 14px;margin:0 0 10px;break-inside:avoid}
.propuesta p{margin:3px 0}.propuesta .esf{font-size:12.5px;color:var(--gris)}
.notas{border:1px dashed var(--azul-medio);border-radius:10px;padding:10px 14px;margin-top:12px;break-inside:avoid}
.rotulo-notas{font-size:11px;font-weight:600;letter-spacing:.12em;text-transform:uppercase;color:var(--azul-medio);margin:0 0 4px}
.notas ul{margin:4px 0;padding-left:18px}
.metodo ul{padding-left:18px;font-size:12.5px}.metodo li{margin-bottom:4px}
footer{padding:16px 48px 28px;font-size:11.5px;color:var(--gris)}
@page{size:A4;margin:14mm 0 16mm;@bottom-right{content:counter(page) " / " counter(pages);font:10px system-ui,sans-serif;color:#5B6B7F;margin-right:14mm}}
@page :first{margin-top:0}
@media print{h2,h3{break-after:avoid} .simulado,footer{display:none}}
@media (max-width:640px){.portada,main{padding-left:16px;padding-right:16px}.cifras{grid-template-columns:1fr 1fr}
 .fila{grid-template-columns:110px 1fr 70px}}
"""


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    hoy = dt.date.today().replace(day=1) - dt.timedelta(days=1)
    p.add_argument("--mes", default=hoy.strftime("%Y-%m"))
    p.add_argument("--estadisticas", type=Path, default=DIR_ESTADISTICAS)
    p.add_argument("--notas", type=Path, help="por defecto, estadisticas/AAAA-MM.notas.md si existe")
    p.add_argument("--salida", type=Path, help="por defecto, informes/AAAA-MM.html")
    a = p.parse_args(argv)
    if not re.match(r"^\d{4}-(0[1-9]|1[0-2])$", a.mes):
        p.error("--mes debe tener el formato AAAA-MM")
    origen = a.estadisticas / f"{a.mes}.json"
    if not origen.exists():
        sys.exit(f"No están las estadísticas de {a.mes}: {origen}. Ejecutar antes scripts/estadisticas-mes.py")
    d = json.loads(origen.read_text(encoding="utf-8"))
    previo = a.estadisticas / f"{mes_previo(a.mes)}.json"
    anterior = json.loads(previo.read_text(encoding="utf-8")) if previo.exists() else None
    notas = leer_notas(a.notas or a.estadisticas / f"{a.mes}.notas.md")
    salida = a.salida or DIR_INFORMES / f"{a.mes}.html"
    salida.parent.mkdir(parents=True, exist_ok=True)
    salida.write_text(informe(d, anterior, notas), encoding="utf-8")
    print(f"Informe de {nombre_mes(a.mes)} -> {salida}")


if __name__ == "__main__":
    main()
