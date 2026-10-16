import io
import re
import unicodedata


def slugify(texto):
    texto = unicodedata.normalize("NFKD", texto).encode("ascii", "ignore").decode("ascii")
    texto = texto.lower().strip()
    texto = re.sub(r"[^a-z0-9]+", "-", texto).strip("-")
    return texto or "evento"


def hoy_argentina():
    """Fecha de hoy en hora de Argentina (las fechas de la base están en UTC)."""
    from datetime import datetime, timedelta

    return (datetime.utcnow() - timedelta(hours=3)).date()


def rango_fechas(args, dias=30):
    """Lee ?desde=AAAA-MM-DD&hasta=AAAA-MM-DD de la URL. Por defecto, los últimos
    `dias` días hasta hoy. Devuelve (desde, hasta) como textos AAAA-MM-DD."""
    from datetime import datetime, timedelta

    hasta = hoy_argentina()
    desde = hasta - timedelta(days=dias - 1)
    try:
        if args.get("desde"):
            desde = datetime.strptime(args["desde"], "%Y-%m-%d").date()
        if args.get("hasta"):
            hasta = datetime.strptime(args["hasta"], "%Y-%m-%d").date()
    except ValueError:
        pass
    if desde > hasta:
        desde, hasta = hasta, desde
    return desde.isoformat(), hasta.isoformat()


def serie_por_dia(filas, desde, hasta, campo):
    """Completa con ceros los días sin datos, para que el gráfico muestre todo el
    período. `filas` trae 'dia' (AAAA-MM-DD) y `campo`."""
    from datetime import date, timedelta

    valores = {f["dia"]: f[campo] or 0 for f in filas}
    d, fin = date.fromisoformat(desde), date.fromisoformat(hasta)
    serie = []
    while d <= fin:
        serie.append({"dia": d.isoformat(), "valor": round(valores.get(d.isoformat(), 0), 2)})
        d += timedelta(days=1)
    return serie


def generar_qr_png_bytes(data):
    """Genera un QR con el texto/código dado y lo devuelve como bytes PNG. Import
    local: `qrcode` recién hace falta cuando se pide una imagen (no rompe la app si
    todavía no está instalado)."""
    import qrcode

    imagen = qrcode.make(data)
    buffer = io.BytesIO()
    imagen.save(buffer, format="PNG")
    return buffer.getvalue()
