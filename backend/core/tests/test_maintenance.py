import os
from unittest.mock import patch
from django.test import SimpleTestCase
from deploy.azure.wsgi import MaintenanceGate


class MaintenanceTests(SimpleTestCase):
    def test_gate_blocks_page_and_api_changes(self):
        with patch.dict(os.environ, {"TRELLIS_MAINTENANCE_MODE": "1"}):
            for path in ("/", "/api/execute/1/", "/api/studio/1/edit/", "/api/auth/login/"):
                status=[]
                body=MaintenanceGate(lambda *_: self.fail("Reached application"))(
                    {"PATH_INFO":path}, lambda code,headers:status.append(code))
                self.assertEqual(status,["503 Service Unavailable"])
                self.assertIn(b"saved work",b"".join(body))

    def test_gate_preserves_authenticated_worker_completion_path(self):
        with patch.dict(os.environ, {"TRELLIS_MAINTENANCE_MODE": "1"}):
            for path in ("/api/runner/claim/", "/api/runner/complete/test/", "/health/"):
                app=lambda *_:[b"normal authentication still applies"]
                self.assertEqual(MaintenanceGate(app)({"PATH_INFO":path},lambda *_:None),app())

    def test_gate_is_disabled_by_default(self):
        with patch.dict(os.environ, {}, clear=True):
            self.assertEqual(MaintenanceGate(lambda *_:[b"app"] )({"PATH_INFO":"/"},lambda *_:None),[b"app"])
