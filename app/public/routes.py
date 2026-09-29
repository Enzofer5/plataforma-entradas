from flask import abort, render_template

from ..db import get_db
from . import public_bp


@public_bp.route("/")
def inicio():
    db = get_db()
    eventos = db.execute(
        "SELECT * FROM eventos WHERE estado = 'publicado' ORDER BY fecha ASC"
    ).fetchall()
    return render_template("public/inicio.html", eventos=eventos)


@public_bp.route("/evento/<slug>")
def evento_detalle(slug):
    db = get_db()
    evento = db.execute("SELECT * FROM eventos WHERE slug = ?", (slug,)).fetchone()
    if evento is None or evento["estado"] != "publicado":
        abort(404)
    tipos = db.execute(
        "SELECT * FROM tipos_entrada WHERE evento_id = ? ORDER BY id", (evento["id"],)
    ).fetchall()
    return render_template("public/evento_detalle.html", evento=evento, tipos=tipos)
