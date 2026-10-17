#!/usr/bin/env python3
"""Check public HTTP(S) connectivity over IPv4 and IPv6, notify on recovery."""
import json
import http.client
import logging
import os
import signal
import socket
import ssl
import sys
import time
import urllib.parse
from pathlib import Path

TARGETS = [("cloudflare", "1.1.1.1", "2606:4700:4700::1111", "cloudflare-dns.com"),
           ("google", "8.8.8.8", "2001:4860:4860::8888", "dns.google")]
STOP = False


def get_int(name, default, minimum=1):
    result = int(os.environ.get(name, default))
    if result < minimum:
        raise ValueError(f"{name} must be >= {minimum}")
    return result


def probe(ip, hostname, family, timeout):
    """TLS over a literal IP, validating certificate for the expected hostname.

    Hostname is supplied as SNI and TLS hostname verification. This avoids DNS
    masking connectivity trouble while testing public HTTPS endpoints.
    """
    try:
        with socket.socket(family, socket.SOCK_STREAM) as sock:
            sock.settimeout(timeout)
            sock.connect((ip, 443))
            with ssl.create_default_context().wrap_socket(sock, server_hostname=hostname) as tls:
                tls.settimeout(timeout)
                tls.sendall(f"HEAD / HTTP/1.1\r\nHost: {hostname}\r\nConnection: close\r\n\r\n".encode())
                response = tls.recv(128)
                return response.startswith(b"HTTP/")
    except (OSError, ssl.SSLError) as exc:
        logging.debug("Probe %s (%s) failed: %s", hostname, ip, exc)
        return False


def check(timeout):
    details = {}
    for name, ipv4, ipv6, hostname in TARGETS:
        details[name] = {
            "ipv4": probe(ipv4, hostname, socket.AF_INET, timeout),
            "ipv6": probe(ipv6, hostname, socket.AF_INET6, timeout),
        }
    return {"ipv4": any(v["ipv4"] for v in details.values()),
            "ipv6": any(v["ipv6"] for v in details.values()),
            "details": details}


class IPv6HTTPSConnection(http.client.HTTPSConnection):
    """Use IPv6 only; preserve TLS verification for api.telegram.org."""

    def connect(self):
        addresses = socket.getaddrinfo(self.host, self.port, socket.AF_INET6,
                                       socket.SOCK_STREAM)
        last_error = None
        for family, socktype, proto, _, address in addresses:
            try:
                sock = socket.socket(family, socktype, proto)
                sock.settimeout(self.timeout)
                try:
                    sock.connect(address)
                    self.sock = self._context.wrap_socket(sock, server_hostname=self.host)
                    return
                except Exception:
                    sock.close()
                    raise
            except OSError as exc:
                last_error = exc
        raise last_error or OSError("No IPv6 address available for Telegram")


def telegram(token, chat_id, message, timeout):
    """Send Telegram notification via IPv6 even when IPv4 is unavailable."""
    data = urllib.parse.urlencode({"chat_id": chat_id, "text": message}).encode()
    connection = IPv6HTTPSConnection("api.telegram.org", timeout=timeout,
                                     context=ssl.create_default_context())
    try:
        connection.request("POST", f"/bot{token}/sendMessage", body=data,
                           headers={"Content-Type": "application/x-www-form-urlencoded"})
        response = connection.getresponse()
        payload = json.loads(response.read())
        if response.status != 200 or not payload.get("ok"):
            raise RuntimeError(f"Telegram HTTP {response.status}: "
                               f"{payload.get('description', 'request failed')}")
    finally:
        connection.close()


def load_state(path):
    try:
        data = json.loads(path.read_text())
        return {"healthy": bool(data.get("healthy", False)), "notified": bool(data.get("notified", False))}
    except (OSError, ValueError):
        return {"healthy": False, "notified": False}


def save_state(path, state):
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(path.name + ".tmp")
    temp.write_text(json.dumps(state))
    temp.replace(path)


def run():
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
    chat_id = os.environ.get("TELEGRAM_CHAT_ID", "").strip()
    if not token or not chat_id:
        raise ValueError("TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID are required")
    interval = get_int("CHECK_INTERVAL_SECONDS", 60)
    timeout = get_int("CONNECT_TIMEOUT_SECONDS", 4)
    streak_needed = get_int("SUCCESS_STREAK", 3)
    state_file = Path(os.environ.get("STATE_FILE", "/data/state.json"))
    state = load_state(state_file)
    streak = 0
    startup_pending = True

    def stop(_signum, _frame):
        global STOP
        STOP = True

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    logging.info("Monitoring HTTPS IPv4 and IPv6, interval=%ss, confirmations=%s", interval, streak_needed)
    while not STOP:
        result = check(timeout)
        healthy = result["ipv4"] and result["ipv6"]
        logging.info("IPv4=%s IPv6=%s details=%s", "OK" if result["ipv4"] else "FAIL",
                     "OK" if result["ipv6"] else "FAIL", result["details"])
        streak = streak + 1 if healthy else 0
        if not healthy and (state["healthy"] or state["notified"]):
            state = {"healthy": False, "notified": False}
            save_state(state_file, state)
        # Telegram notifications use IPv6. Do not wait for IPv4 to send startup.
        if startup_pending:
            try:
                telegram(token, chat_id,
                         "🚀 Moniteur Internet démarré.\n"
                         f"IPv4 : {'OK' if result['ipv4'] else 'KO'}\n"
                         f"IPv6 : {'OK' if result['ipv6'] else 'KO'}\n"
                         f"Intervalle : {interval} s.", timeout=4)
                startup_pending = False
                logging.info("Startup notification sent via IPv6")
            except (OSError, ValueError, RuntimeError) as exc:
                logging.warning("Startup Telegram notification unavailable via IPv6; retry next cycle: %s", exc)

        if healthy and streak >= streak_needed and not state["notified"]:
            message = ("✅ Connectivité Internet rétablie !\n"
                       "IPv4 : OK (HTTPS)\nIPv6 : OK (HTTPS)\n"
                       f"Confirmation : {streak_needed} vérifications consécutives.")
            try:
                telegram(token, chat_id, message, timeout=4)
                state = {"healthy": True, "notified": True}
                save_state(state_file, state)
                logging.info("Recovery notification sent")
            except (OSError, ValueError, RuntimeError) as exc:
                logging.warning("Cannot send recovery Telegram message yet; will retry: %s", exc)
        # Sleep in short increments to respond to shutdown promptly.
        for _ in range(interval):
            if STOP:
                break
            time.sleep(1)


if __name__ == "__main__":
    logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"),
                        format="%(asctime)s %(levelname)s %(message)s")
    try:
        run()
    except (ValueError, OSError) as exc:
        logging.error("Startup failed: %s", exc)
        sys.exit(1)
