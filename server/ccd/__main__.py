"""python -m ccd — run the daemon on 127.0.0.1:7777.

The bind address is fixed in code (owner decision 6). There is no flag or
environment variable that makes ccd listen anywhere but loopback.
"""
import asyncio
import contextlib
import json
import logging
import logging.handlers
import os
import sys

import uvicorn

from . import __version__, config, security
from .api import create_app
from .daemon import Daemon
from .herdr import Herdr
from .store import Store


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


def setup_logging():
    config.STATE_DIR.mkdir(parents=True, exist_ok=True)
    handler = logging.handlers.RotatingFileHandler(config.STATE_DIR / "ccd.log", maxBytes=10 * 1024 * 1024,
                                                   backupCount=3)
    handler.setFormatter(_JsonLines())
    root = logging.getLogger()
    root.handlers[:] = [handler]
    root.setLevel(logging.INFO)
    # uvicorn's access log would record query strings, and the WS token can be one.
    logging.getLogger("uvicorn.access").disabled = True


def build(cfg=None):
    cfg = cfg or config.load()
    store = Store(config.STATE_DIR / "ccd.db")
    daemon = Daemon(cfg, store, Herdr(config.HERDR_SOCKET))
    token = security.load_or_create_token(config.TOKEN_PATH)

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
