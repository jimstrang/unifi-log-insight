"""
Shared dependencies for route modules.

Singletons (database pools, enrichers, UniFi client) are initialized here
at import time and imported by route modules via `from deps import ...`.
"""

import logging
import os
import subprocess
import time

from psycopg2 import pool

from db import Database, get_db_connection_params, is_external_db
from enrichment import AbuseIPDBEnricher
from unifi_api import UniFiAPI

logger = logging.getLogger('api')

# ── Version ──────────────────────────────────────────────────────────────────

def _read_version():
    for path in ('/app/VERSION', 'VERSION'):
        try:
            with open(path) as f:
                return f.read().strip()
        except FileNotFoundError:
            continue
    return 'unknown'

APP_VERSION = _read_version()

# ── Database ─────────────────────────────────────────────────────────────────

conn_params = get_db_connection_params()
logger.info("API database target: %s@%s:%s/%s%s",
            conn_params['user'], conn_params['host'],
            conn_params['port'], conn_params['dbname'],
            " (external)" if is_external_db() else " (bundled)")

db_pool = pool.ThreadedConnectionPool(2, 10, **conn_params)


def get_conn():
    return db_pool.getconn()


def put_conn(conn):
    db_pool.putconn(conn)


# ── AbuseIPDB Enricher (for manual enrich endpoint) ─────────────────────────

enricher_db = Database(conn_params, min_conn=1, max_conn=3)
enricher_db.connect()
abuseipdb = AbuseIPDBEnricher(db=enricher_db)

# ── UniFi API Client ────────────────────────────────────────────────────────

unifi_api = UniFiAPI(db=enricher_db)


# ── Helpers ──────────────────────────────────────────────────────────────────

def signal_receiver():
    """Signal the receiver process to reload config."""
    try:
        subprocess.run(['pkill', '-SIGUSR2', '-f', '/app/main.py'],
                      check=False, timeout=2)
        with open('/tmp/config_update_requested', 'w') as f:
            f.write(str(time.time()))
        logger.info("Signaled receiver process to reload config")
    except Exception as e:
        logger.warning("Failed to signal receiver: %s", e)
