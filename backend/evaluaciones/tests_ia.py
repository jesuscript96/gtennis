"""El pulido de comentarios con Claude: sale solo el texto final (17/11/2026)."""
import json
from types import SimpleNamespace
from unittest import mock

from django.test import SimpleTestCase, override_settings

from . import ia

# Lo que salió de verdad en el informe de Ruohan (comentario del saque).
FUGA = ("Tenemos que mejorar el lanzamiento de bola, trabajar más los saques cortados o liftados al revés y "
        "aprovechar mejor las piernas y la mano para ganar velocidad y control.\n\n"
        "Corrección: no debo añadir información. Versión fiel:\n\n"
        "El jugador tiene que mejorar el lanzamiento de la bola, trabajar más los saques al revés y sacar más "
        "rendimiento de las piernas y de la mano para ganar velocidad y control.")
FIEL = ("El jugador tiene que mejorar el lanzamiento de la bola, trabajar más los saques al revés y sacar más "
        "rendimiento de las piernas y de la mano para ganar velocidad y control.")


def respuesta(texto, stop="end_turn"):
    return SimpleNamespace(stop_reason=stop, content=[SimpleNamespace(type="text", text=texto)])


class LimpiarRespuestaTests(SimpleTestCase):
    def test_se_queda_con_la_version_fiel(self):
        self.assertEqual(ia.limpiar_respuesta(FUGA), FIEL)

    def test_version_fiel_en_el_mismo_parrafo(self):
        self.assertEqual(ia.limpiar_respuesta("Borrador flojo.\n\nVersión fiel: Tiene buena volea: la aprovecha."),
                         "Tiene buena volea: la aprovecha.")

    def test_el_aviso_al_final_se_quita(self):
        self.assertEqual(ia.limpiar_respuesta("Domina el revés.\n\nAclaración: he respetado lo que dijo."),
                         "Domina el revés.")

    def test_en_ingles(self):
        self.assertEqual(ia.limpiar_respuesta("Draft.\nCorrection: no extra info. Faithful version:\nHe volleys well."),
                         "He volleys well.")

    def test_un_texto_normal_no_se_toca(self):
        self.assertEqual(ia.limpiar_respuesta("Debe mejorar la corrección de la técnica: es mejorable.\n"
                                              "Su nota es buena."),
                         "Debe mejorar la corrección de la técnica: es mejorable. Su nota es buena.")


@override_settings(ANTHROPIC_API_KEY="x")
class PulirTests(SimpleTestCase):
    def pulir(self, texto):
        with mock.patch.object(ia, "_llamar", return_value=respuesta(texto)) as m:
            return ia.pulir("comentario", "ES", "el Saque"), m

    def test_pide_salida_estructurada_y_lee_el_campo(self):
        r, m = self.pulir(json.dumps({"texto": "Mejora el saque."}))
        self.assertEqual(r, "Mejora el saque.")
        self.assertEqual(m.call_args.kwargs["output_config"]["format"]["type"], "json_schema")

    def test_aunque_cuele_una_correccion_sale_limpio(self):
        r, _ = self.pulir(json.dumps({"texto": FUGA}))
        self.assertEqual(r, FIEL)

    def test_respuesta_que_no_es_json_se_rechaza(self):
        with self.assertRaises(ia.IANoDisponible):
            self.pulir("Mejora el saque.")
        with self.assertRaises(ia.IANoDisponible):
            self.pulir(json.dumps({"otra": "cosa"}))
        with self.assertRaises(ia.IANoDisponible):
            self.pulir(json.dumps({"texto": "   "}))
