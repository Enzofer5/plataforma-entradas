import uuid

from flask import (
    abort,
    current_app,
    flash,
    g,
    jsonify,
    redirect,
    render_template,
    request,
    url_for,
)

from ..configuracion import calcular_recargo, recargo_para_evento
from ..cupones import buscar_cupon_valido, calcular_descuento, normalizar_codigo
from ..db import get_db, now_iso
from ..pagos.mercadopago_client import (
    MercadoPagoError,
    crear_pago,
    crear_preferencia,
    obtener_pago,
)
from ..pagos.cuentas import cuenta_de_orden, cuenta_para_evento
from ..servicios_compra import (
    StockInsuficienteError,
    confirmar_pago_orden,
    mensaje_para_comprador,
    registrar_pago_mp,
)
from ..cuentas.routes import comprador_requerido
from . import compras_bp


def _evento_publicado_o_404(db, slug):
    evento = db.execute(
        """SELECT eventos.* FROM eventos
           JOIN organizadores ON organizadores.id = eventos.organizador_id
           WHERE eventos.slug = ? AND eventos.estado = 'publicado'
             AND eventos.bloqueado = 0 AND organizadores.suspendido = 0""",
        (slug,),
    ).fetchone()
    if evento is None:
        abort(404)
    return evento


def _orden_o_404(db, codigo):
    orden = db.execute("SELECT * FROM ordenes WHERE codigo = ?", (codigo,)).fetchone()
    if orden is None:
        abort(404)
    return orden


def _items(db, orden_id):
    return db.execute(
        """SELECT orden_items.*, tipos_entrada.nombre AS tipo_nombre
           FROM orden_items
           JOIN tipos_entrada ON tipos_entrada.id = orden_items.tipo_entrada_id
           WHERE orden_items.orden_id = ?""",
        (orden_id,),
    ).fetchall()


@compras_bp.route("/evento/<slug>/comprar", methods=["GET", "POST"])
@comprador_requerido
def comprar(slug):
    db = get_db()
    evento = _evento_publicado_o_404(db, slug)
    tipos = db.execute(
        "SELECT * FROM tipos_entrada WHERE evento_id = ? ORDER BY id", (evento["id"],)
    ).fetchall()
    recargo = recargo_para_evento(db, evento)

    if request.method == "POST":
        nombre = request.form.get("nombre", "").strip() or g.comprador["nombre"]
        email = g.comprador["email"]   # las entradas van siempre al email de la cuenta
        dni = request.form.get("dni", "").strip() or (g.comprador["dni"] or "")
        codigo_cupon = normalizar_codigo(request.form.get("cupon"))

        cantidades = {}
        for tipo in tipos:
            raw = request.form.get(f"cantidad_{tipo['id']}", "0").strip()
            try:
                cantidad = int(raw) if raw else 0
            except ValueError:
                cantidad = 0
            if cantidad > 0:
                cantidades[tipo["id"]] = cantidad

        error = None
        if not nombre or not email:
            error = "Completá tu nombre y email."
        elif not cantidades:
            error = "Elegí al menos una entrada."
        else:
            for tipo in tipos:
                pedidas = cantidades.get(tipo["id"], 0)
                disponible = tipo["stock_total"] - tipo["stock_vendido"]
                if pedidas > disponible:
                    error = f'Solo quedan {disponible} entradas de "{tipo["nombre"]}".'
                    break

        cupon = None
        if not error and codigo_cupon:
            cupon, error = buscar_cupon_valido(db, evento["id"], codigo_cupon)

        if error:
            flash(error, "danger")
            return render_template(
                "compras/comprar.html",
                evento=evento,
                tipos=tipos,
                recargo=recargo,
                nombre=nombre,
                email=email,
                dni=dni,
                cupon=codigo_cupon,
                cantidades=cantidades,
            )

        subtotal = sum(
            cantidades[tipo["id"]] * tipo["precio"] for tipo in tipos if tipo["id"] in cantidades
        )
        entradas_pagas = sum(
            cantidades[tipo["id"]] for tipo in tipos if tipo["id"] in cantidades and tipo["precio"] > 0
        )
        descuento = calcular_descuento(cupon, subtotal)
        recargo_total = calcular_recargo(recargo, subtotal - descuento, entradas_pagas)
        total = round(subtotal - descuento + recargo_total, 2)
        codigo = uuid.uuid4().hex

        cursor = db.execute(
            """INSERT INTO ordenes
               (comprador_id, evento_id, codigo, comprador_nombre, comprador_email, comprador_dni, subtotal,
                cupon_id, descuento, recargo_porcentaje_aplicado, recargo_fijo_aplicado,
                recargo_total, total, estado, creado_en)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'pendiente', ?)""",
            (
                g.comprador["id"],
                evento["id"],
                codigo,
                nombre,
                email,
                dni or None,
                subtotal,
                cupon["id"] if cupon else None,
                descuento,
                recargo["porcentaje"],
                recargo["fijo"],
                recargo_total,
                total,
                now_iso(),
            ),
        )
        orden_id = cursor.lastrowid

        for tipo in tipos:
            cantidad = cantidades.get(tipo["id"], 0)
            if cantidad:
                db.execute(
                    """INSERT INTO orden_items (orden_id, tipo_entrada_id, cantidad, precio_unitario)
                       VALUES (?, ?, ?, ?)""",
                    (orden_id, tipo["id"], cantidad, tipo["precio"]),
                )
        db.commit()

        return redirect(url_for("compras.pagar", codigo=codigo))

    return render_template(
        "compras/comprar.html",
        evento=evento,
        tipos=tipos,
        recargo=recargo,
        nombre=g.comprador["nombre"],
        email=g.comprador["email"],
        dni=g.comprador["dni"] or "",
        cupon=request.args.get("cupon", ""),
        cantidades={},
    )


@compras_bp.route("/checkout/<codigo>/pagar", methods=["GET", "POST"])
def pagar(codigo):
    db = get_db()
    orden = _orden_o_404(db, codigo)
    if orden["estado"] == "pagada":
        return redirect(url_for("compras.confirmacion", codigo=codigo))

    evento = db.execute("SELECT * FROM eventos WHERE id = ?", (orden["evento_id"],)).fetchone()
    items = _items(db, orden["id"])
    cupon = None
    if orden["cupon_id"]:
        cupon = db.execute("SELECT * FROM cupones WHERE id = ?", (orden["cupon_id"],)).fetchone()
    contexto = {"orden": orden, "evento": evento, "items": items, "cupon": cupon}

    if orden["estado"] in ("reembolsada", "sin_stock"):
        return render_template("compras/pagar.html", modo="sin_stock", **contexto)

    # Total $0 (entradas gratis o cupón del 100%): no hay nada que cobrar, y Mercado
    # Pago no acepta pagos de $0 — se confirma directo.
    if orden["total"] <= 0:
        try:
            confirmar_pago_orden(db, orden["id"])
        except StockInsuficienteError as exc:
            flash(f'Ya no hay stock suficiente de "{exc}".', "danger")
            return redirect(url_for("public.evento_detalle", slug=evento["slug"]))
        return redirect(url_for("compras.confirmacion", codigo=codigo))

    # Si el pago ya se inició con una cuenta, se sigue con esa; si no, la que
    # corresponda hoy según el modo de cobro (plataforma u organizador).
    if orden["mp_payment_id"]:
        cuenta = cuenta_de_orden(db, orden)
    else:
        cuenta = cuenta_para_evento(db, evento)

    if cuenta:
        if orden["cobro_modo"] != cuenta["modo"]:
            db.execute(
                "UPDATE ordenes SET cobro_modo = ? WHERE id = ?", (cuenta["modo"], orden["id"])
            )
            db.commit()
            orden = _orden_o_404(db, codigo)
            contexto["orden"] = orden

        # Pago en efectivo o en revisión: no se vuelve a cobrar, se muestra el estado.
        if orden["mp_estado"] in ("pending", "in_process", "authorized"):
            return render_template(
                "compras/pagar.html",
                modo="pendiente",
                mensaje=mensaje_para_comprador(orden["mp_estado"], orden["mp_estado_detalle"]),
                **contexto,
            )

        # La preferencia sirve para pagar con dinero en cuenta de Mercado Pago dentro
        # del formulario (y para redirigir, si el organizador no tiene clave pública).
        try:
            preferencia = crear_preferencia(
                cuenta["token"],
                current_app.config["BASE_URL"],
                orden,
                items,
                evento,
                con_comision=cuenta["con_comision"],
            )
            db.execute(
                "UPDATE ordenes SET mp_preference_id = ? WHERE id = ?",
                (preferencia["id"], orden["id"]),
            )
            db.commit()
        except MercadoPagoError as exc:
            current_app.logger.warning("Error creando preferencia de Mercado Pago: %s", exc)
            preferencia = None

        if cuenta["public_key"]:
            return render_template(
                "compras/pagar.html",
                modo="formulario",
                mp_public_key=cuenta["public_key"],
                preference_id=preferencia["id"] if preferencia else None,
                **contexto,
            )
        if preferencia:
            # Sin clave pública (organizador conectado antes de que se guardara, o
            # MP_PUBLIC_KEY vacía): se paga en la página de Mercado Pago.
            return redirect(preferencia["init_point"])
        return render_template("compras/pagar.html", modo="error_mp", **contexto)

    # Modo simulado: sin cuenta de Mercado Pago para cobrar, todavía se puede probar el
    # circuito completo con un botón que marca la orden como pagada directamente.
    if request.method == "POST":
        try:
            confirmar_pago_orden(db, orden["id"])
        except StockInsuficienteError as exc:
            flash(f'Ya no hay stock suficiente de "{exc}". Contactá al organizador.', "danger")
            return redirect(url_for("compras.pagar", codigo=codigo))
        return redirect(url_for("compras.confirmacion", codigo=codigo))

    return render_template("compras/pagar.html", modo="simulado", **contexto)


@compras_bp.route("/checkout/<codigo>/procesar", methods=["POST"])
def procesar(codigo):
    """Recibe lo que manda el formulario de pago embebido (Payment Brick) y crea el
    pago en Mercado Pago. Responde JSON: {estado, mensaje, redirect?, ticket_url?}."""
    db = get_db()
    orden = _orden_o_404(db, codigo)
    url_confirmacion = url_for("compras.confirmacion", codigo=codigo)
    if orden["estado"] == "pagada":
        return jsonify(estado="aprobado", mensaje="¡Pago aprobado!", redirect=url_confirmacion)
    if orden["estado"] != "pendiente":
        return jsonify(estado="rechazado", mensaje="Esta compra ya no se puede pagar."), 400

    evento = db.execute("SELECT * FROM eventos WHERE id = ?", (orden["evento_id"],)).fetchone()
    cuenta = cuenta_de_orden(db, orden)
    if not cuenta:
        return jsonify(estado="rechazado", mensaje="Este evento no tiene cobro online."), 400

    datos = request.get_json(silent=True) or {}
    if not datos.get("payment_method_id"):
        return jsonify(estado="rechazado", mensaje="Elegí un medio de pago."), 400

    try:
        pago = crear_pago(
            cuenta["token"],
            current_app.config["BASE_URL"],
            orden,
            _items(db, orden["id"]),
            evento,
            datos,
            con_comision=cuenta["con_comision"],
            device_id=(request.headers.get("X-Device-Id") or "")[:200] or None,
        )
    except MercadoPagoError as exc:
        current_app.logger.warning("Error creando pago para la orden %s: %s", orden["id"], exc)
        return jsonify(
            estado="rechazado",
            mensaje="No pudimos procesar el pago. Revisá los datos o probá con otro medio.",
        ), 502

    resultado = registrar_pago_mp(db, orden, pago, cuenta["token"])
    mensaje = mensaje_para_comprador(pago.get("status"), pago.get("status_detail"))
    if resultado == "aprobado":
        return jsonify(estado="aprobado", mensaje=mensaje, redirect=url_confirmacion)
    if resultado == "reembolsado":
        return jsonify(
            estado="rechazado",
            mensaje="Justo se agotaron las entradas que elegiste. Te devolvimos el pago completo.",
        )
    if resultado == "pendiente":
        return jsonify(
            estado="pendiente",
            mensaje=mensaje,
            ticket_url=(pago.get("transaction_details") or {}).get("external_resource_url"),
            redirect=url_for("compras.pagar", codigo=codigo),
        )
    return jsonify(estado="rechazado", mensaje=mensaje)


@compras_bp.route("/checkout/<codigo>/error-formulario", methods=["POST"])
def error_formulario(codigo):
    """El formulario de Mercado Pago avisa acá sus errores (sin datos de la tarjeta),
    para que queden en el registro de la app y se puedan diagnosticar."""
    datos = request.get_json(silent=True) or {}
    current_app.logger.warning(
        "Formulario de pago (orden %s): %s / %s / %s",
        codigo[:8],
        str(datos.get("tipo"))[:40],
        str(datos.get("causa"))[:80],
        str(datos.get("mensaje"))[:200],
    )
    return "", 204


@compras_bp.route("/checkout/<codigo>/estado")
def estado(codigo):
    """'Ya pagué': consulta a Mercado Pago cómo está el pago (por si el aviso
    automático todavía no llegó) y vuelve a la página que corresponda."""
    db = get_db()
    orden = _orden_o_404(db, codigo)
    if orden["estado"] == "pendiente" and orden["mp_payment_id"]:
        cuenta = cuenta_de_orden(db, orden)
        if cuenta:
            try:
                pago = obtener_pago(cuenta["token"], orden["mp_payment_id"])
                registrar_pago_mp(db, orden, pago, cuenta["token"])
            except MercadoPagoError as exc:
                current_app.logger.warning("Error consultando pago: %s", exc)
                flash("No pudimos consultar el pago ahora. Probá en un momento.", "warning")
    return redirect(url_for("compras.pagar", codigo=codigo))


@compras_bp.route("/checkout/<codigo>/confirmacion")
def confirmacion(codigo):
    db = get_db()
    orden = _orden_o_404(db, codigo)
    if orden["estado"] != "pagada":
        return redirect(url_for("compras.pagar", codigo=codigo))

    evento = db.execute("SELECT * FROM eventos WHERE id = ?", (orden["evento_id"],)).fetchone()
    entradas = db.execute(
        """SELECT entradas.*, tipos_entrada.nombre AS tipo_nombre
           FROM entradas
           JOIN tipos_entrada ON tipos_entrada.id = entradas.tipo_entrada_id
           WHERE entradas.orden_id = ?""",
        (orden["id"],),
    ).fetchall()
    return render_template(
        "compras/confirmacion.html", orden=orden, evento=evento, entradas=entradas
    )
