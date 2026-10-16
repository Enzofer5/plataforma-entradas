from flask import current_app, redirect, render_template, request, url_for

from ..db import get_db
from ..servicios_compra import registrar_pago_mp
from . import pagos_bp
from .cuentas import cuenta_de_orden
from .mercadopago_client import MercadoPagoError, obtener_pago


@pagos_bp.route("/webhook/mercadopago", methods=["GET", "POST"])
def webhook_mercadopago():
    """Notificación (IPN / webhook) de Mercado Pago. Puede llegar como GET con query
    params (formato clásico) o como POST con JSON (formato nuevo) — contemplamos los dos.
    Siempre respondemos 200 para que Mercado Pago no siga reintentando, incluso si
    decidimos ignorar la notificación.

    No confiamos en lo que dice la notificación: con el id del pago se lo consultamos a
    Mercado Pago, con el token del organizador de esa orden."""
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
    # notificación para consultar el pago con el token correcto. Lo mandamos en la
    # propia `notification_url`.
    orden_id = request.args.get("orden_id")
    if not orden_id:
        return "", 200

    db = get_db()
    orden = db.execute("SELECT * FROM ordenes WHERE id = ?", (orden_id,)).fetchone()
    cuenta = cuenta_de_orden(db, orden) if orden else None
    if cuenta is None:
        return "", 200

    try:
        pago = obtener_pago(cuenta["token"], payment_id)
    except MercadoPagoError as exc:
        current_app.logger.warning("Error consultando pago de Mercado Pago: %s", exc)
        return "", 200

    # El pago tiene que ser de esta orden (no de otra con la que se intente mezclar).
    if str(pago.get("external_reference")) != str(orden["id"]):
        return "", 200

    registrar_pago_mp(db, orden, pago, cuenta["token"])
    return "", 200


@pagos_bp.route("/checkout/retorno")
def retorno():
    """Página a la que vuelve el comprador si pagó en la página de Mercado Pago. Con
    el id del pago que trae la URL consultamos el estado ahí mismo (sin esperar al
    webhook) y lo mandamos a la confirmación o a la página de pago."""
    codigo = request.args.get("orden")
    db = get_db()
    orden = db.execute("SELECT * FROM ordenes WHERE codigo = ?", (codigo,)).fetchone() if codigo else None
    if orden is None:
        return render_template("pagos/retorno.html", codigo=None)

    payment_id = request.args.get("payment_id") or request.args.get("collection_id")
    if orden["estado"] == "pendiente" and payment_id and payment_id != "null":
        cuenta = cuenta_de_orden(db, orden)
        if cuenta:
            try:
                pago = obtener_pago(cuenta["token"], payment_id)
                if str(pago.get("external_reference")) == str(orden["id"]):
                    registrar_pago_mp(db, orden, pago, cuenta["token"])
            except MercadoPagoError as exc:
                current_app.logger.warning("Error consultando pago al volver: %s", exc)
        orden = db.execute("SELECT * FROM ordenes WHERE id = ?", (orden["id"],)).fetchone()

    if orden["estado"] == "pagada":
        return redirect(url_for("compras.confirmacion", codigo=codigo))
    if orden["mp_estado"]:
        return redirect(url_for("compras.pagar", codigo=codigo))
    return render_template("pagos/retorno.html", codigo=codigo)
