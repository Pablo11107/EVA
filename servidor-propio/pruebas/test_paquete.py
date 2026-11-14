"""Pruebas sin conexión del paquete de servidor propio. Se ejecutan en CI.

    python3 -m unittest discover -s servidor-propio/pruebas -v

Comprueban que el paquete no se degrade con el tiempo: imágenes fijadas por
huella, nada expuesto salvo el proxy, secretos fuera del repositorio, reglas
del proxy coherentes con la burbuja, y que el flujo preparado para la empresa
es exactamente el flujo revisado.
"""
import json
import re
import subprocess
import sys
import unittest
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[2]
PAQUETE = RAIZ / "servidor-propio"
sys.path.insert(0, str(RAIZ / "scripts"))
import verificar  # noqa: E402


def cargar(nombre):
    """Importa un script del paquete por ruta (sus nombres llevan guiones)."""
    import importlib.util
    spec = importlib.util.spec_from_file_location(nombre, PAQUETE / "scripts" / f"{nombre}.py")
    modulo = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(modulo)
    return modulo


preparar_flujo = cargar("preparar-flujo")

COMPOSE = (PAQUETE / "docker-compose.yml").read_text(encoding="utf-8")
ENV = (PAQUETE / ".env.ejemplo").read_text(encoding="utf-8")
CADDY = (PAQUETE / "proxy" / "Caddyfile").read_text(encoding="utf-8")
NGINX = (PAQUETE / "proxy" / "nginx-eva.conf").read_text(encoding="utf-8")
INCRUSTAR = (PAQUETE / "web" / "incrustar-eva.html").read_text(encoding="utf-8")
FLUJO = json.loads((RAIZ / "flujo" / "eva-chatbot.json").read_text(encoding="utf-8"))


class Compose(unittest.TestCase):

    def imagenes(self):
        return re.findall(r"^\s+image:\s*(\S+)", COMPOSE, re.M)

    def test_hay_cinco_servicios(self):
        self.assertEqual(len(self.imagenes()), 5)

    def test_imagenes_fijadas_por_huella(self):
        """«latest» o una etiqueta suelta pueden cambiar sin aviso; la huella no."""
        for imagen in self.imagenes():
            self.assertRegex(imagen, r"@sha256:[0-9a-f]{64}$", imagen)
            self.assertNotIn(":latest", imagen)

    def test_typebot_editor_y_visor_misma_version(self):
        versiones = set(re.findall(r"typebot-(?:builder|viewer):([\d.]+)@", COMPOSE))
        self.assertEqual(len(versiones), 1, versiones)

    def test_solo_el_proxy_publica_puertos(self):
        bloques = re.split(r"\n  (?=[a-z-]+:\n)", COMPOSE)
        con_puertos = [b.split(":")[0].strip() for b in bloques if re.search(r"^\s+ports:", b, re.M)]
        self.assertEqual(con_puertos, ["proxy"])
        self.assertEqual(set(re.findall(r'- "(\d+):\d+(?:/udp)?"', COMPOSE)), {"80", "443"})

    def test_base_de_datos_y_redis_en_red_interna_sin_salida(self):
        self.assertIn("internal: true", COMPOSE)
        for servicio in ("typebot-db", "typebot-redis"):
            bloque = COMPOSE.split(f"\n  {servicio}:")[1].split("\n  typebot-")[0].split("\nnetworks:")[0]
            self.assertIn("- interna", bloque, servicio)
            self.assertNotIn("- frontal", bloque, servicio)

    def test_contrasena_de_postgres_no_es_la_de_fabrica(self):
        self.assertNotIn("POSTGRES_PASSWORD=typebot", COMPOSE)
        self.assertNotIn("POSTGRES_PASSWORD: typebot", COMPOSE)
        self.assertIn("${POSTGRES_PASSWORD:?", COMPOSE)

    def test_sin_privilegios(self):
        self.assertIn("no-new-privileges:true", COMPOSE.split("services:")[0])  # en la plantilla común
        self.assertEqual(COMPOSE.count("<<: *comun"), 4)    # proxy, db, redis y la plantilla de Typebot
        self.assertEqual(COMPOSE.count("<<: *typebot"), 2)  # editor y visor
        self.assertEqual(COMPOSE.count("cap_drop"), 2)      # plantilla de Typebot y proxy


class Env(unittest.TestCase):

    def test_sin_secretos_rellenos(self):
        """El ejemplo nunca lleva valores reales: los genera el script en el servidor."""
        for clave in ("ENCRYPTION_SECRET", "POSTGRES_PASSWORD", "SMTP_PASSWORD"):
            self.assertTrue(re.search(rf"^{clave}=$", ENV, re.M), clave)
        self.assertNotIn("do+UspMmB", ENV)  # la clave del .env.example oficial

    def test_registro_cerrado_y_sin_integraciones(self):
        self.assertIn("DISABLE_SIGNUP=true", ENV)
        for clave in ("S3_ACCESS_KEY=", "WEBHOOK_RELAY_SECRET=", "META_SYSTEM_USER_TOKEN=", "NEXT_PUBLIC_POSTHOG_KEY="):
            self.assertFalse(re.search(rf"^{clave}", ENV, re.M), clave)

    def test_editor_y_visor_en_dominios_distintos(self):
        visor = re.search(r"^EVA_DOMINIO_VISOR=(\S+)", ENV, re.M).group(1)
        editor = re.search(r"^EVA_DOMINIO_EDITOR=(\S+)", ENV, re.M).group(1)
        self.assertNotEqual(visor, editor)
        self.assertIn(f"NEXTAUTH_URL=https://{editor}", ENV)
        self.assertIn(f"NEXT_PUBLIC_VIEWER_URL=https://{visor}", ENV)

    def test_no_hay_env_real_en_el_repositorio(self):
        self.assertFalse((PAQUETE / ".env").exists(), "servidor-propio/.env no debe subirse nunca")
        gitignore = (RAIZ / ".gitignore")
        self.assertTrue(gitignore.exists() and "servidor-propio/.env" in gitignore.read_text(), ".gitignore")


class Proxy(unittest.TestCase):

    def test_visor_solo_las_rutas_de_la_burbuja(self):
        for ruta in ("startChat", "continueChat", "clientLogs"):
            self.assertIn(ruta, CADDY)
            self.assertIn(ruta, NGINX)
        self.assertNotIn("results", CADDY.split("EVA_DOMINIO_EDITOR}")[0].split("Visor")[1])

    def test_origen_obligatorio_y_solo_emalsa(self):
        self.assertIn(r"header_regexp Origin ^https://(www\.)?emalsa\.es$", CADDY)
        self.assertIn('"https://www.emalsa.es" 1;', NGINX)
        self.assertIn("default                 0;", NGINX)

    def test_todo_lo_demas_404_y_editor_403_desde_fuera(self):
        self.assertRegex(CADDY, r'respond "No encontrado" 404')
        self.assertRegex(CADDY, r'respond "Acceso restringido" 403')
        self.assertIn("return 404;", NGINX)
        self.assertIn("return 403;", NGINX)

    def test_cabeceras_de_seguridad(self):
        for cab in ("Strict-Transport-Security", "X-Content-Type-Options", "Referrer-Policy",
                    "Permissions-Policy", "frame-ancestors 'none'"):
            self.assertIn(cab, CADDY, cab)
            self.assertIn(cab, NGINX, cab)
        self.assertIn("-Server", CADDY)

    def test_limite_de_cuerpo(self):
        self.assertIn("max_size 64KB", CADDY)
        self.assertIn("client_max_body_size 64k", NGINX)

    def test_los_orígenes_del_proxy_coinciden_con_los_del_flujo(self):
        """Lo que deja pasar el proxy debe ser lo mismo que acepta el bot."""
        patron = re.compile(r"^https://(www\.)?emalsa\.es$")
        for origen in preparar_flujo.ORIGENES_EMPRESA:
            self.assertRegex(origen, patron)
            self.assertIn(f'"{origen}"', NGINX)


class Flujo(unittest.TestCase):

    def setUp(self):
        self.bot = preparar_flujo.preparar(FLUJO)

    def test_pasa_el_verificador(self):
        self.assertEqual(verificar.verificar_flujo(self.bot), [])

    def test_solo_cambian_origenes_y_datos_de_la_cuenta(self):
        """Lo que se importa en el servidor de la empresa es el flujo revisado, nada más."""
        cambios = {k for k in set(FLUJO) | set(self.bot) if FLUJO.get(k) != self.bot.get(k)}
        self.assertLessEqual(cambios, {"settings", "folderId", "customDomain", "whatsAppCredentialsId",
                                       "resultsTablePreferences", "publicId"}, cambios)
        ajustes = {k: v for k, v in self.bot["settings"].items() if k not in ("security", "general")}
        self.assertEqual(ajustes, {k: v for k, v in FLUJO["settings"].items() if k not in ("security", "general")})
        general = dict(self.bot["settings"]["general"])
        self.assertIs(general.pop("isBrandingEnabled"), False)
        self.assertEqual(general, {k: v for k, v in FLUJO["settings"]["general"].items() if k != "isBrandingEnabled"})
        self.assertEqual(self.bot["groups"], FLUJO["groups"])
        self.assertEqual(self.bot["edges"], FLUJO["edges"])

    def test_sin_github_pages_ni_otros_origenes(self):
        self.assertEqual(set(self.bot["settings"]["security"]["allowedOrigins"]),
                         {"https://emalsa.es", "https://www.emalsa.es"})
        self.assertIsNone(self.bot["publicId"])

    def test_archivo_generado_al_dia(self):
        """El JSON guardado en el paquete debe ser el que genera el script ahora."""
        generado = json.loads((PAQUETE / "flujo" / "eva-chatbot.servidor-propio.json").read_text(encoding="utf-8"))
        self.assertEqual(generado, self.bot, "ejecute servidor-propio/scripts/preparar-flujo.py")


class Web(unittest.TestCase):

    def test_la_burbuja_apunta_al_visor_de_la_empresa(self):
        self.assertIn('apiHost: "https://asistente.emalsa.es"', INCRUSTAR)
        self.assertIn("https://asistente.emalsa.es", verificar.VISORES_PERMITIDOS)
        self.assertIn("EVA_DOMINIO_VISOR=asistente.emalsa.es", ENV)
        self.assertIn('typebot: "eva"', INCRUSTAR)
        self.assertIn("EVA_PUBLIC_ID=eva", ENV)

    def test_la_burbuja_no_pasa_datos_al_bot(self):
        for clave in ("prefilledVariables", "sessionId", "resultId", "wsHost"):
            self.assertNotIn(clave, INCRUSTAR)

    def test_sin_cdn(self):
        self.assertNotIn("cdn.jsdelivr", INCRUSTAR)
        self.assertNotIn("unpkg", INCRUSTAR)

    def test_apuntar_web_deja_la_pagina_verificable(self):
        """Con el visor de la empresa, index.html debe seguir pasando el verificador; con otro, no."""
        import tempfile, shutil
        html = (RAIZ / "index.html").read_text(encoding="utf-8")
        con_visor = html.replace('typebot: "eva-asistente-virtual-de-emalsa-oi2fy0m",',
                                 'typebot: "eva",\n    apiHost: "https://asistente.emalsa.es",')
        self.assertEqual([e for e in verificar.verificar_pagina(con_visor) if "apiHost" in e], [])
        ajeno = con_visor.replace("https://asistente.emalsa.es", "https://asistente.evil.example")
        self.assertTrue(any("apiHost" in e for e in verificar.verificar_pagina(ajeno)))


class Scripts(unittest.TestCase):

    def test_scripts_de_shell_tienen_sintaxis_valida(self):
        for s in (PAQUETE / "scripts").glob("*.sh"):
            r = subprocess.run(["bash", "-n", str(s)], capture_output=True, text=True)
            self.assertEqual(r.returncode, 0, f"{s.name}: {r.stderr}")

    def test_purga_borra_resultados_y_sesiones(self):
        purga = (PAQUETE / "scripts" / "purgar-resultados.sh").read_text(encoding="utf-8")
        self.assertIn('DELETE FROM "Result"', purga)
        self.assertIn('DELETE FROM "ChatSession"', purga)
        self.assertIn("ON_ERROR_STOP", purga)


if __name__ == "__main__":
    unittest.main()
