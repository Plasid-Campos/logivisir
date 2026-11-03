"""
Chat de ayuda guiado: aparece en el sitio público, sus precios son los que se
cobran y cada tema apunta a temas que existen.
"""
from django.test import TestCase, override_settings
from django.urls import reverse

from core import chat_ayuda, membresias


class ChatAyudaTests(TestCase):
    def test_aparece_en_inicio_y_en_solicitud(self):
        for nombre in ("home", "solicitar_cuenta"):
            resp = self.client.get(reverse(nombre))
            self.assertContains(resp, 'id="lvc-datos"', msg_prefix=nombre)
            self.assertContains(resp, "chat_ayuda.js", msg_prefix=nombre)

    def test_precios_del_chat_son_los_vigentes(self):
        tema = next(t for t in chat_ayuda.temas() if t["id"] == "precios")
        texto = " ".join(tema["mensajes"])
        for precio in membresias.PRECIOS_PLAN.values():
            self.assertIn(f"${precio:,}".replace(",", "."), texto)

    def test_temas_bien_enlazados(self):
        datos = chat_ayuda.datos_widget()
        ids = {t["id"] for t in datos["temas"]}
        self.assertEqual(len(ids), len(datos["temas"]))
        for t in datos["temas"]:
            self.assertTrue(t["mensajes"] and t["claves"], t["id"])
            self.assertTrue(set(t["siguientes"]) <= ids, t["id"])
        self.assertTrue(set(datos["inicio"]) <= ids)

    def test_sin_contacto_configurado_no_inventa_canales(self):
        datos = chat_ayuda.datos_widget()
        self.assertEqual((datos["contacto"]["email"], datos["contacto"]["whatsapp"]), ("", ""))

    @override_settings(CONTACTO_WHATSAPP="+56 9 8765 4321")
    def test_whatsapp_configurado_llega_al_chat(self):
        resp = self.client.get(reverse("home"))
        self.assertContains(resp, "56987654321")
