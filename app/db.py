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


def _sumar_columnas(db, tabla, columnas):
    existentes = _columnas(db, tabla)
    for columna, tipo in columnas:
        if columna not in existentes:
            db.execute(f"ALTER TABLE {tabla} ADD COLUMN {columna} {tipo}")


def _migrar(db):
    """Suma columnas nuevas a tablas que ya existían antes de este cambio, sin tocar
    los datos que ya haya cargados (ALTER TABLE ADD COLUMN no borra nada)."""
    _sumar_columnas(
        db,
        "organizadores",
        (
            ("mp_user_id", "TEXT"),
            ("mp_access_token", "TEXT"),
            ("mp_refresh_token", "TEXT"),
            # Clave pública de Mercado Pago del organizador: la necesita el
            # formulario de pago embebido (Payment Brick) para tokenizar la tarjeta.
            ("mp_public_key", "TEXT"),
            # Recargo especial para este organizador (NULL = usa el general).
            ("recargo_porcentaje", "REAL"),
            ("recargo_fijo", "REAL"),
            ("suspendido", "INTEGER NOT NULL DEFAULT 0"),
            # Alias o CBU donde la plataforma le transfiere lo vendido (cobro centralizado).
            ("datos_cobro", "TEXT"),
        ),
    )
    _sumar_columnas(
        db,
        "eventos",
        (
            # Recargo especial para este evento (NULL = usa el del organizador o el general).
            ("recargo_porcentaje", "REAL"),
            ("recargo_fijo", "REAL"),
            # Bloqueado por el dueño de la plataforma: no se ve ni se puede publicar.
            ("bloqueado", "INTEGER NOT NULL DEFAULT 0"),
        ),
    )
    _sumar_columnas(
        db,
        "ordenes",
        (
            ("subtotal", "REAL"),
            ("recargo_porcentaje_aplicado", "REAL"),
            ("recargo_fijo_aplicado", "REAL"),
            ("recargo_total", "REAL"),
            ("cupon_id", "INTEGER"),
            ("descuento", "REAL"),
            # Último estado informado por Mercado Pago (approved, pending, rejected…),
            # su detalle, y el link al cupón de pago si eligió efectivo.
            ("mp_estado", "TEXT"),
            ("mp_estado_detalle", "TEXT"),
            ("mp_ticket_url", "TEXT"),
            # Código secreto de la orden para sus links públicos (pago, confirmación):
            # con el id numérico cualquiera podía ver las entradas de otro cambiando
            # el número en la URL.
            ("codigo", "TEXT"),
            # Con qué cuenta se cobró: 'centralizado' (la de la plataforma) u
            # 'organizador' (la del organizador). Hace falta para consultar el pago
            # con el token correcto aunque después se cambie el modo de cobro.
            ("cobro_modo", "TEXT"),
            # Lo que informa Mercado Pago al aprobar el pago: cuánto llegó neto a la
            # cuenta y cuánto se descontó (comisión + retenciones de impuestos). En
            # cobro centralizado esos costos se le descuentan al organizador.
            ("mp_neto", "REAL"),
            ("mp_comision", "REAL"),
            ("mp_impuestos", "REAL"),
            # Cuenta de comprador que hizo la compra (para "Mis entradas").
            ("comprador_id", "INTEGER"),
        ),
    )
    db.execute(
        "UPDATE ordenes SET codigo = lower(hex(randomblob(16))) WHERE codigo IS NULL"
    )
    db.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_ordenes_codigo ON ordenes (codigo)")

    db.execute(
        "INSERT OR IGNORE INTO configuracion (clave, valor) VALUES ('recargo_porcentaje', '10')"
    )
    db.execute("INSERT OR IGNORE INTO configuracion (clave, valor) VALUES ('recargo_fijo', '0')")
    db.execute(
        "INSERT OR IGNORE INTO configuracion (clave, valor) VALUES ('modo_cobro', 'centralizado')"
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
