from django.test import TestCase

from core.optimizer import (
    haversine,
    construir_vecino_mas_cercano,
    mejorar_2opt,
    optimizar_ruta,
    _distancia_total,
)

# Puntos cardinales aproximados alrededor de Santiago, separados por ~1 grado
# (no son distancias reales, solo sirven para tener una geometria conocida).
ORIGEN = (0.0, 0.0)
NORTE = (1, 0.0)
ESTE = (0.0, 1)
SUR = (-1, 0.0)
OESTE = (0.0, -1)


class HaversineTests(TestCase):
    def test_distancia_a_si_mismo_es_cero(self):
        self.assertAlmostEqual(haversine(-33.45, -70.65, -33.45, -70.65), 0.0, places=6)

    def test_distancia_conocida_un_grado_de_latitud(self):
        # ~111.19 km es la distancia estandar de 1 grado de latitud en la Tierra.
        d = haversine(0.0, 0.0, 1.0, 0.0)
        self.assertAlmostEqual(d, 111.19, delta=0.5)

    def test_simetrica(self):
        d1 = haversine(-33.4, -70.6, -33.5, -70.7)
        d2 = haversine(-33.5, -70.7, -33.4, -70.6)
        self.assertAlmostEqual(d1, d2, places=9)


class ConstruirVecinoMasCercanoTests(TestCase):
    def test_sin_puntos(self):
        self.assertEqual(construir_vecino_mas_cercano(ORIGEN, []), [])

    def test_un_punto(self):
        puntos = [(1, *NORTE)]
        self.assertEqual(construir_vecino_mas_cercano(ORIGEN, puntos), [1])

    def test_elige_el_mas_cercano_primero(self):
        cercano = (0.01, 0.0)
        lejano = (5.0, 0.0)
        puntos = [(1, *lejano), (2, *cercano)]
        orden = construir_vecino_mas_cercano(ORIGEN, puntos)
        self.assertEqual(orden[0], 2)


class Mejorar2optTests(TestCase):
    def test_no_empeora_un_tour_ya_optimo(self):
        # Cuadrado: el orden en sentido horario ya es el tour optimo.
        puntos = [(1, 0, 1), (2, 1, 1), (3, 1, 0), (4, 0, 0)]
        orden_inicial = [1, 2, 3, 4]
        orden_mejorado = mejorar_2opt((0, 0), puntos, orden_inicial)
        dist_inicial = _distancia_total((0, 0), puntos, orden_inicial)
        dist_mejorada = _distancia_total((0, 0), puntos, orden_mejorado)
        self.assertLessEqual(dist_mejorada, dist_inicial + 1e-9)

    def test_corrige_un_tour_cruzado(self):
        # Un cuadrado con el orden "cruzado" (1,3,2,4) debe mejorar a un
        # tour sin cruces tras 2-opt.
        puntos = [(1, 0, 1), (2, 1, 1), (3, 1, 0), (4, 0, 0)]
        orden_cruzado = [1, 3, 2, 4]
        orden_mejorado = mejorar_2opt((0, 0), puntos, orden_cruzado)
        dist_cruzada = _distancia_total((0, 0), puntos, orden_cruzado)
        dist_mejorada = _distancia_total((0, 0), puntos, orden_mejorado)
        self.assertLess(dist_mejorada, dist_cruzada)

    def test_menos_de_4_puntos_no_cambia(self):
        puntos = [(1, 0, 1), (2, 1, 0)]
        orden = [1, 2]
        self.assertEqual(mejorar_2opt((0, 0), puntos, orden), orden)


class OptimizarRutaTests(TestCase):
    def test_sin_puntos(self):
        self.assertEqual(optimizar_ruta(ORIGEN, []), [])

    def test_un_punto(self):
        puntos = [(1, *NORTE)]
        self.assertEqual(optimizar_ruta(ORIGEN, puntos), [1])

    def test_resultado_nunca_peor_que_vecino_mas_cercano(self):
        puntos = [(1, 0.5, 0.9), (2, 1.0, 0.1), (3, 0.2, 0.4), (4, 0.8, 0.8), (5, 0.1, 0.9)]
        orden_nn = construir_vecino_mas_cercano(ORIGEN, puntos)
        orden_final = optimizar_ruta(ORIGEN, puntos)
        self.assertLessEqual(
            _distancia_total(ORIGEN, puntos, orden_final),
            _distancia_total(ORIGEN, puntos, orden_nn) + 1e-9,
        )
        self.assertEqual(set(orden_final), {1, 2, 3, 4, 5})
