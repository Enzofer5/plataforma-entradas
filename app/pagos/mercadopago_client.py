"""Wrapper fino sobre el SDK oficial de Mercado Pago.

El import del paquete `mercadopago` se hace recién adentro de las funciones (no al
principio del archivo) para que la app no se rompa si todavía no está instalado.

El access token puede ser el de la PLATAFORMA (cobro centralizado: entra todo a su
cuenta) o el del ORGANIZADOR (conectado por OAuth). En este segundo caso, con
`con_comision=True`, el recargo se descuenta automáticamente (`marketplace_fee` en
preferencias, `application_fee` en pagos) y va a la cuenta dueña de la aplicación.
Ver pagos/cuentas.py.
"""

import uuid


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


def _url_publica(base_url):
    """Mercado Pago solo acepta webhooks y redirecciones automáticas a direcciones
    públicas con https (no a localhost)."""
    return base_url.startswith("https://")


def _items_mp(orden, items, evento):
    """Ítems para mostrarle al comprador en Mercado Pago. Con cupón, las entradas van
    como un único ítem con el subtotal ya descontado (MP no acepta precios negativos)."""
    descuento = orden["descuento"] or 0
    if descuento:
        subtotal = sum(item["cantidad"] * item["precio_unitario"] for item in items)
        detalle = ", ".join(f"{item['cantidad']}x {item['tipo_nombre']}" for item in items)
        lista = [
            {
                "title": f"{evento['nombre']} — {detalle} (con cupón de descuento)",
                "quantity": 1,
                "unit_price": round(float(subtotal - descuento), 2),
                "currency_id": "ARS",
            }
        ]
    else:
        lista = [
            {
                "title": f"{evento['nombre']} — {item['tipo_nombre']}",
                "quantity": item["cantidad"],
                "unit_price": float(item["precio_unitario"]),
                "currency_id": "ARS",
            }
            for item in items
        ]
    if orden["recargo_total"]:
        lista.append(
            {
                "title": "Cargo por servicio",
                "quantity": 1,
                "unit_price": float(orden["recargo_total"]),
                "currency_id": "ARS",
            }
        )
    return lista


def crear_preferencia(access_token, base_url, orden, items, evento, con_comision=True):
    """Crea una preferencia de pago y devuelve la respuesta de Mercado Pago ('id',
    'init_point'). Se usa para pagar con dinero en cuenta de Mercado Pago desde el
    formulario embebido, y como alternativa (redirigir a Mercado Pago) para los
    organizadores que todavía no tienen guardada su clave pública."""
    sdk = _sdk(access_token)

    retorno = f"{base_url}/checkout/retorno?orden={orden['codigo']}"
    preference_data = {
        "items": _items_mp(orden, items, evento),
        "payer": {
            "name": orden["comprador_nombre"],
            "email": orden["comprador_email"],
        },
        "external_reference": str(orden["id"]),
        "back_urls": {"success": retorno, "pending": retorno, "failure": retorno},
        "statement_descriptor": "ENTRADAS",
    }
    if _url_publica(base_url):
        preference_data["auto_return"] = "approved"
        preference_data["notification_url"] = (
            f"{base_url}/webhook/mercadopago?orden_id={orden['id']}"
        )
    if con_comision and orden["recargo_total"]:
        preference_data["marketplace_fee"] = float(orden["recargo_total"])

    try:
        resultado = sdk.preference().create(preference_data)
    except Exception as exc:  # la red, credenciales inválidas, etc.
        raise MercadoPagoError(str(exc)) from exc

    if resultado.get("status") not in (200, 201):
        raise MercadoPagoError(f"Mercado Pago devolvió un error: {resultado}")

    return resultado["response"]


def crear_pago(
    access_token, base_url, orden, items, evento, datos_formulario, con_comision=True, device_id=None
):
    """Crea el pago con los datos que manda el formulario embebido de Mercado Pago
    (Payment Brick). Para tarjetas, `datos_formulario` trae un `token` que representa
    la tarjeta: el número, vencimiento y código de seguridad nunca pasan por nuestro
    servidor. El monto se toma SIEMPRE de la orden guardada, nunca del navegador.

    Devuelve la respuesta de Mercado Pago (incluye 'id', 'status', 'status_detail')."""
    sdk = _sdk(access_token)
    from mercadopago.config import RequestOptions

    payer = dict(datos_formulario.get("payer") or {})
    payer.setdefault("email", orden["comprador_email"])
    nombre, _, apellido = orden["comprador_nombre"].partition(" ")
    payer.setdefault("first_name", nombre)
    if apellido:
        payer.setdefault("last_name", apellido)

    pago = {
        "transaction_amount": float(orden["total"]),
        "token": datos_formulario.get("token"),
        "description": f"Entradas — {evento['nombre']}",
        "installments": int(datos_formulario.get("installments") or 1),
        "payment_method_id": datos_formulario.get("payment_method_id"),
        "issuer_id": datos_formulario.get("issuer_id"),
        "payer": payer,
        "external_reference": str(orden["id"]),
        "statement_descriptor": "ENTRADAS",
        "metadata": {"orden_id": orden["id"]},
        # Datos que usa el antifraude de Mercado Pago: cuantos más, menos rechazos
        # "por seguridad" (cc_rejected_high_risk).
        "additional_info": {
            "items": [
                {
                    "id": str(item["tipo_entrada_id"]),
                    "title": f"{evento['nombre']} — {item['tipo_nombre']}",
                    "description": f"Entrada para {evento['nombre']} ({evento['fecha']})",
                    "category_id": "tickets",
                    "quantity": item["cantidad"],
                    "unit_price": float(item["precio_unitario"]),
                }
                for item in items
            ],
            "payer": {
                "first_name": payer.get("first_name", ""),
                "last_name": payer.get("last_name", ""),
            },
        },
    }
    if _url_publica(base_url):
        pago["notification_url"] = f"{base_url}/webhook/mercadopago?orden_id={orden['id']}"
    if con_comision and orden["recargo_total"]:
        pago["application_fee"] = float(orden["recargo_total"])
    # Fuera los campos vacíos (ej: los pagos en efectivo no tienen token ni cuotas).
    pago = {clave: valor for clave, valor in pago.items() if valor not in (None, "")}

    encabezados = {"x-idempotency-key": str(uuid.uuid4())}
    if device_id:
        # Id del dispositivo del comprador (script security.js de Mercado Pago).
        encabezados["X-meli-session-id"] = device_id
    opciones = RequestOptions(custom_headers=encabezados)
    try:
        resultado = sdk.payment().create(pago, opciones)
    except Exception as exc:
        raise MercadoPagoError(str(exc)) from exc

    if resultado.get("status") not in (200, 201):
        raise MercadoPagoError(f"Mercado Pago rechazó la solicitud: {resultado.get('response')}")

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


def reembolsar_pago(access_token, payment_id):
    """Devuelve el total de un pago (por ejemplo si se aprobó pero justo se agotaron
    las entradas)."""
    sdk = _sdk(access_token)
    try:
        resultado = sdk.refund().create(payment_id)
    except Exception as exc:
        raise MercadoPagoError(str(exc)) from exc
    if resultado.get("status") not in (200, 201):
        raise MercadoPagoError(f"No se pudo reembolsar el pago {payment_id}: {resultado}")
    return resultado["response"]
