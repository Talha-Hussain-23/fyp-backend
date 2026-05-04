# Gunicorn Configuration for Proctoring Server
# Production-ready WSGI server configuration

import multiprocessing
import os
import structlog

logger = structlog.get_logger("gunicorn")

# Server socket
bind = os.getenv("GUNICORN_BIND", "0.0.0.0:5000")
backlog = 2048

# Worker processes
workers = int(os.getenv("GUNICORN_WORKERS", 4))
worker_class = "geventwebsocket.gunicorn.workers.GeventWebSocketWorker"
worker_connections = 1000
timeout = 120
keepalive = 5

# Logging
accesslog = "-"  # Log to stdout
errorlog = "-"   # Log to stderr
loglevel = os.getenv("GUNICORN_LOG_LEVEL", "info")
access_log_format = '%(h)s %(l)s %(u)s %(t)s "%(r)s" %(s)s %(b)s "%(f)s" "%(a)s"'

# Process naming
proc_name = "smarthiring_proctoring"

# Server mechanics
daemon = False
pidfile = None
umask = 0
user = None
group = None
tmp_upload_dir = None

# Graceful timeout
graceful_timeout = 30

# Preload app for better performance
preload_app = True

# Server hooks
def on_starting(server):
    logger.info("proctoring_server_starting")

def on_reload(server):
    logger.info("proctoring_workers_reloading")

def when_ready(server):
    logger.info("proctoring_server_ready", bind=bind)

def worker_int(worker):
    logger.warning("worker_interrupted", pid=worker.pid)

def worker_abort(worker):
    logger.error("worker_aborted", pid=worker.pid)
