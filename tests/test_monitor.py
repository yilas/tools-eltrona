import importlib.util
import socket
import unittest
from pathlib import Path
from unittest.mock import patch

spec = importlib.util.spec_from_file_location('monitor', Path(__file__).resolve().parents[1] / 'monitor.py')
monitor = importlib.util.module_from_spec(spec)
spec.loader.exec_module(monitor)


class MonitorTests(unittest.TestCase):
    def test_both_families_must_have_a_success(self):
        def fake_probe(ip, hostname, family, timeout):
            return ((family == socket.AF_INET and ip == '1.1.1.1') or
                    (family == socket.AF_INET6 and ip == '2001:4860:4860::8888'))
        with patch.object(monitor, 'probe', fake_probe):
            state = monitor.check(2)
        self.assertTrue(state['ipv4'])
        self.assertTrue(state['ipv6'])

    def test_ipv4_down_is_not_healthy(self):
        with patch.object(monitor, 'probe', side_effect=lambda ip, hostname, family, timeout: family == socket.AF_INET6):
            state = monitor.check(2)
        self.assertFalse(state['ipv4'])
        self.assertTrue(state['ipv6'])

    def test_tls_socket_error_is_failure(self):
        with patch.object(monitor.socket, 'socket', side_effect=OSError('no route')):
            self.assertFalse(monitor.probe('1.1.1.1', 'cloudflare-dns.com', socket.AF_INET, 2))

    def test_startup_message_is_sent_even_when_ipv4_is_down(self):
        import tempfile
        with tempfile.TemporaryDirectory() as temp:
            def check_and_stop(timeout):
                monitor.STOP = True
                return {"ipv4": False, "ipv6": True, "details": {}}
            monitor.STOP = False
            try:
                with patch.dict(monitor.os.environ, {
                    "TELEGRAM_BOT_TOKEN": "example", "TELEGRAM_CHAT_ID": "123456789",
                    "STATE_FILE": str(Path(temp) / "state.json")
                }), patch.object(monitor, "telegram") as send, \
                    patch.object(monitor, "check", side_effect=check_and_stop), \
                    patch.object(monitor.signal, "signal"):
                    monitor.run()
                    self.assertEqual(send.call_count, 1)
                    self.assertIn("démarré", send.call_args.args[2])
            finally:
                monitor.STOP = False

    def test_state_roundtrip(self):
        import tempfile
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / 'state.json'
            self.assertEqual(monitor.load_state(path), {'healthy': False, 'notified': False})
            monitor.save_state(path, {'healthy': True, 'notified': True})
            self.assertEqual(monitor.load_state(path), {'healthy': True, 'notified': True})


if __name__ == '__main__':
    unittest.main()
