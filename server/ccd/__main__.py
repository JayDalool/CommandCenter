"""python -m ccd — run the daemon on 127.0.0.1:7777.

The bind address is fixed in code (owner decision 6). There is no flag or
environment variable that makes ccd listen anywhere but loopback.
"""
import asyncio
import contextlib
import hmac
import json
import logging
import logging.handlers
import os
import re
import sys

import uvicorn

from . import __version__, attachments, config, files, security
from .api import create_app
from .daemon import Daemon
from .herdr import Herdr
from .store import Store
from .tasks import TaskStore


class _JsonLines(logging.Formatter):
    def format(self, record):
        msg = record.getMessage()
        try:
            body = json.loads(msg)
            if not isinstance(body, dict):
                body = {"msg": msg}
        except (json.JSONDecodeError, TypeError):
            body = {"msg": msg}
        body.update(level=record.levelname, logger=record.name,
                    at=self.formatTime(record, "%Y-%m-%dT%H:%M:%S"))
        if record.exc_info:
            body["exc"] = self.formatException(record.exc_info)[-2000:]
        return json.dumps(body)


class _RedactTokens(logging.Filter):
    """uvicorn logs each WebSocket path with its query string, and a browser's
    token arrives as ?token=. Scrub it before anything reaches the file."""
    _pat = re.compile(r"(token=)[^&\s\"']+")

    def filter(self, record):
        msg = record.getMessage()
        clean = self._pat.sub(r"\1[redacted]", msg)
        if clean != msg:
            record.msg, record.args = clean, ()
        return True


def setup_logging():
    config.STATE_DIR.mkdir(parents=True, exist_ok=True)
    handler = logging.handlers.RotatingFileHandler(config.STATE_DIR / "ccd.log", maxBytes=10 * 1024 * 1024,
                                                   backupCount=3)
    handler.setFormatter(_JsonLines())
    handler.addFilter(_RedactTokens())
    root = logging.getLogger()
    root.handlers[:] = [handler]
    root.setLevel(logging.INFO)
    # uvicorn's access log would record query strings, and the WS token can be one.
    logging.getLogger("uvicorn.access").disabled = True


def build(cfg=None):
    cfg = cfg or config.load()
    store = Store(config.STATE_DIR / "ccd.db")
    config.DATA_DIR.mkdir(parents=True, exist_ok=True, mode=0o700)
    tasks = TaskStore(config.DATA_DIR / "tasks.db", config.task_projects(cfg))
    daemon = Daemon(cfg, store, Herdr(config.HERDR_SOCKET), tasks=tasks)
    token = security.load_or_create_token(config.TOKEN_PATH)
    # Workspace: registered roots only; attachments outside every repository;
    # a second credential (developer.token, 0600) for anything that writes.
    upload_max = int(cfg.get("upload_max_mb") or 50) * 1024 * 1024
    daemon.files = files.Roots(upload_max=upload_max)
    daemon.attachments = attachments.Attachments(config.DATA_DIR / "attachments.db", config.ATTACH_DIR, upload_max)
    dev_secret = security.load_or_create_token(config.DEV_TOKEN_PATH)
    if hmac.compare_digest(dev_secret, token):
        sys.exit("developer.token must differ from ccd.token")
    daemon.dev_gate = security.DeveloperGate(dev_secret)
    daemon.launcher_dir = config.LAUNCHER_DIR

    @contextlib.asynccontextmanager
    async def lifespan(app):
        daemon.start()
        logging.getLogger("ccd").info(json.dumps({"msg": "started", "version": __version__, "pid": os.getpid(),
                                                  "bind": f"{config.HOST}:{config.PORT}"}))
        try:
            yield
        finally:
            await daemon.stop()
            store.close()
            tasks.close()
            daemon.attachments.close()
            logging.getLogger("ccd").info(json.dumps({"msg": "stopped"}))

    guarded, _ = create_app(daemon, token, config.PORT, lifespan=lifespan)
    return guarded, daemon


def main():
    if config.HOST != "127.0.0.1":  # belt and braces: refuse to run if someone edits HOST
        sys.exit("ccd binds 127.0.0.1 only")
    setup_logging()
    app, _ = build()
    server = uvicorn.Server(uvicorn.Config(
        app, host=config.HOST, port=config.PORT, log_config=None, access_log=False, server_header=False,
        proxy_headers=False, ws="websockets", lifespan="on", timeout_graceful_shutdown=3))
    asyncio.run(server.serve())


if __name__ == "__main__":
    main()
