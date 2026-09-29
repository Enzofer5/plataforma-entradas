"""Wrapper fino sobre el SDK oficial de Mercado Pago.

El import del paquete `mercadopago` se hace recién adentro de las funciones (no al
principio del archivo) para que la app no se rompa si todavía no está instalado —
no hace falta hasta que se cargue un MP_ACCESS_TOKEN en el .env.
"""


class MercadoPagoError(Exception):
    """Cualquier error al hablar con la API de Mercado Pago."""


def _sdk(access_token):
    try:
        import mercadopago
    except ImportError as exc:
        raise MercadoPagoError(
            "Falta instalar el paquete 'mercadopago' (correr: pip install -r requirements.txt)."
        ) from exc
    return mercadopago.SDK(access_token)


def crear_preferencia(access_token, base_url, orden, items, evento, recargo_total=0):
    """Crea una preferencia de pago (Checkout Pro) y devuelve la respuesta de Mercado Pago,
    que incluye 'id' y la URL de checkout ('init_point' / 'sandbox_init_point').

    `access_token` es el de la cuenta del ORGANIZADOR (conectada por OAuth) — la plata
    de las entradas entra directo ahí. Si `recargo_total` es mayor a 0, se le suma a la
    preferencia como un item aparte (así el comprador paga entrada + recargo) y se
    manda como `marketplace_fee`, que Mercado Pago descuenta automáticamente de lo que
    recibe el organizador y deposita en la cuenta de la plataforma (la dueña de esta
    aplicación, según su Client ID)."""
    sdk = _sdk(access_token)

    items_mp = [
        {
            "title": f"{evento['nombre']} — {item['tipo_nombre']}",
            "quantity": item["cantidad"],
            "unit_price": float(item["precio_unitario"]),
            "currency_id": "ARS",
        }
        for item in items
    ]
    if recargo_total:
        items_mp.append(
            {
                "title": "Cargo por servicio — Matrix Code",
                "quantity": 1,
                "unit_price": float(recargo_total),
                "currency_id": "ARS",
            }
        )

    preference_data = {
        "items": items_mp,
        "payer": {
            "name": orden["comprador_nombre"],
            "email": orden["comprador_email"],
        },
        "external_reference": str(orden["id"]),
        "back_urls": {
            "success": f"{base_url}/checkout/retorno?orden_id={orden['id']}",
            "pending": f"{base_url}/checkout/retorno?orden_id={orden['id']}",
            "failure": f"{base_url}/checkout/retorno?orden_id={orden['id']}",
        },
        "auto_return": "approved",
        "notification_url": f"{base_url}/webhook/mercadopago?orden_id={orden['id']}",
    }
    if recargo_total:
        preference_data["marketplace_fee"] = float(recargo_total)

    try:
        resultado = sdk.preference().create(preference_data)
    except Exception as exc:  # la red, credenciales inválidas, etc.
        raise MercadoPagoError(str(exc)) from exc

    if resultado.get("status") not in (200, 201):
        raise MercadoPagoError(f"Mercado Pago devolvió un error: {resultado}")

    return resultado["response"]


def obtener_pago(access_token, payment_id):
    """Consulta el estado de un pago por su id."""
    sdk = _sdk(access_token)

    try:
        resultado = sdk.payment().get(payment_id)
    except Exception as exc:
        raise MercadoPagoError(str(exc)) from exc

    if resultado.get("status") != 200:
        raise MercadoPagoError(f"No se pudo consultar el pago {payment_id}: {resultado}")

    return resultado["response"]
