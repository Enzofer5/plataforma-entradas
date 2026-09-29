from datetime import datetime

from flask import abort, flash, g, redirect, render_template, request, url_for

from ..auth.routes import login_required
from ..db import get_db, now_iso
from ..utils import slugify
from . import eventos_bp


def _evento_del_organizador_o_404(db, evento_id):
    evento = db.execute("SELECT * FROM eventos WHERE id = ?", (evento_id,)).fetchone()
    if evento is None:
        abort(404)
    if evento["organizador_id"] != g.organizador["id"]:
        abort(403)
    return evento


def _generar_slug_unico(db, nombre, evento_id=None):
    base = slugify(nombre)
    slug = base
    contador = 2
    while True:
        if evento_id:
            fila = db.execute(
                "SELECT id FROM eventos WHERE slug = ? AND id != ?", (slug, evento_id)
            ).fetchone()
        else:
            fila = db.execute("SELECT id FROM eventos WHERE slug = ?", (slug,)).fetchone()
        if not fila:
            return slug
        slug = f"{base}-{contador}"
        contador += 1


def _leer_formulario(form):
    fecha_raw = form.get("fecha", "").strip()
    hora_raw = form.get("hora", "").strip()

    if fecha_raw:
        try:
            datetime.strptime(fecha_raw, "%Y-%m-%d")
        except ValueError:
            fecha_raw = ""

    if hora_raw:
        try:
            datetime.strptime(hora_raw, "%H:%M")
        except ValueError:
            hora_raw = ""

    return {
        "nombre": form.get("nombre", "").strip(),
        "descripcion": form.get("descripcion", "").strip(),
        "fecha": fecha_raw,
        "hora": hora_raw,
        "lugar": form.get("lugar", "").strip(),
        "imagen_url": form.get("imagen_url", "").strip(),
    }


def _validar_formulario(datos):
    if not datos["nombre"]:
        return "El evento necesita un nombre."
    if not datos["fecha"]:
        return "Ingresá una fecha válida (AAAA-MM-DD)."
    if not datos["lugar"]:
        return "Ingresá el lugar del evento."
    return None


@eventos_bp.route("/eventos")
@login_required
def listado():
    db = get_db()
    eventos = db.execute(
        "SELECT * FROM eventos WHERE organizador_id = ? ORDER BY fecha DESC",
        (g.organizador["id"],),
    ).fetchall()
    return render_template("eventos/listado.html", eventos=eventos)


@eventos_bp.route("/eventos/nuevo", methods=["GET", "POST"])
@login_required
def nuevo():
    if request.method == "POST":
        datos = _leer_formulario(request.form)
        error = _validar_formulario(datos)
        if error:
            flash(error, "danger")
            return render_template("eventos/form.html", evento=None, datos=datos)

        db = get_db()
        slug = _generar_slug_unico(db, datos["nombre"])
        cursor = db.execute(
            """INSERT INTO eventos
               (organizador_id, nombre, slug, descripcion, fecha, hora, lugar, imagen_url, estado, creado_en)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'borrador', ?)""",
            (
                g.organizador["id"],
                datos["nombre"],
                slug,
                datos["descripcion"],
                datos["fecha"],
                datos["hora"] or None,
                datos["lugar"],
                datos["imagen_url"] or None,
                now_iso(),
            ),
        )
        db.commit()
        flash("Evento creado. Ahora agregá los tipos de entrada.", "success")
        return redirect(url_for("eventos.tipos_entrada", evento_id=cursor.lastrowid))

    return render_template("eventos/form.html", evento=None, datos=None)


@eventos_bp.route("/eventos/<int:evento_id>/editar", methods=["GET", "POST"])
@login_required
def editar(evento_id):
    db = get_db()
    evento = _evento_del_organizador_o_404(db, evento_id)

    if request.method == "POST":
        datos = _leer_formulario(request.form)
        error = _validar_formulario(datos)
        if error:
            flash(error, "danger")
            return render_template("eventos/form.html", evento=evento, datos=datos)

        slug = evento["slug"]
        if datos["nombre"] != evento["nombre"]:
            slug = _generar_slug_unico(db, datos["nombre"], evento_id=evento_id)

        db.execute(
            """UPDATE eventos SET nombre = ?, slug = ?, descripcion = ?, fecha = ?, hora = ?,
               lugar = ?, imagen_url = ? WHERE id = ?""",
            (
                datos["nombre"],
                slug,
                datos["descripcion"],
                datos["fecha"],
                datos["hora"] or None,
                datos["lugar"],
                datos["imagen_url"] or None,
                evento_id,
            ),
        )
        db.commit()
        flash("Evento actualizado.", "success")
        return redirect(url_for("eventos.listado"))

    return render_template("eventos/form.html", evento=evento, datos=None)


@eventos_bp.route("/eventos/<int:evento_id>/publicar", methods=["POST"])
@login_required
def publicar(evento_id):
    db = get_db()
    evento = _evento_del_organizador_o_404(db, evento_id)

    if evento["estado"] == "publicado":
        db.execute("UPDATE eventos SET estado = 'borrador' WHERE id = ?", (evento_id,))
        db.commit()
        flash("Evento pasado a borrador (ya no es visible al público).", "info")
    else:
        tiene_tipos = db.execute(
            "SELECT id FROM tipos_entrada WHERE evento_id = ? LIMIT 1", (evento_id,)
        ).fetchone()
        if not tiene_tipos:
            flash("Agregá al menos un tipo de entrada antes de publicar.", "warning")
            return redirect(url_for("eventos.tipos_entrada", evento_id=evento_id))

        tiene_pagas = db.execute(
            "SELECT id FROM tipos_entrada WHERE evento_id = ? AND precio > 0 LIMIT 1",
            (evento_id,),
        ).fetchone()
        if tiene_pagas and not g.organizador["mp_access_token"]:
            flash(
                "Conectá tu cuenta de Mercado Pago antes de publicar un evento con "
                "entradas pagas — así la plata te llega directo a vos.",
                "warning",
            )
            return redirect(url_for("auth.cuenta"))

        db.execute("UPDATE eventos SET estado = 'publicado' WHERE id = ?", (evento_id,))
        db.commit()
        flash("¡Evento publicado! Ya es visible en la página pública.", "success")

    return redirect(url_for("eventos.listado"))


@eventos_bp.route("/eventos/<int:evento_id>/tipos-entrada", methods=["GET", "POST"])
@login_required
def tipos_entrada(evento_id):
    db = get_db()
    evento = _evento_del_organizador_o_404(db, evento_id)

    if request.method == "POST":
        nombre = request.form.get("nombre", "").strip()
        precio_raw = request.form.get("precio", "").strip()
        stock_raw = request.form.get("stock", "").strip()

        error = None
        precio_val = stock_val = None
        if not nombre:
            error = "El tipo de entrada necesita un nombre."
        else:
            try:
                precio_val = float(precio_raw)
                stock_val = int(stock_raw)
                if precio_val < 0 or stock_val < 1:
                    raise ValueError
            except ValueError:
                error = "Precio y stock tienen que ser números válidos (stock mínimo 1)."

        if error:
            flash(error, "danger")
        else:
            db.execute(
                """INSERT INTO tipos_entrada (evento_id, nombre, precio, stock_total, stock_vendido)
                   VALUES (?, ?, ?, ?, 0)""",
                (evento_id, nombre, precio_val, stock_val),
            )
            db.commit()
            flash("Tipo de entrada agregado.", "success")

        return redirect(url_for("eventos.tipos_entrada", evento_id=evento_id))

    tipos = db.execute(
        "SELECT * FROM tipos_entrada WHERE evento_id = ? ORDER BY id", (evento_id,)
    ).fetchall()
    return render_template("eventos/tipos_entrada.html", evento=evento, tipos=tipos)


@eventos_bp.route(
    "/eventos/<int:evento_id>/tipos-entrada/<int:tipo_id>/eliminar", methods=["POST"]
)
@login_required
def eliminar_tipo_entrada(evento_id, tipo_id):
    db = get_db()
    _evento_del_organizador_o_404(db, evento_id)

    tipo = db.execute(
        "SELECT * FROM tipos_entrada WHERE id = ? AND evento_id = ?", (tipo_id, evento_id)
    ).fetchone()
    if tipo is None:
        abort(404)

    if tipo["stock_vendido"] > 0:
        flash("No se puede eliminar un tipo de entrada que ya tiene ventas.", "danger")
    else:
        db.execute("DELETE FROM tipos_entrada WHERE id = ?", (tipo_id,))
        db.commit()
        flash("Tipo de entrada eliminado.", "info")

    return redirect(url_for("eventos.tipos_entrada", evento_id=evento_id))


@eventos_bp.route("/eventos/<int:evento_id>/validar", methods=["GET", "POST"])
@login_required
def validar(evento_id):
    db = get_db()
    evento = _evento_del_organizador_o_404(db, evento_id)

    resultado = None
    if request.method == "POST":
        codigo = request.form.get("codigo", "").strip()
        entrada = db.execute(
            """SELECT entradas.*, tipos_entrada.nombre AS tipo_nombre, tipos_entrada.evento_id
               FROM entradas
               JOIN tipos_entrada ON tipos_entrada.id = entradas.tipo_entrada_id
               WHERE entradas.codigo_unico = ?""",
            (codigo,),
        ).fetchone()

        if not codigo:
            resultado = {"ok": False, "mensaje": "Ingresá o escaneá un código."}
        elif entrada is None or entrada["evento_id"] != evento_id:
            resultado = {"ok": False, "mensaje": "Ese código no corresponde a este evento."}
        elif entrada["estado"] == "usada":
            resultado = {
                "ok": False,
                "mensaje": "Esta entrada ya fue validada antes.",
                "tipo_nombre": entrada["tipo_nombre"],
            }
        else:
            db.execute(
                "UPDATE entradas SET estado = 'usada', usada_en = ? WHERE id = ?",
                (now_iso(), entrada["id"]),
            )
            db.commit()
            resultado = {
                "ok": True,
                "mensaje": "¡Entrada válida! Acceso permitido.",
                "tipo_nombre": entrada["tipo_nombre"],
            }

    stats = db.execute(
        """SELECT
             COUNT(*) AS total,
             SUM(CASE WHEN entradas.estado = 'usada' THEN 1 ELSE 0 END) AS usadas
           FROM entradas
           JOIN tipos_entrada ON tipos_entrada.id = entradas.tipo_entrada_id
           WHERE tipos_entrada.evento_id = ?""",
        (evento_id,),
    ).fetchone()

    return render_template(
        "eventos/validar.html", evento=evento, resultado=resultado, stats=stats
    )
