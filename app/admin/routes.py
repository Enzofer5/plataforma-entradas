from functools import wraps

from flask import abort, current_app, flash, g, redirect, render_template, request, url_for

from ..auth.routes import login_required
from ..configuracion import actualizar_recargo_porcentaje, obtener_recargo_porcentaje
from ..db import get_db
from . import admin_bp


def admin_required(view):
    @wraps(view)
    def wrapped_view(**kwargs):
        email_admin = current_app.config.get("ADMIN_EMAIL")
        if not email_admin or not g.organizador or g.organizador["email"] != email_admin:
            abort(403)
        return view(**kwargs)

    return wrapped_view


@admin_bp.route("/configuracion", methods=["GET", "POST"])
@login_required
@admin_required
def configuracion():
    db = get_db()

    if request.method == "POST":
        raw = request.form.get("recargo_porcentaje", "").strip()
        try:
            valor = float(raw)
            if valor < 0 or valor > 100:
                raise ValueError
        except ValueError:
            flash("Ingresá un porcentaje válido, entre 0 y 100.", "danger")
            return redirect(url_for("admin.configuracion"))

        actualizar_recargo_porcentaje(db, valor)
        flash("Recargo actualizado.", "success")
        return redirect(url_for("admin.configuracion"))

    recargo_actual = obtener_recargo_porcentaje(db)
    return render_template("admin/configuracion.html", recargo_actual=recargo_actual)
