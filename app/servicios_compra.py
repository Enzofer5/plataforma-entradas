"""Lógica compartida para confirmar el pago de una orden: la usan el pago simulado y
el formulario de pago (compras/routes.py) y el webhook de Mercado Pago (pagos/routes.py)."""

import uuid

from flask import current_app

from .correo import enviar_entradas_por_email
from .db import now_iso


class StockInsuficienteError(Exception):
    """El stock disponible ya no alcanza para cubrir la orden (alguien más compró antes)."""


# Explicación para el comprador según el motivo que informa Mercado Pago.
MENSAJES_MP = {
    "accredited": "¡Pago aprobado!",
    "pending_contingency": "Estamos procesando tu pago. En menos de 2 días hábiles te avisamos por mail si se acreditó.",
    "pending_review_manual": "Estamos revisando tu pago. En menos de 2 días hábiles te avisamos por mail si se acreditó.",
    "pending_waiting_payment": "Tu cupón de pago está listo. Pagalo en efectivo y te mandamos las entradas apenas se acredite.",
    "pending_waiting_transfer": "Esperando la transferencia. Te mandamos las entradas apenas se acredite.",
    "cc_rejected_bad_filled_card_number": "Revisá el número de la tarjeta.",
    "cc_rejected_bad_filled_date": "Revisá la fecha de vencimiento de la tarjeta.",
    "cc_rejected_bad_filled_security_code": "Revisá el código de seguridad de la tarjeta.",
    "cc_rejected_bad_filled_other": "Revisá los datos de la tarjeta.",
    "cc_rejected_insufficient_amount": "La tarjeta no tiene saldo o límite suficiente. Probá con otra o con otro medio de pago.",
    "cc_rejected_call_for_authorize": "Tu banco necesita que autorices este pago: llamá al número que figura al dorso de la tarjeta y volvé a intentar.",
    "cc_rejected_card_disabled": "La tarjeta no está activa. Llamá a tu banco para activarla o usá otra.",
    "cc_rejected_duplicated_payment": "Ya hiciste un pago por este mismo monto hace un momento. Si necesitás pagar de nuevo, usá otra tarjeta u otro medio.",
    "cc_rejected_high_risk": "El pago fue rechazado por seguridad. Probá con otra tarjeta u otro medio de pago.",
    "cc_rejected_max_attempts": "Llegaste al límite de intentos con esta tarjeta. Probá con otra.",
    "cc_rejected_invalid_installments": "Tu tarjeta no acepta esa cantidad de cuotas. Elegí otra.",
    "cc_rejected_card_error": "No se pudo procesar la tarjeta. Probá de nuevo o con otra.",
    "cc_rejected_blacklist": "No pudimos procesar el pago con esta tarjeta. Probá con otra u otro medio.",
    "cc_rejected_other_reason": "Tu banco rechazó el pago. Probá con otra tarjeta u otro medio de pago.",
}


def costos_de_pago(pago):
    """Separa lo que descontó Mercado Pago de un pago aprobado: su comisión y las
    retenciones de impuestos (Ingresos Brutos, etc.), y lo que llegó neto."""
    tarifas = [
        f for f in pago.get("fee_details") or [] if f.get("fee_payer", "collector") == "collector"
    ]
    # La comisión de marketplace ("application_fee") es el recargo de la plataforma:
    # no es un costo de Mercado Pago.
    recargo_plataforma = sum(
        float(f.get("amount") or 0) for f in tarifas if f.get("type") == "application_fee"
    )
    comision = sum(
        float(f.get("amount") or 0) for f in tarifas if f.get("type") != "application_fee"
    )
    impuestos = sum(
        float((c.get("amounts") or {}).get("original") or 0)
        for c in pago.get("charges_details") or []
        if c.get("type") == "tax"
    )
    neto = (pago.get("transaction_details") or {}).get("net_received_amount")
    total = float(pago.get("transaction_amount") or 0)
    if neto is None:
        neto = total - comision - impuestos
    else:
        neto = float(neto)
        # Si Mercado Pago no detalla todo, lo que falte se cuenta como impuestos.
        resto = round(total - neto - comision - impuestos - recargo_plataforma, 2)
        if resto > 0:
            impuestos += resto
    return {"neto": round(neto, 2), "comision": round(comision, 2), "impuestos": round(impuestos, 2)}


def mensaje_para_comprador(estado, detalle):
    if detalle in MENSAJES_MP:
        return MENSAJES_MP[detalle]
    if estado == "approved":
        return "¡Pago aprobado!"
    if estado in ("pending", "in_process", "authorized"):
        return "Tu pago está en proceso. Te avisamos por mail apenas se acredite."
    return "El pago fue rechazado. Probá con otra tarjeta u otro medio de pago."


def registrar_pago_mp(db, orden, pago, access_token):
    """Guarda en la orden lo que informa Mercado Pago sobre un pago (venga del
    formulario, del webhook o de una consulta) y, si está aprobado, genera las
    entradas. Devuelve el estado final para la orden: 'aprobado', 'pendiente',
    'rechazado' o 'reembolsado' (aprobado pero ya sin stock: se devuelve la plata)."""
    from .pagos.mercadopago_client import MercadoPagoError, reembolsar_pago

    estado = pago.get("status")
    detalle = pago.get("status_detail")
    payment_id = str(pago.get("id")) if pago.get("id") else None
    ticket_url = (pago.get("transaction_details") or {}).get("external_resource_url")

    # Un pago rechazado no pisa a uno anterior que ya estaba aprobado o pendiente
    # (el comprador puede haber reintentado con otra tarjeta).
    if orden["estado"] == "pagada" and estado != "approved":
        return "aprobado"

    db.execute(
        """UPDATE ordenes SET mp_payment_id = COALESCE(?, mp_payment_id), mp_estado = ?,
                  mp_estado_detalle = ?, mp_ticket_url = COALESCE(?, mp_ticket_url)
           WHERE id = ?""",
        (payment_id, estado, detalle, ticket_url, orden["id"]),
    )
    if estado == "approved":
        costos = costos_de_pago(pago)
        db.execute(
            "UPDATE ordenes SET mp_neto = ?, mp_comision = ?, mp_impuestos = ? WHERE id = ?",
            (costos["neto"], costos["comision"], costos["impuestos"], orden["id"]),
        )
    db.commit()

    if estado == "approved":
        try:
            confirmar_pago_orden(db, orden["id"], mp_payment_id=payment_id)
        except StockInsuficienteError:
            db.rollback()
            current_app.logger.warning(
                "Pago %s aprobado para la orden %s pero sin stock: se reembolsa.",
                payment_id,
                orden["id"],
            )
            try:
                reembolsar_pago(access_token, payment_id)
                db.execute(
                    "UPDATE ordenes SET estado = 'reembolsada', mp_estado = 'refunded' WHERE id = ?",
                    (orden["id"],),
                )
            except MercadoPagoError as exc:
                current_app.logger.error("No se pudo reembolsar el pago %s: %s", payment_id, exc)
                db.execute(
                    "UPDATE ordenes SET estado = 'sin_stock' WHERE id = ?", (orden["id"],)
                )
            db.commit()
            return "reembolsado"
        return "aprobado"
    if estado in ("pending", "in_process", "authorized"):
        return "pendiente"
    return "rechazado"


def confirmar_pago_orden(db, orden_id, mp_payment_id=None):
    """Marca la orden como pagada, descuenta el stock y genera las entradas.

    Es idempotente: si la orden ya estaba pagada, no hace nada (importante porque
    Mercado Pago puede llamar al webhook más de una vez para el mismo pago).
    """
    orden = db.execute("SELECT * FROM ordenes WHERE id = ?", (orden_id,)).fetchone()
    if orden is None or orden["estado"] == "pagada":
        return

    items = db.execute(
        """SELECT orden_items.*, tipos_entrada.nombre AS tipo_nombre
           FROM orden_items
           JOIN tipos_entrada ON tipos_entrada.id = orden_items.tipo_entrada_id
           WHERE orden_items.orden_id = ?""",
        (orden_id,),
    ).fetchall()

    for item in items:
        tipo = db.execute(
            "SELECT * FROM tipos_entrada WHERE id = ?", (item["tipo_entrada_id"],)
        ).fetchone()
        disponible = tipo["stock_total"] - tipo["stock_vendido"]
        if item["cantidad"] > disponible:
            raise StockInsuficienteError(tipo["nombre"])

    for item in items:
        db.execute(
            "UPDATE tipos_entrada SET stock_vendido = stock_vendido + ? WHERE id = ?",
            (item["cantidad"], item["tipo_entrada_id"]),
        )
        for _ in range(item["cantidad"]):
            db.execute(
                """INSERT INTO entradas (orden_id, tipo_entrada_id, codigo_unico, estado, creado_en)
                   VALUES (?, ?, ?, 'valida', ?)""",
                (orden_id, item["tipo_entrada_id"], str(uuid.uuid4()), now_iso()),
            )

    if orden["cupon_id"]:
        db.execute("UPDATE cupones SET usos = usos + 1 WHERE id = ?", (orden["cupon_id"],))

    if mp_payment_id:
        db.execute(
            "UPDATE ordenes SET estado = 'pagada', mp_payment_id = ? WHERE id = ?",
            (mp_payment_id, orden_id),
        )
    else:
        db.execute("UPDATE ordenes SET estado = 'pagada' WHERE id = ?", (orden_id,))

    db.commit()

    # Mandar el mail con las entradas es un extra, no algo de lo que dependa la
    # confirmación del pago — si falla o no está configurado, no debe romper nada de
    # lo anterior (por eso ya está todo commiteado antes de intentarlo).
    entradas_creadas = db.execute(
        """SELECT entradas.*, tipos_entrada.nombre AS tipo_nombre
           FROM entradas
           JOIN tipos_entrada ON tipos_entrada.id = entradas.tipo_entrada_id
           WHERE entradas.orden_id = ?
           ORDER BY entradas.id""",
        (orden_id,),
    ).fetchall()
    evento = db.execute("SELECT * FROM eventos WHERE id = ?", (orden["evento_id"],)).fetchone()
    enviar_entradas_por_email(current_app, orden, evento, entradas_creadas)
