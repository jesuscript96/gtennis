"""Cuenta propia: cambiar la contraseña."""
from django.test import TestCase
from rest_framework.authtoken.models import Token
from rest_framework.test import APIClient

from users.models import User


class CambiarPasswordTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username="blas", password="inicial123", role=User.Role.ENTRENADOR)
        self.api = APIClient()
        self.api.force_authenticate(self.user)

    def _post(self, actual, nueva):
        return self.api.post("/api/auth/password/",
                             {"actual": actual, "nueva": nueva}, format="json")

    def test_la_cambia_y_devuelve_token_nuevo(self):
        viejo = Token.objects.create(user=self.user).key
        r = self._post("inicial123", "otracosa456")
        self.assertEqual(r.status_code, 200, r.data)
        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password("otracosa456"))
        self.assertNotEqual(r.data["token"], viejo)

    def test_sin_la_actual_no_la_cambia(self):
        r = self._post("loquesea", "otracosa456")
        self.assertEqual(r.status_code, 400)
        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password("inicial123"))

    def test_la_nueva_tiene_un_minimo(self):
        r = self._post("inicial123", "corta")
        self.assertEqual(r.status_code, 400)

    def test_no_vale_la_misma(self):
        r = self._post("inicial123", "inicial123")
        self.assertEqual(r.status_code, 400)

    def test_sin_sesion_no_se_puede(self):
        api = APIClient()
        r = api.post("/api/auth/password/",
                     {"actual": "inicial123", "nueva": "otracosa456"}, format="json")
        self.assertIn(r.status_code, (401, 403))
