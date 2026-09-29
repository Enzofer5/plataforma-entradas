"""Lógica compartida para confirmar el pago de una orden: la usan tanto el pago
simulado (compras/routes.py) como el webhook real de Mercado Pago (pagos/routes.py)."""

import uuid

from .db import now_iso


class StockInsuficienteError(Exception):
    """El stock disponible ya no alcanza para cubrir la orden (alguien más compró antes)."""


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

    if mp_payment_id:
        db.execute(
            "UPDATE ordenes SET estado = 'pagada', mp_payment_id = ? WHERE id = ?",
            (mp_payment_id, orden_id),
        )
    else:
        db.execute("UPDATE ordenes SET estado = 'pagada' WHERE id = ?", (orden_id,))

    db.commit()
