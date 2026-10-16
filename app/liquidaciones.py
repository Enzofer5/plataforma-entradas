"""Cuentas con los organizadores en el modo de cobro centralizado.

Por cada venta cobrada con la cuenta de la plataforma:
  - el cargo por servicio (recargo) es la ganancia de la plataforma, entero;
  - al organizador le corresponde el precio de sus entradas menos los cupones, MENOS
    los costos de cobro de esa venta (comisión de Mercado Pago y retenciones de
    impuestos), que son costos de su venta.

`a_transferir - transferido = pendiente`.
"""

_VENDIDO = """
    SELECT eventos.organizador_id AS organizador_id,
           COALESCE(SUM(COALESCE(ordenes.subtotal, ordenes.total) - COALESCE(ordenes.descuento, 0)), 0) AS vendido,
           COALESCE(SUM(COALESCE(ordenes.mp_comision, 0)), 0) AS comision,
           COALESCE(SUM(COALESCE(ordenes.mp_impuestos, 0)), 0) AS impuestos,
           COALESCE(SUM(COALESCE(ordenes.recargo_total, 0)), 0) AS recargos,
           COUNT(ordenes.id) AS compras
    FROM ordenes JOIN eventos ON eventos.id = ordenes.evento_id
    WHERE ordenes.estado = 'pagada' AND ordenes.cobro_modo = 'centralizado'
    GROUP BY eventos.organizador_id
"""

_TRANSFERIDO = """
    SELECT organizador_id, COALESCE(SUM(monto), 0) AS transferido, MAX(creado_en) AS ultima
    FROM liquidaciones GROUP BY organizador_id
"""


def saldos(db):
    """Una fila por organizador: vendido, costos de cobro, a transferir, transferido,
    pendiente y sus datos para transferirle."""
    return db.execute(
        f"""SELECT organizadores.id, organizadores.nombre, organizadores.email,
                   organizadores.datos_cobro, organizadores.suspendido,
                   COALESCE(v.vendido, 0) AS vendido, COALESCE(v.compras, 0) AS compras,
                   COALESCE(v.comision, 0) AS comision, COALESCE(v.impuestos, 0) AS impuestos,
                   COALESCE(v.recargos, 0) AS recargos,
                   ROUND(COALESCE(v.vendido, 0) - COALESCE(v.comision, 0) - COALESCE(v.impuestos, 0), 2) AS a_transferir,
                   COALESCE(t.transferido, 0) AS transferido, t.ultima,
                   ROUND(COALESCE(v.vendido, 0) - COALESCE(v.comision, 0) - COALESCE(v.impuestos, 0)
                         - COALESCE(t.transferido, 0), 2) AS pendiente
            FROM organizadores
            LEFT JOIN ({_VENDIDO}) v ON v.organizador_id = organizadores.id
            LEFT JOIN ({_TRANSFERIDO}) t ON t.organizador_id = organizadores.id
            ORDER BY pendiente DESC, organizadores.nombre"""
    ).fetchall()


def saldo_de(db, organizador_id):
    for fila in saldos(db):
        if fila["id"] == organizador_id:
            return fila
    return None


def ventas_de(db, organizador_id, limite=50):
    """Detalle venta por venta (cobro centralizado), para que el organizador vea
    cuánto descontó Mercado Pago en cada una."""
    return db.execute(
        """SELECT ordenes.id, datetime(ordenes.creado_en, '-3 hours') AS fecha_local,
                  eventos.nombre AS evento_nombre, ordenes.total,
                  COALESCE(ordenes.recargo_total, 0) AS recargo,
                  COALESCE(ordenes.subtotal, ordenes.total) - COALESCE(ordenes.descuento, 0) AS venta,
                  COALESCE(ordenes.mp_comision, 0) AS comision,
                  COALESCE(ordenes.mp_impuestos, 0) AS impuestos,
                  ROUND(COALESCE(ordenes.subtotal, ordenes.total) - COALESCE(ordenes.descuento, 0)
                        - COALESCE(ordenes.mp_comision, 0) - COALESCE(ordenes.mp_impuestos, 0), 2) AS para_vos
           FROM ordenes JOIN eventos ON eventos.id = ordenes.evento_id
           WHERE eventos.organizador_id = ? AND ordenes.estado = 'pagada'
             AND ordenes.cobro_modo = 'centralizado'
           ORDER BY ordenes.creado_en DESC LIMIT ?""",
        (organizador_id, limite),
    ).fetchall()
