from flask import abort, current_app, flash, redirect, render_template, request, url_for

from ..configuracion import obtener_recargo_porcentaje
from ..db import get_db, now_iso
from ..pagos.mercadopago_client import MercadoPagoError, crear_preferencia
from ..servicios_compra import StockInsuficienteError, confirmar_pago_orden
from . import compras_bp


def _evento_publicado_o_404(db, slug):
    evento = db.execute("SELECT * FROM eventos WHERE slug = ?", (slug,)).fetchone()
    if evento is None or evento["estado"] != "publicado":
        abort(404)
    return evento


@compras_bp.route("/evento/<slug>/comprar", methods=["GET", "POST"])
def comprar(slug):
    db = get_db()
    evento = _evento_publicado_o_404(db, slug)
    tipos = db.execute(
        "SELECT * FROM tipos_entrada WHERE evento_id = ? ORDER BY id", (evento["id"],)
    ).fetchall()

    if request.method == "POST":
        nombre = request.form.get("nombre", "").strip()
        email = request.form.get("email", "").strip().lower()
        dni = request.form.get("dni", "").strip()

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

        if error:
            flash(error, "danger")
            return render_template(
                "compras/comprar.html",
                evento=evento,
                tipos=tipos,
                nombre=nombre,
                email=email,
                dni=dni,
                cantidades=cantidades,
            )

        subtotal = sum(
            cantidades[tipo["id"]] * tipo["precio"] for tipo in tipos if tipo["id"] in cantidades
        )
        porcentaje_recargo = obtener_recargo_porcentaje(db)
        recargo_total = round(subtotal * porcentaje_recargo / 100, 2)
        total = round(subtotal + recargo_total, 2)

        cursor = db.execute(
            """INSERT INTO ordenes
               (evento_id, comprador_nombre, comprador_email, comprador_dni, subtotal,
                recargo_porcentaje_aplicado, recargo_total, total, estado, creado_en)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'pendiente', ?)""",
            (
                evento["id"],
                nombre,
                email,
                dni or None,
                subtotal,
                porcentaje_recargo,
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

        return redirect(url_for("compras.pagar", orden_id=orden_id))

    return render_template(
        "compras/comprar.html",
        evento=evento,
        tipos=tipos,
        nombre="",
        email="",
        dni="",
        cantidades={},
    )


@compras_bp.route("/checkout/<int:orden_id>/pagar", methods=["GET", "POST"])
def pagar(orden_id):
    db = get_db()
    orden = db.execute("SELECT * FROM ordenes WHERE id = ?", (orden_id,)).fetchone()
    if orden is None:
        abort(404)
    if orden["estado"] == "pagada":
        return redirect(url_for("compras.confirmacion", orden_id=orden_id))

    evento = db.execute("SELECT * FROM eventos WHERE id = ?", (orden["evento_id"],)).fetchone()
    items = db.execute(
        """SELECT orden_items.*, tipos_entrada.nombre AS tipo_nombre
           FROM orden_items
           JOIN tipos_entrada ON tipos_entrada.id = orden_items.tipo_entrada_id
           WHERE orden_items.orden_id = ?""",
        (orden_id,),
    ).fetchall()

    organizador = db.execute(
        "SELECT * FROM organizadores WHERE id = ?", (evento["organizador_id"],)
    ).fetchone()
    mp_token = organizador["mp_access_token"] if organizador else None

    if mp_token:
        # Modo real: la preferencia se crea con la cuenta de Mercado Pago del
        # organizador (conectada por OAuth) — la plata de las entradas entra ahí
        # directo, y a la plataforma le llega solo el recargo por `marketplace_fee`.
        # La confirmación efectiva llega después por el webhook.
        try:
            preferencia = crear_preferencia(
                mp_token,
                current_app.config["BASE_URL"],
                orden,
                items,
                evento,
                recargo_total=orden["recargo_total"] or 0,
            )
        except MercadoPagoError as exc:
            current_app.logger.warning("Error creando preferencia de Mercado Pago: %s", exc)
            return render_template(
                "compras/pagar.html",
                orden=orden,
                evento=evento,
                items=items,
                mp_configurado=True,
            )

        db.execute(
            "UPDATE ordenes SET mp_preference_id = ? WHERE id = ?",
            (preferencia["id"], orden_id),
        )
        db.commit()

        checkout_url = preferencia.get("sandbox_init_point") or preferencia["init_point"]
        return redirect(checkout_url)

    # Modo simulado: sin token de Mercado Pago configurado, todavía se puede probar
    # el circuito completo con un botón que marca la orden como pagada directamente.
    if request.method == "POST":
        try:
            confirmar_pago_orden(db, orden_id)
        except StockInsuficienteError as exc:
            flash(
                f'Ya no hay stock suficiente de "{exc}". Contactá al organizador.', "danger"
            )
            return redirect(url_for("compras.pagar", orden_id=orden_id))
        return redirect(url_for("compras.confirmacion", orden_id=orden_id))

    return render_template(
        "compras/pagar.html", orden=orden, evento=evento, items=items, mp_configurado=False
    )


@compras_bp.route("/checkout/<int:orden_id>/confirmacion")
def confirmacion(orden_id):
    db = get_db()
    orden = db.execute("SELECT * FROM ordenes WHERE id = ?", (orden_id,)).fetchone()
    if orden is None:
        abort(404)
    if orden["estado"] != "pagada":
        return redirect(url_for("compras.pagar", orden_id=orden_id))

    evento = db.execute("SELECT * FROM eventos WHERE id = ?", (orden["evento_id"],)).fetchone()
    entradas = db.execute(
        """SELECT entradas.*, tipos_entrada.nombre AS tipo_nombre
           FROM entradas
           JOIN tipos_entrada ON tipos_entrada.id = entradas.tipo_entrada_id
           WHERE entradas.orden_id = ?""",
        (orden_id,),
    ).fetchall()
    return render_template(
        "compras/confirmacion.html", orden=orden, evento=evento, entradas=entradas
    )
