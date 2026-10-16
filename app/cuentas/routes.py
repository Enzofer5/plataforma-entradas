"""Cuentas de compradores: registro, "Mis entradas" y salir. El ingreso es por la
misma pantalla de "Iniciar sesión" que usan los productores y el dueño."""

from functools import wraps

from flask import flash, g, redirect, render_template, request, session, url_for
from werkzeug.security import generate_password_hash

from ..db import get_db, now_iso
from . import cuentas_bp


def url_interna(destino, defecto):
    """Solo direcciones del propio sitio (no '//otro-sitio' ni 'https://...')."""
    if destino and destino.startswith("/") and not destino.startswith("//") and "\\" not in destino:
        return destino
    return defecto


def entrar_como_comprador(comprador_id):
    """Una sola identidad por navegador: al entrar como comprador se cierran las otras."""
    session.pop("organizador_id", None)
    session.pop("admin_id", None)
    session.pop("ver_organizador_id", None)
    session["comprador_id"] = comprador_id


def comprador_requerido(view):
    @wraps(view)
    def envoltura(**kwargs):
        if g.comprador is None:
            flash("Para comprar entradas necesitás una cuenta: creala en un minuto o iniciá sesión.", "info")
            return redirect(url_for("cuentas.registro", next=request.path))
        return view(**kwargs)
    return envoltura


@cuentas_bp.before_app_request
def cargar_comprador():
    g.comprador = None
    comprador_id = session.get("comprador_id")
    if comprador_id is not None:
        g.comprador = get_db().execute(
            "SELECT * FROM compradores WHERE id = ?", (comprador_id,)
        ).fetchone()
        if g.comprador is None:
            session.pop("comprador_id", None)


@cuentas_bp.route("/registro", methods=["GET", "POST"])
def registro():
    destino = url_interna(request.args.get("next"), url_for("cuentas.mis_entradas"))
    if g.comprador:
        return redirect(destino)
    datos = {"nombre": "", "email": "", "dni": "", "telefono": ""}
    if request.method == "POST":
        datos = {k: request.form.get(k, "").strip() for k in datos}
        datos["email"] = datos["email"].lower()
        password = request.form.get("password", "")
        password_confirm = request.form.get("password_confirm", "")
        db = get_db()
        error = None
        if not datos["nombre"] or "@" not in datos["email"]:
            error = "Completá tu nombre y un email válido."
        elif datos["dni"] and not datos["dni"].replace(".", "").isdigit():
            error = "El DNI tiene que tener solo números."
        elif len(password) < 8:
            error = "La contraseña tiene que tener al menos 8 caracteres."
        elif password != password_confirm:
            error = "Las contraseñas no coinciden."
        elif any(
            db.execute(f"SELECT 1 FROM {tabla} WHERE email = ?", (datos["email"],)).fetchone()
            for tabla in ("compradores", "organizadores", "administradores")
        ):
            error = "Ya existe una cuenta con ese email. Iniciá sesión."
        if error:
            flash(error, "danger")
        else:
            cursor = db.execute(
                """INSERT INTO compradores (nombre, email, dni, telefono, password_hash, creado_en)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (datos["nombre"], datos["email"], datos["dni"].replace(".", "") or None,
                 datos["telefono"] or None, generate_password_hash(password), now_iso()),
            )
            db.commit()
            entrar_como_comprador(cursor.lastrowid)
            flash(f"¡Bienvenido/a, {datos['nombre'].split()[0]}! Tu cuenta quedó creada.", "success")
            return redirect(destino)
    return render_template("cuentas/registro.html", next=request.args.get("next", ""), **datos)


@cuentas_bp.route("/entradas")
def mis_entradas():
    if g.comprador is None:
        return redirect(url_for("auth.login", next=request.path))
    db = get_db()
    ordenes = db.execute(
        """SELECT ordenes.*, eventos.nombre AS evento_nombre, eventos.fecha AS evento_fecha,
                  eventos.hora AS evento_hora, eventos.lugar AS evento_lugar,
                  eventos.imagen_url AS evento_imagen, eventos.slug AS evento_slug
           FROM ordenes JOIN eventos ON eventos.id = ordenes.evento_id
           WHERE ordenes.comprador_id = ? AND ordenes.estado IN ('pagada', 'pendiente')
           ORDER BY ordenes.creado_en DESC""",
        (g.comprador["id"],),
    ).fetchall()
    entradas = {}
    for o in ordenes:
        entradas[o["id"]] = db.execute(
            """SELECT entradas.*, tipos_entrada.nombre AS tipo_nombre
               FROM entradas JOIN tipos_entrada ON tipos_entrada.id = entradas.tipo_entrada_id
               WHERE entradas.orden_id = ? ORDER BY entradas.id""",
            (o["id"],),
        ).fetchall()
    return render_template("cuentas/mis_entradas.html", ordenes=ordenes, entradas=entradas)


@cuentas_bp.route("/salir")
def salir():
    session.pop("comprador_id", None)
    flash("Cerraste sesión.", "info")
    return redirect(url_for("public.inicio"))
