import sqlite3
from datetime import datetime

from flask import current_app, g


def get_db():
    if "db" not in g:
        g.db = sqlite3.connect(current_app.config["DATABASE_PATH"])
        g.db.row_factory = sqlite3.Row
        g.db.execute("PRAGMA foreign_keys = ON")
    return g.db


def close_db(e=None):
    db = g.pop("db", None)
    if db is not None:
        db.close()


def _columnas(db, tabla):
    return {fila["name"] for fila in db.execute(f"PRAGMA table_info({tabla})")}


def _migrar(db):
    """Suma columnas nuevas a tablas que ya existían antes de este cambio, sin tocar
    los datos que ya haya cargados (ALTER TABLE ADD COLUMN no borra nada)."""
    columnas_organizadores = _columnas(db, "organizadores")
    for columna, tipo in (
        ("mp_user_id", "TEXT"),
        ("mp_access_token", "TEXT"),
        ("mp_refresh_token", "TEXT"),
    ):
        if columna not in columnas_organizadores:
            db.execute(f"ALTER TABLE organizadores ADD COLUMN {columna} {tipo}")

    columnas_ordenes = _columnas(db, "ordenes")
    for columna, tipo in (
        ("subtotal", "REAL"),
        ("recargo_porcentaje_aplicado", "REAL"),
        ("recargo_total", "REAL"),
    ):
        if columna not in columnas_ordenes:
            db.execute(f"ALTER TABLE ordenes ADD COLUMN {columna} {tipo}")

    db.execute(
        "INSERT OR IGNORE INTO configuracion (clave, valor) VALUES ('recargo_porcentaje', '10')"
    )
    db.commit()


def init_db(app):
    with app.app_context():
        db = get_db()
        with app.open_resource("schema.sql") as f:
            db.executescript(f.read().decode("utf8"))
        db.commit()
        _migrar(db)


def init_app(app):
    app.teardown_appcontext(close_db)
    init_db(app)


def now_iso():
    return datetime.utcnow().isoformat(timespec="seconds")
