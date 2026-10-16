import secrets
from functools import wraps

from flask import current_app, flash, g, redirect, render_template, request, session, url_for
from werkzeug.security import check_password_hash, generate_password_hash

from ..configuracion import obtener_modo_cobro
from ..db import get_db, now_iso
from ..liquidaciones import saldo_de, ventas_de
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


# Endpoints que el dueño SÍ puede usar mientras mira el panel de un organizador
# (todo lo demás que no sea GET queda bloqueado: el modo vista es solo lectura).
_BLOQUEADOS_EN_VISTA = {"auth.mercadopago_conectar", "auth.mercadopago_callback"}


@auth_bp.before_app_request
def cargar_organizador():
    g.viendo_como_dueno = False
    # Modo vista: el dueño (sesión de admin) mira el panel de un organizador.
    ver_id = session.get("ver_organizador_id")
    if ver_id is not None:
        db = get_db()
        admin_id = session.get("admin_id")
        es_dueno = admin_id is not None and db.execute(
            "SELECT 1 FROM administradores WHERE id = ?", (admin_id,)
        ).fetchone()
        organizador = db.execute("SELECT * FROM organizadores WHERE id = ?", (ver_id,)).fetchone()
        if es_dueno and organizador is not None:
            g.organizador = organizador
            g.viendo_como_dueno = True
            bp = (request.blueprint or "")
            if bp in ("eventos", "auth", "pagos") and (
                request.method != "GET" or request.endpoint in _BLOQUEADOS_EN_VISTA
            ) and request.endpoint != "auth.logout":
                flash("Estás mirando el panel como dueño: es solo lectura. "
                      "Los cambios los hace el organizador desde su cuenta.", "warning")
                return redirect(request.referrer or url_for("eventos.panel"))
            return None
        session.pop("ver_organizador_id", None)

    organizador_id = session.get("organizador_id")
    if organizador_id is None:
        g.organizador = None
    else:
        g.organizador = (
            get_db()
            .execute("SELECT * FROM organizadores WHERE id = ?", (organizador_id,))
            .fetchone()
        )
        # Si el dueño de la plataforma suspendió la cuenta, se cierra la sesión.
        if g.organizador is not None and g.organizador["suspendido"]:
            session.pop("organizador_id", None)
            g.organizador = None


def _entrar_como_organizador(organizador_id):
    """Inicia la sesión de organizador cerrando la de dueño, si había una: en un mismo
    navegador se es dueño u organizador, nunca las dos cosas a la vez."""
    if session.pop("admin_id", None) is not None:
        flash("Cerramos tu sesión de dueño para entrar como organizador.", "info")
    session.pop("comprador_id", None)
    session.pop("ver_organizador_id", None)
    session.pop("mp_oauth_state", None)
    session["organizador_id"] = organizador_id


@auth_bp.route("/registro", methods=["GET", "POST"])
def registro():
    if g.organizador:
        return redirect(url_for("eventos.panel"))

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
        _entrar_como_organizador(cursor.lastrowid)
        flash("¡Cuenta creada! Ya podés crear tu primer evento.", "success")
        return redirect(url_for("eventos.panel"))

    return render_template("auth/registro.html")


@auth_bp.route("/login", methods=["GET", "POST"])
def login():
    if g.organizador:
        return redirect(url_for("eventos.panel"))
    if getattr(g, "comprador", None):
        return redirect(url_for("cuentas.mis_entradas"))

    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")

        organizador = get_db().execute(
            "SELECT * FROM organizadores WHERE email = ?", (email,)
        ).fetchone()

        if organizador and check_password_hash(organizador["password_hash"], password):
            if organizador["suspendido"]:
                flash(
                    "Tu cuenta está suspendida. Escribinos para saber más.", "danger"
                )
                return render_template("auth/login.html", email=email)
            _entrar_como_organizador(organizador["id"])
            # Solo direcciones internas del sitio (no "//otro-sitio.com" ni "https://...").
            next_url = request.args.get("next", "")
            if not next_url.startswith("/") or next_url.startswith("//") or "\\" in next_url:
                next_url = url_for("eventos.panel")
            return redirect(next_url)

        # Una sola pantalla de "Iniciar sesión": si el email y la contraseña son los de
        # la cuenta de dueño, entra al panel del dueño.
        dueno = get_db().execute(
            "SELECT * FROM administradores WHERE email = ?", (email,)
        ).fetchone()
        if dueno and check_password_hash(dueno["password_hash"], password):
            from ..admin.routes import _entrar_como_dueno

            _entrar_como_dueno(dueno["id"])
            return redirect(url_for("admin.resumen"))

        # Compradores: ven sus entradas y siguen con la compra si venían de una.
        comprador = get_db().execute(
            "SELECT * FROM compradores WHERE email = ?", (email,)
        ).fetchone()
        if comprador and check_password_hash(comprador["password_hash"], password):
            from ..cuentas.routes import entrar_como_comprador, url_interna

            entrar_como_comprador(comprador["id"])
            return redirect(url_interna(request.args.get("next"), url_for("cuentas.mis_entradas")))

        flash("Email o contraseña incorrectos.", "danger")
        return render_template("auth/login.html", email=email)

    return render_template("auth/login.html")


@auth_bp.route("/logout")
def logout():
    # Solo cierra la sesión de organizador (si también hay una de dueño, sigue abierta).
    session.pop("organizador_id", None)
    session.pop("mp_oauth_state", None)
    flash("Sesión cerrada.", "info")
    return redirect(url_for("public.inicio"))


def _redirect_uri_mp():
    return f"{current_app.config['BASE_URL']}/organizador/mercadopago/callback"


@auth_bp.route("/cuenta")
@login_required
def cuenta():
    db = get_db()
    transferencias = db.execute(
        """SELECT *, datetime(creado_en, '-3 hours') AS fecha_local FROM liquidaciones
           WHERE organizador_id = ? ORDER BY creado_en DESC""",
        (g.organizador["id"],),
    ).fetchall()
    return render_template(
        "auth/cuenta.html",
        modo_cobro=obtener_modo_cobro(db),
        saldo=saldo_de(db, g.organizador["id"]),
        ventas=ventas_de(db, g.organizador["id"]),
        transferencias=transferencias,
    )


@auth_bp.route("/cuenta/datos-cobro", methods=["POST"])
@login_required
def guardar_datos_cobro():
    datos = request.form.get("datos_cobro", "").strip()[:300]
    db = get_db()
    db.execute(
        "UPDATE organizadores SET datos_cobro = ? WHERE id = ?",
        (datos or None, g.organizador["id"]),
    )
    db.commit()
    flash("Datos para recibir tus pagos guardados.", "success")
    return redirect(url_for("auth.cuenta"))


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
           SET mp_user_id = ?, mp_access_token = ?, mp_refresh_token = ?, mp_public_key = ?
           WHERE id = ?""",
        (
            str(datos.get("user_id", "")),
            datos.get("access_token"),
            datos.get("refresh_token"),
            datos.get("public_key"),
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
           SET mp_user_id = NULL, mp_access_token = NULL, mp_refresh_token = NULL,
               mp_public_key = NULL
           WHERE id = ?""",
        (g.organizador["id"],),
    )
    db.commit()
    flash("Desconectaste tu cuenta de Mercado Pago.", "info")
    return redirect(url_for("auth.cuenta"))
