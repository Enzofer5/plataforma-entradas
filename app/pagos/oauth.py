"""Conexión OAuth de la cuenta de Mercado Pago de cada organizador (modelo
marketplace/split payments) — independiente del SDK de `mercadopago`, porque el
intercambio de código por token es una llamada HTTP directa."""

from urllib.parse import urlencode

import requests

from .mercadopago_client import MercadoPagoError

AUTH_URL = "https://auth.mercadopago.com/authorization"
TOKEN_URL = "https://api.mercadopago.com/oauth/token"


def url_autorizacion(client_id, redirect_uri, state):
    query = urlencode(
        {
            "client_id": client_id,
            "response_type": "code",
            "platform_id": "mp",
            "state": state,
            "redirect_uri": redirect_uri,
        }
    )
    return f"{AUTH_URL}?{query}"


def intercambiar_codigo(client_id, client_secret, code, redirect_uri):
    """Cambia el 'code' que devuelve Mercado Pago tras la autorización por el
    access_token/refresh_token de la cuenta del organizador. Devuelve el JSON de la
    respuesta (incluye access_token, refresh_token, user_id, expires_in)."""
    try:
        respuesta = requests.post(
            TOKEN_URL,
            json={
                "client_id": client_id,
                "client_secret": client_secret,
                "code": code,
                "redirect_uri": redirect_uri,
                "grant_type": "authorization_code",
            },
            timeout=15,
        )
    except requests.RequestException as exc:
        raise MercadoPagoError(str(exc)) from exc

    if respuesta.status_code != 200:
        raise MercadoPagoError(
            f"Mercado Pago no pudo autorizar la cuenta ({respuesta.status_code}): {respuesta.text}"
        )

    return respuesta.json()
