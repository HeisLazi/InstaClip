"""InstaClip relational layer (blueprint Phase 1).

`init_db()` brings the schema to the latest Alembic revision (building it from
scratch on a fresh install, or applying pending migrations on an existing one)
and seeds the default creator. Startup goes through Alembic — not a bare
`create_all` — so column-adding migrations actually reach existing databases.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path

from sqlalchemy import inspect

from db.base import Base, DEFAULT_CREATOR_ID, SessionLocal, engine
from db import models

log = logging.getLogger("db")


def _upgrade_to_head() -> None:
    """Run Alembic migrations up to head.

    Uses a bare `Config` (no .ini file) so Alembic's `fileConfig` never runs and
    therefore cannot disable the app's existing loggers. `env.py` supplies the
    DB URL from `db.base._DB_URL`. Falls back to `create_all` only if Alembic is
    unavailable, so a fresh install still boots.
    """
    try:
        from alembic import command
        from alembic.config import Config

        from config import paths

        cfg = Config()
        bundle_root = Path(os.environ.get("INSTACLIP_BUNDLE_ROOT", paths.ROOT_DIR))
        cfg.set_main_option("script_location", str(bundle_root / "db" / "migrations"))
        if "alembic_version" not in inspect(engine).get_table_names():
            # The historical initial revision is intentionally empty. A fresh
            # install needs the current schema before it can enter the normal
            # incremental migration chain.
            Base.metadata.create_all(engine)
            command.stamp(cfg, "head")
            log.info("fresh schema created and stamped at Alembic head")
            return
        command.upgrade(cfg, "head")
        log.info("schema migrated to Alembic head")
    except Exception as exc:  # noqa: BLE001 — the app must still boot
        log.warning("Alembic upgrade failed (%s); creating tables directly", exc)
        Base.metadata.create_all(engine)


def init_db() -> None:
    _upgrade_to_head()
    with SessionLocal() as session:
        existing = session.get(models.Creator, DEFAULT_CREATOR_ID)
        if existing is None:
            session.add(models.Creator(id=DEFAULT_CREATOR_ID, slug=DEFAULT_CREATOR_ID, name="Default Creator"))
            session.commit()
            log.info("seeded default creator '%s'", DEFAULT_CREATOR_ID)


__all__ = ["Base", "SessionLocal", "engine", "init_db", "models", "DEFAULT_CREATOR_ID"]
