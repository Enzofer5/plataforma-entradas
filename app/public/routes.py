from datetime import date, datetime

from flask import abort, render_template

from ..configuracion import obtener_modo_cobro, obtener_recargo_global
from ..db import get_db
from . import public_bp


def _dias_para(fecha):
    """Días que faltan para la fecha (AAAA-MM-DD); None si no se puede leer."""
    try:
        return (datetime.strptime(fecha, "%Y-%m-%d").date() - date.today()).days
    except (TypeError, ValueError):
        return None


@public_bp.route("/")
def inicio():
    db = get_db()
    eventos = db.execute(
        """SELECT eventos.*, organizadores.nombre AS organizador_nombre,
                  (SELECT MIN(precio) FROM tipos_entrada
                   WHERE tipos_entrada.evento_id = eventos.id) AS precio_desde,
                  (SELECT SUM(stock_total - stock_vendido) FROM tipos_entrada
                   WHERE tipos_entrada.evento_id = eventos.id) AS disponibles
           FROM eventos JOIN organizadores ON organizadores.id = eventos.organizador_id
           WHERE estado = 'publicado' AND bloqueado = 0 AND organizadores.suspendido = 0
           ORDER BY fecha ASC"""
    ).fetchall()

    # Destacados arriba de todo: los próximos eventos (hasta 5), con los que tienen
    # imagen primero. Si no hay ninguno a futuro, se destacan los que haya.
    hoy = date.today().isoformat()
    proximos = [e for e in eventos if e["fecha"] >= hoy] or list(eventos)
    destacados = sorted(proximos, key=lambda e: (not e["imagen_url"], e["fecha"]))[:5]

    return render_template(
        "public/inicio.html", eventos=eventos, destacados=destacados, dias_para=_dias_para
    )


@public_bp.route("/organizadores")
def organizadores():
    """Página para productores: qué ofrece la plataforma y cómo empezar."""
    db = get_db()
    return render_template(
        "public/organizadores.html",
        recargo=obtener_recargo_global(db),
        modo_cobro=obtener_modo_cobro(db),
    )


@public_bp.route("/evento/<slug>")
def evento_detalle(slug):
    db = get_db()
    evento = db.execute(
        """SELECT eventos.*, organizadores.nombre AS organizador_nombre,
                  organizadores.suspendido AS organizador_suspendido
           FROM eventos JOIN organizadores ON organizadores.id = eventos.organizador_id
           WHERE slug = ?""",
        (slug,),
    ).fetchone()
    if (
        evento is None
        or evento["estado"] != "publicado"
        or evento["bloqueado"]
        or evento["organizador_suspendido"]
    ):
        abort(404)
    tipos = db.execute(
        "SELECT * FROM tipos_entrada WHERE evento_id = ? ORDER BY id", (evento["id"],)
    ).fetchall()
    otros = db.execute(
        """SELECT eventos.*,
                  (SELECT MIN(precio) FROM tipos_entrada
                   WHERE tipos_entrada.evento_id = eventos.id) AS precio_desde
           FROM eventos JOIN organizadores ON organizadores.id = eventos.organizador_id
           WHERE estado = 'publicado' AND bloqueado = 0 AND organizadores.suspendido = 0
             AND eventos.id != ? AND fecha >= ?
           ORDER BY fecha ASC LIMIT 3""",
        (evento["id"], date.today().isoformat()),
    ).fetchall()
    return render_template(
        "public/evento_detalle.html",
        evento=evento,
        tipos=tipos,
        otros=otros,
        dias=_dias_para(evento["fecha"]),
    )
