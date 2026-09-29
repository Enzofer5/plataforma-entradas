"""Configuración de la plataforma guardada en la base (no en archivos), para poder
cambiarla desde una pantalla sin tocar código ni reiniciar el servidor."""

RECARGO_PORCENTAJE_DEFAULT = 10.0


def obtener_recargo_porcentaje(db):
    fila = db.execute(
        "SELECT valor FROM configuracion WHERE clave = 'recargo_porcentaje'"
    ).fetchone()
    if fila is None:
        return RECARGO_PORCENTAJE_DEFAULT
    try:
        return float(fila["valor"])
    except (TypeError, ValueError):
        return RECARGO_PORCENTAJE_DEFAULT


def actualizar_recargo_porcentaje(db, porcentaje):
    db.execute(
        """INSERT INTO configuracion (clave, valor) VALUES ('recargo_porcentaje', ?)
           ON CONFLICT(clave) DO UPDATE SET valor = excluded.valor""",
        (str(porcentaje),),
    )
    db.commit()
