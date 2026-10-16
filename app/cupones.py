"""Cupones de descuento por evento: los crea el organizador y el comprador los aplica
al comprar. El descuento se aplica sobre el precio de las entradas (lo que cobra el
organizador); el cargo por servicio de la plataforma se calcula después, sobre el
subtotal ya descontado."""

from datetime import date

TIPOS = ("porcentaje", "monto")


def normalizar_codigo(codigo):
    return (codigo or "").strip().upper()


def buscar_cupon_valido(db, evento_id, codigo):
    """Devuelve (cupon, None) si el código se puede usar ahora mismo para este evento,
    o (None, mensaje_de_error) si no."""
    codigo = normalizar_codigo(codigo)
    if not codigo:
        return None, None

    cupon = db.execute(
        "SELECT * FROM cupones WHERE evento_id = ? AND codigo = ?", (evento_id, codigo)
    ).fetchone()
    if cupon is None or not cupon["activo"]:
        return None, f'El cupón "{codigo}" no existe o no está activo.'
    if cupon["vence_en"] and cupon["vence_en"] < date.today().isoformat():
        return None, f'El cupón "{codigo}" ya venció.'
    if cupon["usos_maximos"] is not None and cupon["usos"] >= cupon["usos_maximos"]:
        return None, f'El cupón "{codigo}" ya alcanzó su límite de usos.'
    return cupon, None


def calcular_descuento(cupon, subtotal):
    """Monto a descontar del subtotal (nunca más que el subtotal)."""
    if cupon is None or subtotal <= 0:
        return 0.0
    if cupon["tipo"] == "porcentaje":
        descuento = subtotal * cupon["valor"] / 100
    else:
        descuento = cupon["valor"]
    return round(min(descuento, subtotal), 2)


def describir(cupon):
    """Texto corto para mostrar: '20% off' o '$500 off'."""
    if cupon["tipo"] == "porcentaje":
        return f"{cupon['valor']:g}% off"
    return f"${cupon['valor']:,.0f} off".replace(",", ".")
