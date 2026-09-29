from flask import current_app, redirect, render_template, request, url_for

from ..db import get_db
from ..servicios_compra import confirmar_pago_orden
from . import pagos_bp
from .mercadopago_client import MercadoPagoError, obtener_pago


@pagos_bp.route("/webhook/mercadopago", methods=["GET", "POST"])
def webhook_mercadopago():
    """Notificación (IPN / webhook) de Mercado Pago. Puede llegar como GET con query
    params (formato clásico) o como POST con JSON (formato nuevo) — contemplamos los dos.
    Siempre respondemos 200 para que Mercado Pago no siga reintentando, incluso si
    decidimos ignorar la notificación."""
    payload = request.get_json(silent=True) or {}

    payment_id = (
        request.args.get("data.id")
        or request.args.get("id")
        or payload.get("data", {}).get("id")
    )
    tipo = request.args.get("type") or request.args.get("topic") or payload.get("type")

    if not payment_id or (tipo and tipo != "payment"):
        return "", 200

    # El pago se hace con la cuenta de Mercado Pago del organizador (no una sola
    # cuenta de la plataforma), así que necesitamos saber de qué orden es esta
    # notificación para consultar el pago con el token correcto. `crear_preferencia`
    # manda `orden_id` en la propia `notification_url`, así no hay que adivinar.
    orden_id = request.args.get("orden_id")
    if not orden_id:
        return "", 200

    db = get_db()
    fila = db.execute(
        """SELECT organizadores.mp_access_token AS token
           FROM ordenes
           JOIN eventos ON eventos.id = ordenes.evento_id
           JOIN organizadores ON organizadores.id = eventos.organizador_id
           WHERE ordenes.id = ?""",
        (orden_id,),
    ).fetchone()
    if fila is None or not fila["token"]:
        return "", 200

    try:
        pago = obtener_pago(fila["token"], payment_id)
    except MercadoPagoError as exc:
        current_app.logger.warning("Error consultando pago de Mercado Pago: %s", exc)
        return "", 200

    if pago.get("status") == "approved":
        confirmar_pago_orden(db, orden_id, mp_payment_id=str(payment_id))

    return "", 200


@pagos_bp.route("/checkout/retorno")
def retorno():
    """Página a la que Mercado Pago redirige al comprador después de pagar. El estado
    real de la orden lo confirma el webhook (que puede tardar unos segundos más), así
    que acá solo mostramos un mensaje y, si ya está pagada, mandamos a la confirmación."""
    orden_id = request.args.get("orden_id")
    if orden_id:
        db = get_db()
        orden = db.execute("SELECT * FROM ordenes WHERE id = ?", (orden_id,)).fetchone()
        if orden and orden["estado"] == "pagada":
            return redirect(url_for("compras.confirmacion", orden_id=orden_id))
    return render_template("pagos/retorno.html", orden_id=orden_id)
