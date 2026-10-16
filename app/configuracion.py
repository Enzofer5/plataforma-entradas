"""Configuración de la plataforma guardada en la base (no en archivos), para poder
cambiarla desde el panel del dueño sin tocar código ni reiniciar el servidor.

Recargo por servicio (lo que se queda la plataforma en cada compra): un porcentaje
sobre el precio de las entradas (ya descontado el cupón) más, opcionalmente, un monto
fijo por cada entrada paga. Se puede definir en tres niveles, y gana el más específico:

    evento  →  organizador  →  general de la plataforma

Si un nivel deja el valor vacío (NULL), se usa el del nivel siguiente.
"""

MODOS_COBRO = ("centralizado", "organizador")
RECARGO_PORCENTAJE_DEFAULT = 10.0
RECARGO_FIJO_DEFAULT = 0.0


def _leer_numero(db, clave, default):
    fila = db.execute("SELECT valor FROM configuracion WHERE clave = ?", (clave,)).fetchone()
    if fila is None:
        return default
    try:
        return float(fila["valor"])
    except (TypeError, ValueError):
        return default


def _guardar(db, clave, valor):
    db.execute(
        """INSERT INTO configuracion (clave, valor) VALUES (?, ?)
           ON CONFLICT(clave) DO UPDATE SET valor = excluded.valor""",
        (clave, str(valor)),
    )


def obtener_recargo_porcentaje(db):
    return _leer_numero(db, "recargo_porcentaje", RECARGO_PORCENTAJE_DEFAULT)


def obtener_recargo_global(db):
    return {
        "porcentaje": obtener_recargo_porcentaje(db),
        "fijo": _leer_numero(db, "recargo_fijo", RECARGO_FIJO_DEFAULT),
    }


def actualizar_recargo_global(db, porcentaje, fijo):
    _guardar(db, "recargo_porcentaje", porcentaje)
    _guardar(db, "recargo_fijo", fijo)
    db.commit()


def actualizar_recargo_porcentaje(db, porcentaje):
    _guardar(db, "recargo_porcentaje", porcentaje)
    db.commit()


def recargo_para_evento(db, evento):
    """Recargo que corresponde a un evento: {'porcentaje', 'fijo', 'origen'}.
    `origen` dice de qué nivel salió cada valor ('evento', 'organizador' o 'general')."""
    organizador = db.execute(
        "SELECT recargo_porcentaje, recargo_fijo FROM organizadores WHERE id = ?",
        (evento["organizador_id"],),
    ).fetchone()
    general = obtener_recargo_global(db)

    def elegir(campo):
        if evento[f"recargo_{campo}"] is not None:
            return evento[f"recargo_{campo}"], "evento"
        if organizador is not None and organizador[f"recargo_{campo}"] is not None:
            return organizador[f"recargo_{campo}"], "organizador"
        return general[campo], "general"

    porcentaje, origen_porcentaje = elegir("porcentaje")
    fijo, origen_fijo = elegir("fijo")
    return {
        "porcentaje": porcentaje,
        "fijo": fijo,
        "origen": {"porcentaje": origen_porcentaje, "fijo": origen_fijo},
    }


def calcular_recargo(recargo, base, entradas_pagas):
    """Monto del recargo para una compra. `base` es el precio de las entradas ya
    descontado el cupón; `entradas_pagas` cuántas entradas con precio > 0 lleva.
    Si no hay nada que cobrar (entradas gratis o cupón del 100%), no hay recargo."""
    if base <= 0:
        return 0.0
    return round(base * recargo["porcentaje"] / 100 + recargo["fijo"] * entradas_pagas, 2)


def obtener_modo_cobro(db):
    """'centralizado': todo se cobra en la cuenta de Mercado Pago de la plataforma y el
    dueño le transfiere a cada organizador. 'organizador': cada organizador conecta su
    cuenta y cobra directo (la plataforma recibe solo el recargo)."""
    fila = db.execute("SELECT valor FROM configuracion WHERE clave = 'modo_cobro'").fetchone()
    return fila["valor"] if fila and fila["valor"] in MODOS_COBRO else "centralizado"


def actualizar_modo_cobro(db, modo):
    if modo not in MODOS_COBRO:
        raise ValueError(modo)
    _guardar(db, "modo_cobro", modo)
    db.commit()


def describir_recargo(porcentaje, fijo):
    """'10%', '$500 por entrada' o '8% + $300 por entrada'."""
    partes = []
    if porcentaje:
        partes.append(f"{porcentaje:g}%")
    if fijo:
        partes.append(f"${fijo:,.0f}".replace(",", ".") + " por entrada")
    return " + ".join(partes) or "sin recargo"
