"""Pruebas de las estadísticas mensuales y del informe. Se ejecutan en CI, sin base de datos.

    python3 -m unittest discover -s servidor-propio/pruebas -v

La consulta SQL se probó contra PostgreSQL (límites del mes en hora de Canarias con cambio de
hora, orden del recorrido, otro bot en la misma base de datos); aquí se comprueba que no se
degrade: variables de psql en lugar de texto pegado, y validación del mes y del identificador.
"""
import datetime as dt
import importlib.util
import json
import re
import unittest
from pathlib import Path

PAQUETE = Path(__file__).resolve().parents[1]
RAIZ = PAQUETE.parent
FLUJO = json.loads((PAQUETE / "flujo" / "eva-chatbot.servidor-propio.json").read_text(encoding="utf-8"))


def cargar(ruta, nombre):
    spec = importlib.util.spec_from_file_location(nombre, ruta)
    modulo = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(modulo)
    return modulo


est = cargar(PAQUETE / "scripts" / "estadisticas-mes.py", "estadisticas_mes")
inf = cargar(PAQUETE / "scripts" / "informe-mensual.py", "informe_mensual")
sim = cargar(PAQUETE / "pruebas" / "simular-mes.py", "simular_mes")
CLASIF = est.clasificar(FLUJO)


def camino(*botones):
    """Recorrido (ids de flecha) que pulsa estos botones, en orden, desde el saludo."""
    bot = FLUJO
    grupos = {g["id"]: g for g in bot["groups"]}
    aristas = {e["id"]: e for e in bot["edges"]}
    eid = bot["events"][0]["outgoingEdgeId"]
    recorrido = [eid]
    pendientes = list(botones)
    while True:
        grupo = grupos[aristas[eid]["to"]["groupId"]]
        menu = next((b for b in grupo["blocks"] if b["type"] == "choice input"), None)
        if menu is None:
            siguiente = next((b.get("outgoingEdgeId") for b in grupo["blocks"] if b.get("outgoingEdgeId")), None)
            if not siguiente:
                return recorrido
            eid = siguiente
        elif pendientes:
            texto = pendientes.pop(0)
            item = next((i for i in menu["items"] if i.get("content") == texto), None)
            if item is None:
                raise AssertionError(f"«{texto}» no está en «{grupo['title']}»")
            eid = item["outgoingEdgeId"]
        else:
            return recorrido
        recorrido.append(eid)


def conversacion(hora, *botones, completada=None):
    rec = camino(*botones)
    fin = CLASIF["aristas"][rec[-1]]["a"] == est.FIN
    return {"hora": hora, "empezada": bool(botones), "completada": fin if completada is None else completada,
            "recorrido": rec}


class Clasificacion(unittest.TestCase):
    def test_cada_pantalla_tiene_tipo(self):
        tipos = CLASIF["tipos"]
        self.assertEqual(len(tipos), len(FLUJO["groups"]))
        self.assertEqual([t for t, v in tipos.items() if v == "otro"], ["Bienvenida"])
        self.assertEqual(tipos["Despedida"], "fin")
        self.assertEqual(tipos["Hablar con una persona"], "persona")
        self.assertEqual(sorted(t for t, v in tipos.items() if v == "llamada"),
                         ["Llamar a atención al cliente", "Llamar a averías"])
        for menu in ("Menú principal", "Menú de trámites", "Menú de incidencias", "Grupo: contrato"):
            self.assertEqual(tipos[menu], "menu", menu)

    def test_todos_los_tramites_son_respuestas(self):
        con_documentacion = [g["title"] for g in FLUJO["groups"]
                             if "Documentación a aportar" in json.dumps(g, ensure_ascii=False)]
        self.assertGreater(len(con_documentacion), 40)
        for t in con_documentacion:
            self.assertEqual(CLASIF["tipos"][t], "respuesta", t)

    def test_cada_formulario_tiene_su_tramite(self):
        for t, tipo in CLASIF["tipos"].items():
            if tipo == "formulario":
                self.assertEqual(CLASIF["tipos"].get(t[len("Formulario: "):]), "respuesta", t)

    def test_todas_las_flechas_se_reconocen(self):
        self.assertEqual(len(CLASIF["aristas"]), len(FLUJO["edges"]))


class Cuentas(unittest.TestCase):
    def setUp(self):
        self.filas = [
            # lunes 10:15: baja de suministro, abre el formulario y se despide
            conversacion("2026-11-02T10:15", "Trámites", "Contrato", "Baja de suministro", "No",
                         "Rellenar formulario", "Finalizar"),
            # sábado: no tiene agua y pulsa llamar a averías
            conversacion("2026-11-07T11:00", "Incidencia o avería", "No tengo agua", "Llamar a averías (928 010 334)"),
            # viernes 20:00 (ya fuera de horario): no encuentra su caso y pide una persona
            conversacion("2026-11-06T20:00", "Trámites", "No encuentro mi caso"),
            # lunes 7:59: entra en contrato y se va
            conversacion("2026-11-09T07:59", "Trámites", "Contrato"),
            # abre y no pulsa nada
            conversacion("2026-11-10T12:00"),
            # otro mes: no cuenta
            conversacion("2026-10-31T23:59", "Contacto"),
        ]
        self.d = est.agregar(self.filas, CLASIF, "2026-11")

    def test_totales(self):
        d = self.d
        self.assertEqual((d["aperturas"], d["conversaciones"], d["completadas"]), (5, 4, 1))
        self.assertEqual(d["resolucion"], {"respuesta": 1, "llamada": 1, "persona": 1, "sin_respuesta": 1})
        self.assertEqual(sum(d["resolucion"].values()), d["conversaciones"])

    def test_horario(self):
        self.assertEqual(self.d["fuera_de_horario"], 3)  # sábado, viernes 20:00 y lunes 7:59
        self.assertTrue(est.en_horario(dt.datetime(2026, 11, 6, 19, 59)))
        self.assertFalse(est.en_horario(dt.datetime(2026, 11, 6, 20, 0)))
        self.assertFalse(est.en_horario(dt.datetime(2026, 11, 9, 7, 59)))
        self.assertTrue(est.en_horario(dt.datetime(2026, 11, 9, 8, 0)))
        self.assertFalse(est.en_horario(dt.datetime(2026, 11, 8, 12, 0)))

    def test_botones_y_pantallas(self):
        d = self.d
        self.assertEqual(d["botones"]["Menú principal"], {"Incidencia o avería": 1, "Trámites": 3})
        self.assertEqual(d["botones"]["Menú de trámites"]["No encuentro mi caso"], 1)
        self.assertEqual(d["visitas"]["Formulario: Baja de suministro"], 1)
        self.assertEqual(d["llamadas"], {"Llamar a averías": 1})
        self.assertEqual(d["abandonos_sin_respuesta"], {"Grupo: contrato": 1})
        self.assertEqual(d["por_dia_semana"][5], 1)  # sábado
        self.assertEqual(len(d["por_dia"]), 30)

    def test_una_conversacion_cuenta_una_vez(self):
        ida_y_vuelta = conversacion("2026-11-03T09:00", "Trámites", "Contrato", "Volver", "Contrato", "Volver",
                                    "Contrato", "Alta de suministro")
        d = est.agregar([ida_y_vuelta], CLASIF, "2026-11")
        self.assertEqual(d["visitas"]["Grupo: contrato"], 1)
        self.assertEqual(d["botones"]["Grupo: contrato"]["Volver"], 1)

    def test_flechas_desconocidas_no_rompen_nada(self):
        fila = conversacion("2026-11-03T09:00", "Trámites")
        fila["recorrido"].append("flecha-de-una-version-anterior")
        d = est.agregar([fila], CLASIF, "2026-11")
        self.assertEqual(d["recorridos_incompletos"], 1)
        self.assertEqual(d["conversaciones"], 1)

    def test_solo_recuentos(self):
        """Ni identificadores, ni horas exactas, ni recorridos: nada que señale a una persona."""
        texto = json.dumps(self.d, ensure_ascii=False)
        self.assertNotRegex(texto, r"\bc[a-z0-9]{24}\b")              # ids de Typebot (cuid)
        self.assertNotRegex(texto, r"\d{4}-\d\d-\d\dT\d\d")           # marcas de tiempo
        self.assertEqual(set(self.d), {
            "version", "mes", "simulado", "horario", "aperturas", "conversaciones", "completadas",
            "fuera_de_horario", "recorridos_incompletos", "resolucion", "llamadas", "por_hora",
            "por_dia_semana", "por_dia", "pasos", "visitas", "botones", "ultima_pantalla",
            "abandonos_sin_respuesta", "pantallas"})


class Consulta(unittest.TestCase):
    def test_valores_como_variables_de_psql(self):
        self.assertIn(":'publico'", est.SQL)
        self.assertIn(":'desde'", est.SQL)
        self.assertNotRegex(est.SQL, r"\{\w+\}")       # nada de f-strings ni format
        self.assertIn("ON_ERROR_STOP", est.SQL)

    def test_entradas_validadas(self):
        orden = est.orden_psql("2026-11", "eva")
        self.assertIn("publico=eva", orden)
        self.assertIn("desde=2026-11-01", orden)
        self.assertIn("hasta=2026-12-01", orden)
        self.assertIn("hasta=2027-01-01", est.orden_psql("2026-12", "eva"))
        for mes, bot in (("2026-13", "eva"), ("2026-1", "eva"), ("2026-11", "eva'; DROP TABLE \"Result\"; --"),
                         ("2026-11", "EVA"), ("2026-11", "")):
            with self.assertRaises(ValueError):
                est.orden_psql(mes, bot)

    def test_mes_anterior(self):
        self.assertEqual(est.mes_anterior(dt.date(2026, 12, 1)), "2026-11")
        self.assertEqual(est.mes_anterior(dt.date(2027, 1, 1)), "2026-12")


class Informe(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.nov = est.agregar(sim.simular(FLUJO, "2026-11", 900, 7), CLASIF, "2026-11", simulado=True)
        cls.oct = est.agregar(sim.simular(FLUJO, "2026-10", 700, 3), CLASIF, "2026-10", simulado=True)

    def test_seis_apartados(self):
        html = inf.informe(self.nov, self.oct)
        for rotulo in ("01 · Uso", "02 · Resolución", "03 · Qué consultan", "04 · Dónde se atasca",
                       "05 · Qué proponemos", "06 · Seguimiento"):
            self.assertIn(rotulo, html)
        self.assertIn("Octubre de 2026", html)

    def test_aviso_de_simulado(self):
        self.assertIn("DATOS SIMULADOS", inf.informe(self.nov))
        real = dict(self.nov, simulado=False)
        self.assertNotIn("SIMULADOS", inf.informe(real))

    def test_autonomo(self):
        """Nada se carga de fuera: ni fuentes, ni scripts, ni imágenes."""
        html = inf.informe(self.nov, self.oct)
        self.assertNotRegex(html, r"(src|href)=\"?https?:")
        self.assertNotIn("<script", html)
        self.assertNotIn("@import", html)

    def test_escapa_textos_del_flujo(self):
        """Los títulos de pantalla y los botones salen del flujo: se escapan siempre."""
        d = json.loads(json.dumps(self.nov))
        d["pantallas"]["<img src=x onerror=alert(1)>"] = "respuesta"
        d["visitas"]["<img src=x onerror=alert(1)>"] = 50
        d["botones"]["<img src=x onerror=alert(1)>"] = {"No es mi caso": 20}
        d["botones"]["Menú principal"]["<script>alert(1)</script>"] = 5
        html = inf.informe(d, notas={"propuestas": ["- <b>nota</b>"]})
        self.assertNotIn("<img src=x", html)
        self.assertNotIn("<script>alert", html)
        self.assertNotIn("<b>nota</b>", html)
        self.assertIn("&lt;img src=x", html)

    def test_primer_mes(self):
        self.assertIn("primer mes con datos", inf.informe(self.nov))

    def test_mes_vacio(self):
        vacio = est.agregar([], CLASIF, "2026-11")
        html = inf.informe(vacio)
        self.assertIn("Sin datos este mes", html)

    def test_propuestas_con_dato(self):
        for _, titulo, dato, esfuerzo in inf.propuestas(self.nov):
            self.assertRegex(dato, r"\d")
            self.assertTrue(esfuerzo)

    def test_notas(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            ruta = Path(tmp) / "2026-11.notas.md"
            ruta.write_text("## Propuestas\n- Una\nTexto\n## Seguimiento\n- Dos\n", encoding="utf-8")
            notas = inf.leer_notas(ruta)
        self.assertEqual(notas, {"propuestas": ["- Una", "Texto"], "seguimiento": ["- Dos"]})


env = cargar(PAQUETE / "scripts" / "enviar-informe.py", "enviar_informe")


class Envio(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import tempfile
        cls.tmp = tempfile.TemporaryDirectory()
        cls.dir = Path(cls.tmp.name)
        for mes, n, semilla in (("2026-10", 300, 3), ("2026-11", 400, 7)):
            d = est.agregar(sim.simular(FLUJO, mes, n, semilla), CLASIF, mes)
            (cls.dir / f"{mes}.json").write_text(json.dumps(d), encoding="utf-8")
        (cls.dir / "2026-11.html").write_text(inf.informe(d), encoding="utf-8")

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def correo(self):
        return env.componer("2026-11", ["a@emalsa.es", "b@example.com"], "EVA <eva@emalsa.es>", self.dir, self.dir)

    def test_adjuntos_con_el_nombre_que_espera_el_informe(self):
        nombres = [p.get_filename() for p in self.correo().iter_attachments()]
        self.assertEqual(nombres, ["2026-11.html", "2026-11.json", "2026-10.json"])

    def test_cabeceras_y_texto(self):
        m = self.correo()
        self.assertEqual(m["To"], "a@emalsa.es, b@example.com")
        self.assertIn("noviembre de 2026", m["Subject"])
        self.assertNotIn("simulad", m["Subject"])
        cuerpo = m.get_body(("plain",)).get_content()
        self.assertIn("informe-mensual.py --mes 2026-11", cuerpo)
        self.assertRegex(cuerpo, r"\d+ conversaciones")

    def test_adjuntos_sin_datos_personales(self):
        for parte in self.correo().iter_attachments():
            if parte.get_filename().endswith(".json"):
                texto = parte.get_payload(decode=True).decode()
                self.assertNotRegex(texto, r"\bc[a-z0-9]{24}\b")
                self.assertNotRegex(texto, r"\d{4}-\d\d-\d\dT\d\d")

    def test_destinatarios_validados(self):
        self.assertEqual(env.destinatarios(" a@emalsa.es , b@example.com,"), ["a@emalsa.es", "b@example.com"])
        self.assertEqual(env.destinatarios(""), [])
        for malo in ("sinarroba.com", "a@b.com\nBcc: x@y.com", "a@emalsa.es, <x>"):
            with self.assertRaises(ValueError):
                env.destinatarios(malo)

    def test_falta_el_informe(self):
        with self.assertRaises(FileNotFoundError):
            env.componer("2026-09", ["a@emalsa.es"], "eva@emalsa.es", self.dir, self.dir)

    def _smtp_falso(self, con_tls):
        from unittest import mock
        servidor = mock.MagicMock()
        servidor.has_extn.side_effect = lambda e: con_tls and e == "starttls"
        servidor.__enter__.return_value = servidor
        return servidor

    def test_starttls_antes_de_la_contrasena(self):
        from unittest import mock
        servidor = self._smtp_falso(con_tls=True)
        conf = {"SMTP_HOST": "smtp.emalsa.es", "SMTP_PORT": "587", "SMTP_USERNAME": "eva@emalsa.es",
                "SMTP_PASSWORD": "x"}
        with mock.patch.object(env.smtplib, "SMTP", return_value=servidor):
            env.enviar(self.correo(), conf)
        llamadas = [c[0] for c in servidor.method_calls]
        self.assertLess(llamadas.index("starttls"), llamadas.index("login"))
        self.assertIn("send_message", llamadas)

    def test_sin_tls_no_manda_la_contrasena(self):
        from unittest import mock
        servidor = self._smtp_falso(con_tls=False)
        conf = {"SMTP_HOST": "smtp.emalsa.es", "SMTP_USERNAME": "eva@emalsa.es", "SMTP_PASSWORD": "x"}
        with mock.patch.object(env.smtplib, "SMTP", return_value=servidor):
            with self.assertRaises(RuntimeError):
                env.enviar(self.correo(), conf)
        self.assertNotIn("login", [c[0] for c in servidor.method_calls])
        self.assertNotIn("send_message", [c[0] for c in servidor.method_calls])

    def test_tls_directo(self):
        from unittest import mock
        servidor = self._smtp_falso(con_tls=False)
        conf = {"SMTP_HOST": "smtp.emalsa.es", "SMTP_PORT": "465", "SMTP_SECURE": "true",
                "SMTP_USERNAME": "eva@emalsa.es", "SMTP_PASSWORD": "x"}
        with mock.patch.object(env.smtplib, "SMTP_SSL", return_value=servidor) as ssl_:
            env.enviar(self.correo(), conf)
        ssl_.assert_called_once()
        self.assertIn("login", [c[0] for c in servidor.method_calls])

    def test_sin_destinatarios_no_envia(self):
        from unittest import mock
        import io, contextlib
        salida = io.StringIO()
        with mock.patch.object(env, "leer_env", return_value={"EVA_INFORME_PARA": ""}), \
                mock.patch.object(env.smtplib, "SMTP") as smtp, contextlib.redirect_stdout(salida):
            env.main(["--mes", "2026-11", "--estadisticas", str(self.dir), "--informes", str(self.dir)])
        smtp.assert_not_called()
        self.assertIn("no se envía", salida.getvalue())

    @unittest.skipUnless((RAIZ / ".git").exists(), "solo en el repositorio; el paquete entregado lleva la dirección")
    def test_direccion_no_publicada(self):
        """La dirección provisional se entrega aparte: en el repositorio, EVA_INFORME_PARA va vacío."""
        self.assertRegex((PAQUETE / ".env.ejemplo").read_text(encoding="utf-8"), r"(?m)^EVA_INFORME_PARA=$")


class Simulador(unittest.TestCase):
    def test_reproducible_y_dentro_del_mes(self):
        a = list(sim.simular(FLUJO, "2026-02", 200, 5))
        b = list(sim.simular(FLUJO, "2026-02", 200, 5))
        self.assertEqual(a, b)
        self.assertTrue(all(f["hora"].startswith("2026-02-") for f in a))
        d = est.agregar(a, CLASIF, "2026-02")
        self.assertEqual(d["aperturas"], 200)
        self.assertEqual(d["recorridos_incompletos"], 0)


class Operacion(unittest.TestCase):
    def test_programado_antes_de_la_purga(self):
        readme = (PAQUETE / "README.md").read_text(encoding="utf-8")
        m = re.search(r"^\s*(\d+) (\d+) 1 \* \* eva .*estadisticas-mes\.py.*informe-mensual\.py.*enviar-informe\.py",
                      readme, re.M)
        self.assertIsNotNone(m, "falta la tarea mensual en el README")
        purga = re.search(r"^\s*(\d+) (\d+) \* \* \* eva .*purgar-resultados\.sh", readme, re.M)
        self.assertLess((int(m.group(2)), int(m.group(1))), (int(purga.group(2)), int(purga.group(1))))

    @unittest.skipUnless((RAIZ / ".git").exists(), "solo en el repositorio")
    def test_datos_fuera_del_repositorio(self):
        ignorado = (RAIZ / ".gitignore").read_text(encoding="utf-8")
        self.assertIn("servidor-propio/estadisticas/", ignorado)
        self.assertIn("servidor-propio/informes/", ignorado)


if __name__ == "__main__":
    unittest.main()
