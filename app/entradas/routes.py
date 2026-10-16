import io

from flask import abort, render_template, send_file

from ..db import get_db
from ..utils import generar_qr_png_bytes
from . import entradas_bp


def _obtener_entrada_o_404(db, codigo):
    entrada = db.execute(
        """SELECT entradas.*, tipos_entrada.nombre AS tipo_nombre, tipos_entrada.evento_id
           FROM entradas
           JOIN tipos_entrada ON tipos_entrada.id = entradas.tipo_entrada_id
           WHERE entradas.codigo_unico = ?""",
        (codigo,),
    ).fetchone()
    if entrada is None:
        abort(404)
    return entrada


@entradas_bp.route("/entrada/<codigo>")
def ver_entrada(codigo):
    db = get_db()
    entrada = _obtener_entrada_o_404(db, codigo)
    evento = db.execute(
        "SELECT * FROM eventos WHERE id = ?", (entrada["evento_id"],)
    ).fetchone()
    orden = db.execute(
        "SELECT * FROM ordenes WHERE id = ?", (entrada["orden_id"],)
    ).fetchone()
    return render_template("entradas/ver.html", entrada=entrada, evento=evento, orden=orden)


@entradas_bp.route("/entrada/<codigo>/qr.png")
def qr_entrada(codigo):
    db = get_db()
    _obtener_entrada_o_404(db, codigo)  # solo para devolver 404 si el código no existe

    png_bytes = generar_qr_png_bytes(codigo)
    return send_file(io.BytesIO(png_bytes), mimetype="image/png")
