import secrets
from functools import wraps

from flask import current_app, flash, g, redirect, render_template, request, session, url_for
from werkzeug.security import check_password_hash, generate_password_hash

from ..db import get_db, now_iso
from ..pagos.mercadopago_client import MercadoPagoError
from ..pagos.oauth import intercambiar_codigo, url_autorizacion
from . import auth_bp


def login_required(view):
    @wraps(view)
    def wrapped_view(**kwargs):
        if g.organizador is None:
            return redirect(url_for("auth.login", next=request.path))
        return view(**kwargs)

    return wrapped_view


@auth_bp.before_app_request
def cargar_organizador():
    organizador_id = session.get("organizador_id")
    if organizador_id is None:
        g.organizador = None
    else:
        g.organizador = (
            get_db()
            .execute("SELECT * FROM organizadores WHERE id = ?", (organizador_id,))
            .fetchone()
        )


@auth_bp.route("/registro", methods=["GET", "POST"])
def registro():
    if g.organizador:
        return redirect(url_for("eventos.listado"))

    if request.method == "POST":
        nombre = request.form.get("nombre", "").strip()
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        password_confirm = request.form.get("password_confirm", "")

        db = get_db()
        error = None
        if not nombre or not email or not password:
            error = "Completá todos los campos."
        elif password != password_confirm:
            error = "Las contraseñas no coinciden."
        elif len(password) < 6:
            error = "La contraseña debe tener al menos 6 caracteres."
        elif db.execute("SELECT id FROM organizadores WHERE email = ?", (email,)).fetchone():
            error = "Ya existe una cuenta con ese email."

        if error:
            flash(error, "danger")
            return render_template("auth/registro.html", nombre=nombre, email=email)

        cursor = db.execute(
            "INSERT INTO organizadores (nombre, email, password_hash, creado_en) VALUES (?, ?, ?, ?)",
            (nombre, email, generate_password_hash(password), now_iso()),
        )
        db.commit()
        session.clear()
        session["organizador_id"] = cursor.lastrowid
        flash("¡Cuenta creada! Ya podés crear tu primer evento.", "success")
        return redirect(url_for("eventos.listado"))

    return render_template("auth/registro.html")


@auth_bp.route("/login", methods=["GET", "POST"])
def login():
    if g.organizador:
        return redirect(url_for("eventos.listado"))

    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")

        organizador = get_db().execute(
            "SELECT * FROM organizadores WHERE email = ?", (email,)
        ).fetchone()

        if organizador and check_password_hash(organizador["password_hash"], password):
            session.clear()
            session["organizador_id"] = organizador["id"]
            next_url = request.args.get("next")
            return redirect(next_url or url_for("eventos.listado"))

        flash("Email o contraseña incorrectos.", "danger")
        return render_template("auth/login.html", email=email)

    return render_template("auth/login.html")


@auth_bp.route("/logout")
def logout():
    session.clear()
    flash("Sesión cerrada.", "info")
    return redirect(url_for("public.inicio"))


def _redirect_uri_mp():
    return f"{current_app.config['BASE_URL']}/organizador/mercadopago/callback"


@auth_bp.route("/cuenta")
@login_required
def cuenta():
    return render_template("auth/cuenta.html")


@auth_bp.route("/mercadopago/conectar")
@login_required
def mp_conectar():
    client_id = current_app.config.get("MP_CLIENT_ID")
    if not client_id:
        flash(
            "Todavía no está configurado MP_CLIENT_ID en el servidor — avisale al "
            "administrador.",
            "danger",
        )
        return redirect(url_for("auth.cuenta"))

    state = secrets.token_urlsafe(16)
    session["mp_oauth_state"] = state
    return redirect(url_autorizacion(client_id, _redirect_uri_mp(), state))


@auth_bp.route("/mercadopago/callback")
@login_required
def mp_callback():
    state_esperado = session.pop("mp_oauth_state", None)
    state_recibido = request.args.get("state")
    if not state_recibido or state_recibido != state_esperado:
        flash(
            "No se pudo validar la conexión con Mercado Pago — probá de nuevo.",
            "danger",
        )
        return redirect(url_for("auth.cuenta"))

    code = request.args.get("code")
    if not code:
        flash("Mercado Pago no autorizó la conexión.", "warning")
        return redirect(url_for("auth.cuenta"))

    try:
        datos = intercambiar_codigo(
            current_app.config["MP_CLIENT_ID"],
            current_app.config["MP_CLIENT_SECRET"],
            code,
            _redirect_uri_mp(),
        )
    except MercadoPagoError as exc:
        flash(f"No se pudo conectar con Mercado Pago: {exc}", "danger")
        return redirect(url_for("auth.cuenta"))

    db = get_db()
    db.execute(
        """UPDATE organizadores
           SET mp_user_id = ?, mp_access_token = ?, mp_refresh_token = ?
           WHERE id = ?""",
        (
            str(datos.get("user_id", "")),
            datos.get("access_token"),
            datos.get("refresh_token"),
            g.organizador["id"],
        ),
    )
    db.commit()
    flash("¡Cuenta de Mercado Pago conectada! Ya podés publicar eventos pagos.", "success")
    return redirect(url_for("auth.cuenta"))


@auth_bp.route("/mercadopago/desconectar", methods=["POST"])
@login_required
def mp_desconectar():
    db = get_db()
    db.execute(
        """UPDATE organizadores
           SET mp_user_id = NULL, mp_access_token = NULL, mp_refresh_token = NULL
           WHERE id = ?""",
        (g.organizador["id"],),
    )
    db.commit()
    flash("Desconectaste tu cuenta de Mercado Pago.", "info")
    return redirect(url_for("auth.cuenta"))
