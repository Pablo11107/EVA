#!/usr/bin/env python3
"""Prepara el flujo revisado (flujo/eva-chatbot.json) para importarlo en el
Typebot de EMALSA.

    python3 servidor-propio/scripts/preparar-flujo.py

Escribe servidor-propio/flujo/eva-chatbot.servidor-propio.json. Es el mismo
flujo, con tres diferencias, y solo esas:

  - allowedOrigins: solo emalsa.es y www.emalsa.es. La página de demostración
    de GitHub Pages deja de estar en la lista: la versión de la empresa solo
    se puede incrustar en la web de la empresa.
  - isBrandingEnabled: false. Sin la marca «Made with Typebot», que la nube
    gratuita obliga a mostrar.
  - publicId vacío: el identificador público se fija en el editor al publicar
    («Share»), y debe coincidir con EVA_PUBLIC_ID del .env del servidor.
  - Sin rastro de la cuenta de origen: carpeta, dominio personalizado,
    credenciales de WhatsApp y preferencias de la tabla de resultados.

Todo lo demás (grupos, botones, textos, enlaces, tema y ajustes) es idéntico
byte a byte al flujo revisado, y pruebas/test_paquete.py lo comprueba.
"""
import json
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[2]
ORIGEN = RAIZ / "flujo" / "eva-chatbot.json"
DESTINO = RAIZ / "servidor-propio" / "flujo" / "eva-chatbot.servidor-propio.json"

ORIGENES_EMPRESA = ["https://emalsa.es", "https://www.emalsa.es"]
CAMPOS_DE_LA_CUENTA = {"folderId": None, "customDomain": None, "whatsAppCredentialsId": None,
                       "resultsTablePreferences": None, "publicId": None}


def preparar(flujo):
    bot = dict(flujo.get("typebot", flujo))
    bot["settings"] = dict(bot.get("settings") or {})
    bot["settings"]["security"] = {"allowedOrigins": list(ORIGENES_EMPRESA)}
    # Sin «Made with Typebot». En la nube gratuita Typebot lo fuerza al importar; en el servidor
    # propio, con el plan ilimitado del administrador, respeta este valor.
    bot["settings"]["general"] = {**(bot["settings"].get("general") or {}), "isBrandingEnabled": False}
    for campo, valor in CAMPOS_DE_LA_CUENTA.items():
        if campo in bot:
            bot[campo] = valor
    return bot


def main():
    flujo = json.loads(ORIGEN.read_text(encoding="utf-8"))
    bot = preparar(flujo)
    DESTINO.parent.mkdir(parents=True, exist_ok=True)
    DESTINO.write_text(json.dumps(bot, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Escrito {DESTINO.relative_to(RAIZ)}: {len(bot['groups'])} grupos, orígenes {ORIGENES_EMPRESA}")

    # Debe seguir pasando el verificador del repositorio, con sus mismas reglas.
    sys.path.insert(0, str(RAIZ / "scripts"))
    import verificar  # noqa: E402
    errores = verificar.verificar_flujo(bot)
    if errores:
        print("El flujo preparado NO pasa el verificador:", *errores, sep="\n  - ")
        sys.exit(1)
    print("El flujo preparado pasa el verificador.")


if __name__ == "__main__":
    main()
