import unittest

from fastapi.testclient import TestClient

from app.main import app


class CorsTests(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)

    def test_expo_web_origin_can_call_api(self):
        response = self.client.get(
            "/health",
            headers={"Origin": "http://localhost:8081"},
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.headers["access-control-allow-origin"],
            "http://localhost:8081",
        )

    def test_unconfigured_origin_is_not_allowed(self):
        response = self.client.options(
            "/api/v1/cities",
            headers={
                "Origin": "https://untrusted.example",
                "Access-Control-Request-Method": "GET",
            },
        )

        self.assertEqual(response.status_code, 400)
        self.assertNotIn("access-control-allow-origin", response.headers)


if __name__ == "__main__":
    unittest.main()
