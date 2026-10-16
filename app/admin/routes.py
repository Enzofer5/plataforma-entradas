"""Panel del dueño de la plataforma (/admin). Tiene su propio inicio de sesión,
separado del de los organizadores, y una ÚNICA cuenta de dueño: se crea desde la web
la primera vez que se entra a /admin, y después ese alta queda deshabilitada.

Si el dueño se olvida la contraseña, se la cambia desde la consola:

    flask --app run recuperar-dueno
"""

from functools import wraps

import click
from flask import (
    abort,
    current_app,
    flash,
    g,
    redirect,
    render_template,
    request,
    session,
    url_for,
)
from werkzeug.security import check_password_hash, generate_password_hash

from ..configuracion import (
    actualizar_modo_cobro,
    actualizar_recargo_global,
    describir_recargo,
    obtener_modo_cobro,
    obtener_recargo_global,
)
from ..correo import enviar_mail_de_prueba, smtp_configurado
from ..db import get_db, now_iso
from ..liquidaciones import saldos
from ..utils import hoy_argentina, rango_fechas, serie_por_dia
from . import admin_bp

# Fechas guardadas en UTC; para agrupar por mes se pasan a hora de Argentina.
_MES_LOCAL = "strftime('%Y-%m', ordenes.creado_en, '-3 hours')"


@admin_bp.before_app_request
def cargar_admin():
    admin_id = session.get("admin_id")
    g.admin = None
    if admin_id is not None:
        g.admin = get_db().execute(
            "SELECT * FROM administradores WHERE id = ?", (admin_id,)
        ).fetchone()
        # Una sola identidad por navegador: si quedó también una sesión de organizador
        # (de antes de este cambio), se cierra.
        if g.admin is not None:
            session.pop("organizador_id", None)


@admin_bp.app_context_processor
def menu_del_dueno():
    """Datos del menú único del dueño: lista de productores y cuál está mirando."""
    if getattr(g, "admin", None) is None:
        return {}
    orgs = get_db().execute("SELECT id, nombre FROM organizadores ORDER BY nombre").fetchall()
    actual = session.get("ver_organizador_id") or (orgs[0]["id"] if orgs else None)
    return {"menu_orgs": orgs, "menu_org_actual": actual}


def _entrar_como_dueno(admin_id):
    """Inicia la sesión de dueño cerrando la de organizador, si había una: en un mismo
    navegador se es dueño u organizador, nunca las dos cosas a la vez."""
    if session.pop("organizador_id", None) is not None:
        flash("Cerramos tu sesión de organizador para entrar como dueño.", "info")
    session.pop("mp_oauth_state", None)
    session.pop("comprador_id", None)
    session["admin_id"] = admin_id


def admin_required(view):
    @wraps(view)
    def wrapped_view(**kwargs):
        if g.admin is None:
            return redirect(url_for("admin.login", next=request.path))
        return view(**kwargs)

    return wrapped_view


def _numero_opcional(raw, minimo=0, maximo=None):
    """'' -> None (usar el valor general); si no, un float validado. Lanza ValueError."""
    raw = (raw or "").strip().replace(",", ".")
    if raw == "":
        return None
    valor = float(raw)
    if valor < minimo or (maximo is not None and valor > maximo):
        raise ValueError
    return valor


# ------------------------------------------------------------------ Sesión


def _hay_dueno(db):
    return db.execute("SELECT 1 FROM administradores LIMIT 1").fetchone() is not None


def _validar_datos_dueno(nombre, email, password, password_confirm, password_obligatoria=True):
    if not nombre or not email or "@" not in email:
        return "Completá tu nombre y un email válido."
    if password or password_obligatoria:
        if len(password) < 8:
            return "La contraseña tiene que tener al menos 8 caracteres."
        if password != password_confirm:
            return "Las contraseñas no coinciden."
    return None


@admin_bp.route("/crear-cuenta", methods=["GET", "POST"])
def crear_cuenta():
    """Alta de la ÚNICA cuenta de dueño, desde la web. Solo está disponible mientras
    no exista ninguna: apenas se crea, esta página deja de funcionar para siempre."""
    db = get_db()
    if _hay_dueno(db):
        return redirect(url_for("admin.login"))

    if request.method == "POST":
        nombre = request.form.get("nombre", "").strip()
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        error = _validar_datos_dueno(
            nombre, email, password, request.form.get("password_confirm", "")
        )
        if error:
            flash(error, "danger")
            return render_template("admin/crear_cuenta.html", nombre=nombre, email=email)

        # El INSERT solo se hace si sigue sin haber dueño (por si dos personas mandan
        # el formulario al mismo tiempo, gana una sola).
        cursor = db.execute(
            """INSERT INTO administradores (nombre, email, password_hash, creado_en)
               SELECT ?, ?, ?, ? WHERE NOT EXISTS (SELECT 1 FROM administradores)""",
            (nombre, email, generate_password_hash(password), now_iso()),
        )
        db.commit()
        if cursor.rowcount != 1:
            flash("Ya existe una cuenta de dueño.", "warning")
            return redirect(url_for("admin.login"))

        _entrar_como_dueno(cursor.lastrowid)
        flash("¡Listo! Tu cuenta de dueño quedó creada. Es la única que puede entrar a este panel.", "success")
        return redirect(url_for("admin.resumen"))

    return render_template("admin/crear_cuenta.html", nombre="", email="")


@admin_bp.route("/login", methods=["GET", "POST"])
def login():
    if g.admin:
        return redirect(url_for("admin.resumen"))
    if not _hay_dueno(get_db()):
        return redirect(url_for("admin.crear_cuenta"))
    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        admin = get_db().execute(
            "SELECT * FROM administradores WHERE email = ?", (email,)
        ).fetchone()
        if admin and check_password_hash(admin["password_hash"], password):
            _entrar_como_dueno(admin["id"])
            destino = request.args.get("next", "")
            # Solo redirecciones internas al panel (nada de mandar a otro sitio).
            if not destino.startswith("/admin"):
                destino = url_for("admin.resumen")
            return redirect(destino)
        flash("Email o contraseña incorrectos.", "danger")
        return render_template("admin/login.html", email=email)
    return render_template("admin/login.html", email="")


@admin_bp.route("/logout")
def logout():
    session.pop("admin_id", None)
    flash("Cerraste la sesión del panel de dueño.", "info")
    return redirect(url_for("public.inicio"))


@admin_bp.route("/correo-prueba", methods=["POST"])
@admin_required
def correo_prueba():
    error = enviar_mail_de_prueba(current_app, g.admin["email"])
    if error:
        flash(error, "danger")
    else:
        flash(f"Mail de prueba enviado a {g.admin['email']}. Revisá tu bandeja (y la carpeta de spam).", "success")
    return redirect(url_for("admin.cuenta"))


@admin_bp.route("/cuenta", methods=["GET", "POST"])
@admin_required
def cuenta():
    """Cambiar nombre, email o contraseña del dueño (pide la contraseña actual)."""
    db = get_db()
    if request.method == "POST":
        nombre = request.form.get("nombre", "").strip()
        email = request.form.get("email", "").strip().lower()
        actual = request.form.get("password_actual", "")
        nueva = request.form.get("password", "")

        error = None
        if not check_password_hash(g.admin["password_hash"], actual):
            error = "La contraseña actual no es correcta."
        else:
            error = _validar_datos_dueno(
                nombre, email, nueva, request.form.get("password_confirm", ""),
                password_obligatoria=False,
            )
        if error:
            flash(error, "danger")
            return redirect(url_for("admin.cuenta"))

        password_hash = generate_password_hash(nueva) if nueva else g.admin["password_hash"]
        db.execute(
            "UPDATE administradores SET nombre = ?, email = ?, password_hash = ? WHERE id = ?",
            (nombre, email, password_hash, g.admin["id"]),
        )
        db.commit()
        flash("Datos actualizados.", "success")
        return redirect(url_for("admin.cuenta"))
    return render_template(
        "admin/cuenta.html",
        smtp_ok=smtp_configurado(current_app),
        smtp_usuario=current_app.config.get("SMTP_USER"),
    )


# ----------------------------------------------------------------- Resumen


_DIA = "date(ordenes.creado_en, '-3 hours')"
_ENTRADAS = "(SELECT SUM(cantidad) FROM orden_items WHERE orden_items.orden_id = ordenes.id)"


@admin_bp.route("/")
@admin_required
def resumen():
    """Panel de plataforma: comisiones (recargos cobrados) y ventas de todo el sitio,
    con filtro de fechas."""
    session.pop("ver_organizador_id", None)
    db = get_db()
    desde, hasta = rango_fechas(request.args)
    hoy = hoy_argentina().isoformat()

    def comisiones(condicion, params=()):
        return db.execute(
            f"SELECT COALESCE(SUM(recargo_total), 0) FROM ordenes WHERE estado = 'pagada' AND {condicion}",
            params,
        ).fetchone()[0]

    tarjetas = {
        "hoy": comisiones(f"{_DIA} = ?", (hoy,)),
        "mes": comisiones(f"strftime('%Y-%m', ordenes.creado_en, '-3 hours') = ?", (hoy[:7],)),
        # Solo compras pagadas: las reembolsadas no cuentan.
        "historicas": comisiones("1 = 1"),
    }
    periodo = db.execute(
        f"""SELECT COUNT(*) AS compras, COALESCE(SUM(total), 0) AS facturado,
                   COALESCE(SUM(recargo_total), 0) AS comisiones,
                   COALESCE(SUM({_ENTRADAS}), 0) AS entradas
            FROM ordenes WHERE estado = 'pagada' AND {_DIA} BETWEEN ? AND ?""",
        (desde, hasta),
    ).fetchone()
    eventos = db.execute(
        """SELECT COUNT(*) AS total,
                  COALESCE(SUM(CASE WHEN estado = 'publicado' AND bloqueado = 0 THEN 1 ELSE 0 END), 0) AS publicados
           FROM eventos"""
    ).fetchone()
    cuentas = db.execute(
        """SELECT COUNT(*) AS total, COALESCE(SUM(suspendido), 0) AS suspendidos
           FROM organizadores"""
    ).fetchone()
    por_dia = db.execute(
        f"""SELECT {_DIA} AS dia, SUM(COALESCE(recargo_total, 0)) AS comisiones
            FROM ordenes WHERE estado = 'pagada' AND {_DIA} BETWEEN ? AND ?
            GROUP BY dia""",
        (desde, hasta),
    ).fetchall()
    por_evento = db.execute(
        f"""SELECT eventos.id, eventos.nombre, eventos.fecha, eventos.estado, eventos.bloqueado,
                   eventos.slug, organizadores.nombre AS organizador,
                   COUNT(ordenes.id) AS compras, COALESCE(SUM({_ENTRADAS}), 0) AS entradas,
                   COALESCE(SUM(ordenes.total), 0) AS facturado,
                   COALESCE(SUM(ordenes.recargo_total), 0) AS comisiones
            FROM ordenes
            JOIN eventos ON eventos.id = ordenes.evento_id
            JOIN organizadores ON organizadores.id = eventos.organizador_id
            WHERE ordenes.estado = 'pagada' AND {_DIA} BETWEEN ? AND ?
            GROUP BY eventos.id ORDER BY comisiones DESC""",
        (desde, hasta),
    ).fetchall()
    ultimas = db.execute(
        """SELECT ordenes.*, eventos.nombre AS evento_nombre,
                  organizadores.nombre AS organizador_nombre,
                  datetime(ordenes.creado_en, '-3 hours') AS fecha_local
           FROM ordenes
           JOIN eventos ON eventos.id = ordenes.evento_id
           JOIN organizadores ON organizadores.id = eventos.organizador_id
           WHERE ordenes.estado = 'pagada'
           ORDER BY ordenes.creado_en DESC LIMIT 8"""
    ).fetchall()

    return render_template(
        "admin/resumen.html",
        desde=desde,
        hasta=hasta,
        tarjetas=tarjetas,
        periodo=periodo,
        eventos=eventos,
        cuentas=cuentas,
        serie=serie_por_dia(por_dia, desde, hasta, "comisiones"),
        por_evento=por_evento,
        ultimas=ultimas,
        recargo=obtener_recargo_global(db),
        modo_cobro=obtener_modo_cobro(db),
    )


# ----------------------------------------------------------------- Recargos


@admin_bp.route("/recargos", methods=["GET", "POST"])
@admin_required
def recargos():
    db = get_db()

    if request.method == "POST":
        accion = request.form.get("accion")
        try:
            porcentaje = _numero_opcional(request.form.get("porcentaje"), 0, 100)
            fijo = _numero_opcional(request.form.get("fijo"), 0)
        except ValueError:
            flash("Ingresá números válidos: porcentaje entre 0 y 100, monto fijo 0 o más.", "danger")
            return redirect(url_for("admin.recargos"))

        if accion == "general":
            actualizar_recargo_global(db, porcentaje or 0, fijo or 0)
            flash(
                f"Recargo general actualizado: {describir_recargo(porcentaje or 0, fijo or 0)}. "
                "Se aplica a las compras nuevas.",
                "success",
            )
        elif accion in ("organizador", "evento"):
            tabla = "organizadores" if accion == "organizador" else "eventos"
            try:
                objetivo_id = int(request.form.get("objetivo_id", ""))
            except ValueError:
                flash("Elegí a quién aplicarle el recargo especial.", "danger")
                return redirect(url_for("admin.recargos"))
            if porcentaje is None and fijo is None:
                flash("Completá al menos el porcentaje o el monto fijo.", "danger")
                return redirect(url_for("admin.recargos"))
            fila = db.execute(f"SELECT id FROM {tabla} WHERE id = ?", (objetivo_id,)).fetchone()
            if fila is None:
                abort(404)
            db.execute(
                f"UPDATE {tabla} SET recargo_porcentaje = ?, recargo_fijo = ? WHERE id = ?",
                (porcentaje, fijo, objetivo_id),
            )
            db.commit()
            flash("Recargo especial guardado. Se aplica a las compras nuevas.", "success")
        elif accion in ("quitar_organizador", "quitar_evento"):
            tabla = "organizadores" if accion == "quitar_organizador" else "eventos"
            db.execute(
                f"UPDATE {tabla} SET recargo_porcentaje = NULL, recargo_fijo = NULL WHERE id = ?",
                (request.form.get("objetivo_id"),),
            )
            db.commit()
            flash("Recargo especial quitado: vuelve a usar el general.", "info")
        return redirect(url_for("admin.recargos"))

    organizadores = db.execute(
        "SELECT id, nombre, email, recargo_porcentaje, recargo_fijo FROM organizadores ORDER BY nombre"
    ).fetchall()
    eventos = db.execute(
        """SELECT eventos.id, eventos.nombre, eventos.fecha, eventos.recargo_porcentaje,
                  eventos.recargo_fijo, organizadores.nombre AS organizador_nombre
           FROM eventos JOIN organizadores ON organizadores.id = eventos.organizador_id
           ORDER BY eventos.fecha DESC"""
    ).fetchall()
    return render_template(
        "admin/recargos.html",
        recargo=obtener_recargo_global(db),
        organizadores=organizadores,
        eventos=eventos,
        org_especiales=[
            o for o in organizadores
            if o["recargo_porcentaje"] is not None or o["recargo_fijo"] is not None
        ],
        ev_especiales=[
            e for e in eventos
            if e["recargo_porcentaje"] is not None or e["recargo_fijo"] is not None
        ],
        describir_recargo=describir_recargo,
    )


# ------------------------------------------------------------------ Cobros


def _estado_credenciales(valor):
    if not valor:
        return "falta"
    return "prueba" if valor.startswith("TEST-") else "produccion"


@admin_bp.route("/cobros", methods=["GET", "POST"])
@admin_required
def cobros():
    db = get_db()

    if request.method == "POST":
        accion = request.form.get("accion")
        if accion == "modo":
            try:
                actualizar_modo_cobro(db, request.form.get("modo"))
            except ValueError:
                abort(400)
            if request.form.get("modo") == "centralizado":
                flash("Ahora todos los pagos entran a tu cuenta de Mercado Pago.", "success")
            else:
                flash(
                    "Ahora cada organizador cobra en su propia cuenta de Mercado Pago "
                    "(tienen que conectarla para publicar eventos pagos).",
                    "success",
                )
        elif accion == "transferencia":
            try:
                organizador_id = int(request.form.get("organizador_id", ""))
                monto = _numero_opcional(request.form.get("monto"), 0.01)
                if monto is None:
                    raise ValueError
            except ValueError:
                flash("Ingresá un monto válido.", "danger")
                return redirect(url_for("admin.cobros"))
            organizador = db.execute(
                "SELECT nombre FROM organizadores WHERE id = ?", (organizador_id,)
            ).fetchone()
            if organizador is None:
                abort(404)
            db.execute(
                "INSERT INTO liquidaciones (organizador_id, monto, nota, creado_en) VALUES (?, ?, ?, ?)",
                (organizador_id, round(monto, 2),
                 request.form.get("nota", "").strip()[:200] or None, now_iso()),
            )
            db.commit()
            pesos = current_app.jinja_env.filters["pesos"]
            flash(f"Transferencia de {pesos(monto)} a {organizador['nombre']} registrada.", "success")
        return redirect(url_for("admin.cobros"))

    historial = db.execute(
        """SELECT liquidaciones.*, organizadores.nombre AS organizador_nombre,
                  datetime(liquidaciones.creado_en, '-3 hours') AS fecha_local
           FROM liquidaciones JOIN organizadores ON organizadores.id = liquidaciones.organizador_id
           ORDER BY liquidaciones.creado_en DESC LIMIT 30"""
    ).fetchall()
    return render_template(
        "admin/cobros.html",
        modo=obtener_modo_cobro(db),
        token=_estado_credenciales(current_app.config.get("MP_ACCESS_TOKEN")),
        public_key=_estado_credenciales(current_app.config.get("MP_PUBLIC_KEY")),
        saldos=saldos(db),
        historial=historial,
    )


@admin_bp.route("/cobros/<int:liquidacion_id>/anular", methods=["POST"])
@admin_required
def anular_transferencia(liquidacion_id):
    db = get_db()
    db.execute("DELETE FROM liquidaciones WHERE id = ?", (liquidacion_id,))
    db.commit()
    flash("Transferencia anulada (se volvió a sumar al saldo pendiente).", "info")
    return redirect(url_for("admin.cobros"))


# ------------------------------------------------------------- Organizadores


@admin_bp.route("/organizadores")
@admin_required
def organizadores():
    db = get_db()
    lista = db.execute(
        """SELECT organizadores.*,
                  (SELECT COUNT(*) FROM eventos WHERE eventos.organizador_id = organizadores.id) AS eventos,
                  (SELECT COUNT(*) FROM eventos WHERE eventos.organizador_id = organizadores.id
                     AND eventos.estado = 'publicado') AS publicados,
                  COALESCE((SELECT SUM(ordenes.total) FROM ordenes
                            JOIN eventos ON eventos.id = ordenes.evento_id
                            WHERE eventos.organizador_id = organizadores.id
                              AND ordenes.estado = 'pagada'), 0) AS cobrado,
                  COALESCE((SELECT SUM(ordenes.recargo_total) FROM ordenes
                            JOIN eventos ON eventos.id = ordenes.evento_id
                            WHERE eventos.organizador_id = organizadores.id
                              AND ordenes.estado = 'pagada'), 0) AS ganancia
           FROM organizadores ORDER BY organizadores.creado_en DESC"""
    ).fetchall()
    return render_template(
        "admin/organizadores.html",
        organizadores=lista,
        recargo=obtener_recargo_global(db),
        describir_recargo=describir_recargo,
    )


@admin_bp.route("/organizadores/nuevo", methods=["GET", "POST"])
@admin_required
def nuevo_organizador():
    """El dueño crea la cuenta de un productor (organizador) y le pasa los datos."""
    datos = {"nombre": "", "email": ""}
    if request.method == "POST":
        nombre = request.form.get("nombre", "").strip()
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        password_confirm = request.form.get("password_confirm", "")
        datos = {"nombre": nombre, "email": email}
        db = get_db()
        error = None
        if not nombre or not email or "@" not in email:
            error = "Completá el nombre y un email válido."
        elif len(password) < 8:
            error = "La contraseña tiene que tener al menos 8 caracteres."
        elif password != password_confirm:
            error = "Las contraseñas no coinciden."
        elif db.execute("SELECT 1 FROM organizadores WHERE email = ?", (email,)).fetchone() or \
                db.execute("SELECT 1 FROM administradores WHERE email = ?", (email,)).fetchone():
            error = "Ya existe una cuenta con ese email."
        if error:
            flash(error, "danger")
        else:
            db.execute(
                "INSERT INTO organizadores (nombre, email, password_hash, creado_en) VALUES (?, ?, ?, ?)",
                (nombre, email, generate_password_hash(password), now_iso()),
            )
            db.commit()
            flash(
                f"Cuenta creada para {nombre} ({email}). Pasale el email y la contraseña: entra "
                "por «Iniciar sesión» y desde su panel conecta su Mercado Pago.",
                "success",
            )
            return redirect(url_for("admin.organizadores"))
    return render_template("admin/organizador_nuevo.html", **datos)


@admin_bp.route("/organizadores/<int:organizador_id>/ver")
@admin_required
def ver_organizador(organizador_id):
    """Abre el panel del organizador en modo vista (solo lectura) sin cerrar la sesión de dueño."""
    organizador = get_db().execute(
        "SELECT id, nombre FROM organizadores WHERE id = ?", (organizador_id,)
    ).fetchone()
    if organizador is None:
        abort(404)
    session["ver_organizador_id"] = organizador["id"]
    destino = request.args.get("a", "")
    if not destino.startswith("/") or destino.startswith("//"):
        destino = url_for("eventos.panel")
    return redirect(destino)


@admin_bp.route("/dejar-de-ver")
@admin_required
def dejar_de_ver():
    session.pop("ver_organizador_id", None)
    return redirect(url_for("admin.organizadores"))


@admin_bp.route("/organizadores/<int:organizador_id>/suspender", methods=["POST"])
@admin_required
def suspender_organizador(organizador_id):
    db = get_db()
    organizador = db.execute(
        "SELECT * FROM organizadores WHERE id = ?", (organizador_id,)
    ).fetchone()
    if organizador is None:
        abort(404)
    nuevo = 0 if organizador["suspendido"] else 1
    db.execute("UPDATE organizadores SET suspendido = ? WHERE id = ?", (nuevo, organizador_id))
    db.commit()
    if nuevo:
        flash(
            f"{organizador['nombre']} quedó suspendido: no puede entrar y sus eventos dejan de verse.",
            "warning",
        )
    else:
        flash(f"{organizador['nombre']} fue reactivado.", "success")
    return redirect(url_for("admin.organizadores"))


# ------------------------------------------------------------------ Eventos


@admin_bp.route("/eventos")
@admin_required
def eventos():
    db = get_db()
    lista = db.execute(
        """SELECT eventos.*, organizadores.nombre AS organizador_nombre,
                  organizadores.suspendido AS organizador_suspendido,
                  (SELECT COALESCE(SUM(stock_vendido), 0) FROM tipos_entrada
                   WHERE tipos_entrada.evento_id = eventos.id) AS vendidas,
                  (SELECT COALESCE(SUM(stock_total), 0) FROM tipos_entrada
                   WHERE tipos_entrada.evento_id = eventos.id) AS stock_total,
                  COALESCE((SELECT SUM(recargo_total) FROM ordenes
                            WHERE ordenes.evento_id = eventos.id
                              AND ordenes.estado = 'pagada'), 0) AS ganancia
           FROM eventos JOIN organizadores ON organizadores.id = eventos.organizador_id
           ORDER BY eventos.fecha DESC"""
    ).fetchall()
    return render_template("admin/eventos.html", eventos=lista, describir_recargo=describir_recargo)


@admin_bp.route("/eventos/<int:evento_id>/bloquear", methods=["POST"])
@admin_required
def bloquear_evento(evento_id):
    db = get_db()
    evento = db.execute("SELECT * FROM eventos WHERE id = ?", (evento_id,)).fetchone()
    if evento is None:
        abort(404)
    if evento["bloqueado"]:
        db.execute("UPDATE eventos SET bloqueado = 0 WHERE id = ?", (evento_id,))
        flash(
            f"«{evento['nombre']}» fue habilitado. El organizador ya puede volver a publicarlo.",
            "success",
        )
    else:
        db.execute(
            "UPDATE eventos SET bloqueado = 1, estado = 'borrador' WHERE id = ?", (evento_id,)
        )
        flash(
            f"«{evento['nombre']}» fue pausado: dejó de verse y el organizador no puede republicarlo.",
            "warning",
        )
    db.commit()
    return redirect(url_for("admin.eventos"))


# -------------------------------------------------------------- Consola


@admin_bp.cli.command("recuperar-dueno", with_appcontext=True)
@click.password_option(
    "--password", prompt="Nueva contraseña", confirmation_prompt="Repetí la contraseña"
)
def recuperar_dueno(password):
    """Le pone una contraseña nueva a la cuenta de dueño (si te la olvidaste)."""
    if len(password) < 8:
        raise click.ClickException("La contraseña tiene que tener al menos 8 caracteres.")
    db = get_db()
    dueno = db.execute("SELECT * FROM administradores ORDER BY id LIMIT 1").fetchone()
    if dueno is None:
        raise click.ClickException(
            "Todavía no hay cuenta de dueño: creala desde la web entrando a /admin."
        )
    db.execute(
        "UPDATE administradores SET password_hash = ? WHERE id = ?",
        (generate_password_hash(password), dueno["id"]),
    )
    db.commit()
    click.echo(f"Contraseña actualizada para la cuenta de dueño {dueno['email']}.")
