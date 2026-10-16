"""Con qué cuenta de Mercado Pago se cobra cada compra.

- Modo 'centralizado' (configurable desde el panel del dueño): se cobra con la cuenta
  de la PLATAFORMA (MP_ACCESS_TOKEN / MP_PUBLIC_KEY del .env). Entra todo ahí y el dueño
  le transfiere a cada organizador lo suyo (ver "Liquidaciones" en el panel).
- Modo 'organizador': se cobra con la cuenta que conectó el organizador (OAuth), y la
  plataforma recibe solo el recargo como comisión de marketplace.

Si no hay cuenta disponible, devuelve None y la compra usa el pago simulado.
"""

from flask import current_app

from ..configuracion import obtener_modo_cobro


def _cuenta(modo, token, public_key):
    if not token:
        return None
    return {
        "modo": modo,
        "token": token,
        "public_key": public_key or None,
        # Comisión de marketplace: solo cuando cobra el organizador (en modo
        # centralizado el recargo ya entra a la cuenta de la plataforma).
        "con_comision": modo == "organizador",
    }


def _de_plataforma():
    return _cuenta(
        "centralizado",
        current_app.config.get("MP_ACCESS_TOKEN"),
        current_app.config.get("MP_PUBLIC_KEY"),
    )


def _del_organizador(db, organizador_id):
    organizador = db.execute(
        "SELECT mp_access_token, mp_public_key FROM organizadores WHERE id = ?",
        (organizador_id,),
    ).fetchone()
    if organizador is None:
        return None
    return _cuenta("organizador", organizador["mp_access_token"], organizador["mp_public_key"])


def cuenta_para_evento(db, evento):
    """Cuenta con la que se cobraría hoy una compra de este evento."""
    if obtener_modo_cobro(db) == "centralizado":
        return _de_plataforma()
    return _del_organizador(db, evento["organizador_id"])


def cuenta_de_orden(db, orden):
    """Cuenta con la que se cobró (o se está cobrando) esta orden. Respeta el modo con
    que se inició el pago aunque después se haya cambiado la configuración."""
    if orden["cobro_modo"] == "centralizado":
        return _de_plataforma()
    if orden["cobro_modo"] == "organizador":
        evento = db.execute(
            "SELECT organizador_id FROM eventos WHERE id = ?", (orden["evento_id"],)
        ).fetchone()
        return _del_organizador(db, evento["organizador_id"]) if evento else None
    evento = db.execute("SELECT * FROM eventos WHERE id = ?", (orden["evento_id"],)).fetchone()
    return cuenta_para_evento(db, evento) if evento else None
