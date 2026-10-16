import csv
import io
import os
import re
import uuid
from datetime import datetime

from flask import (
    Response,
    abort,
    current_app,
    flash,
    g,
    redirect,
    render_template,
    request,
    url_for,
)

from ..auth.routes import login_required
from ..configuracion import obtener_modo_cobro
from ..cupones import TIPOS as TIPOS_CUPON
from ..cupones import describir as describir_cupon
from ..cupones import normalizar_codigo
from ..db import get_db, now_iso
from ..liquidaciones import saldo_de
from ..utils import rango_fechas, serie_por_dia, slugify
from . import eventos_bp

# Imágenes de portada que sube el organizador. Quedan en app/static/uploads/eventos/
# (esa carpeta no se sube a git).
CARPETA_IMAGENES = os.path.join("uploads", "eventos")
FORMATOS_IMAGEN = {"JPEG": "jpg", "PNG": "png", "WEBP": "webp", "GIF": "gif"}


def _guardar_imagen_subida(archivo):
    """Guarda la imagen subida y devuelve (url, None), o (None, error). Si no se subió
    ningún archivo devuelve (None, None). Se verifica con Pillow que sea de verdad una
    imagen (no alcanza con mirar la extensión del nombre)."""
    if archivo is None or not archivo.filename:
        return None, None

    from PIL import Image, UnidentifiedImageError

    try:
        with Image.open(archivo.stream) as imagen:
            formato = imagen.format
            imagen.verify()
    except (UnidentifiedImageError, OSError):
        return None, "El archivo subido no es una imagen válida."

    extension = FORMATOS_IMAGEN.get(formato)
    if extension is None:
        return None, "Formato de imagen no soportado. Usá JPG, PNG, WEBP o GIF."

    carpeta = os.path.join(current_app.static_folder, CARPETA_IMAGENES)
    os.makedirs(carpeta, exist_ok=True)
    nombre = f"{uuid.uuid4().hex}.{extension}"
    archivo.stream.seek(0)
    archivo.save(os.path.join(carpeta, nombre))
    return url_for("static", filename=f"uploads/eventos/{nombre}"), None


def _imagen_url_valida(url):
    return not url or url.startswith(("http://", "https://", "/static/uploads/eventos/"))


def _evento_del_organizador_o_404(db, evento_id):
    evento = db.execute("SELECT * FROM eventos WHERE id = ?", (evento_id,)).fetchone()
    if evento is None:
        abort(404)
    if evento["organizador_id"] != g.organizador["id"]:
        abort(403)
    return evento


def _generar_slug_unico(db, nombre, evento_id=None):
    base = slugify(nombre)
    slug = base
    contador = 2
    while True:
        if evento_id:
            fila = db.execute(
                "SELECT id FROM eventos WHERE slug = ? AND id != ?", (slug, evento_id)
            ).fetchone()
        else:
            fila = db.execute("SELECT id FROM eventos WHERE slug = ?", (slug,)).fetchone()
        if not fila:
            return slug
        slug = f"{base}-{contador}"
        contador += 1


def _leer_formulario(form):
    fecha_raw = form.get("fecha", "").strip()
    hora_raw = form.get("hora", "").strip()

    if fecha_raw:
        try:
            datetime.strptime(fecha_raw, "%Y-%m-%d")
        except ValueError:
            fecha_raw = ""

    if hora_raw:
        try:
            datetime.strptime(hora_raw, "%H:%M")
        except ValueError:
            hora_raw = ""

    return {
        "nombre": form.get("nombre", "").strip(),
        "descripcion": form.get("descripcion", "").strip(),
        "fecha": fecha_raw,
        "hora": hora_raw,
        "lugar": form.get("lugar", "").strip(),
        "imagen_url": form.get("imagen_url", "").strip(),
    }


def _validar_formulario(datos):
    if not datos["nombre"]:
        return "El evento necesita un nombre."
    if not datos["fecha"]:
        return "Ingresá una fecha válida (AAAA-MM-DD)."
    if not datos["lugar"]:
        return "Ingresá el lugar del evento."
    if not _imagen_url_valida(datos["imagen_url"]):
        return "El link de la imagen tiene que empezar con http:// o https://."
    return None


def _procesar_imagen(datos):
    """Si se subió una imagen, reemplaza el link por la imagen subida. Devuelve un
    mensaje de error o None."""
    url, error = _guardar_imagen_subida(request.files.get("imagen"))
    if error:
        return error
    if url:
        datos["imagen_url"] = url
    return None


@eventos_bp.route("/eventos")
@login_required
def listado():
    db = get_db()
    eventos = db.execute(
        """SELECT eventos.*,
                  (SELECT COALESCE(SUM(stock_vendido), 0) FROM tipos_entrada
                   WHERE tipos_entrada.evento_id = eventos.id) AS vendidas,
                  (SELECT COALESCE(SUM(stock_total), 0) FROM tipos_entrada
                   WHERE tipos_entrada.evento_id = eventos.id) AS stock_total,
                  (SELECT COALESCE(SUM(COALESCE(subtotal, total) - COALESCE(descuento, 0)), 0)
                   FROM ordenes WHERE ordenes.evento_id = eventos.id
                     AND ordenes.estado = 'pagada') AS recaudado
           FROM eventos WHERE organizador_id = ? ORDER BY fecha DESC""",
        (g.organizador["id"],),
    ).fetchall()
    totales = {
        "eventos": len(eventos),
        "publicados": sum(1 for e in eventos if e["estado"] == "publicado"),
        "vendidas": sum(e["vendidas"] for e in eventos),
        "recaudado": sum(e["recaudado"] for e in eventos),
    }
    return render_template("eventos/listado.html", eventos=eventos, totales=totales)


@eventos_bp.route("/eventos/<int:evento_id>")
@login_required
def detalle(evento_id):
    """Panel de un evento: estado, métricas y accesos a todo lo que se puede hacer
    con él (entradas, cupones, reporte, validar, editar...)."""
    db = get_db()
    evento = _evento_del_organizador_o_404(db, evento_id)
    tipos = db.execute(
        "SELECT * FROM tipos_entrada WHERE evento_id = ? ORDER BY id", (evento_id,)
    ).fetchall()
    stats = db.execute(
        """SELECT COUNT(*) AS compras,
                  COALESCE(SUM(COALESCE(subtotal, total) - COALESCE(descuento, 0)), 0) AS recaudado
           FROM ordenes WHERE evento_id = ? AND estado = 'pagada'""",
        (evento_id,),
    ).fetchone()
    usadas = db.execute(
        """SELECT COUNT(*) FROM entradas
           JOIN tipos_entrada ON tipos_entrada.id = entradas.tipo_entrada_id
           WHERE tipos_entrada.evento_id = ? AND entradas.estado = 'usada'""",
        (evento_id,),
    ).fetchone()[0]
    cupones_activos = db.execute(
        "SELECT COUNT(*) FROM cupones WHERE evento_id = ? AND activo = 1", (evento_id,)
    ).fetchone()[0]
    return render_template(
        "eventos/detalle.html",
        evento=evento,
        tipos=tipos,
        vendidas=sum(t["stock_vendido"] for t in tipos),
        stock_total=sum(t["stock_total"] for t in tipos),
        compras=stats["compras"],
        recaudado=stats["recaudado"],
        usadas=usadas,
        cupones_activos=cupones_activos,
    )


@eventos_bp.route("/eventos/nuevo", methods=["GET", "POST"])
@login_required
def nuevo():
    if request.method == "POST":
        datos = _leer_formulario(request.form)
        error = _validar_formulario(datos) or _procesar_imagen(datos)
        if error:
            flash(error, "danger")
            return render_template("eventos/form.html", evento=None, datos=datos)

        db = get_db()
        slug = _generar_slug_unico(db, datos["nombre"])
        cursor = db.execute(
            """INSERT INTO eventos
               (organizador_id, nombre, slug, descripcion, fecha, hora, lugar, imagen_url, estado, creado_en)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'borrador', ?)""",
            (
                g.organizador["id"],
                datos["nombre"],
                slug,
                datos["descripcion"],
                datos["fecha"],
                datos["hora"] or None,
                datos["lugar"],
                datos["imagen_url"] or None,
                now_iso(),
            ),
        )
        db.commit()
        flash("Evento creado. Ahora agregá los tipos de entrada.", "success")
        return redirect(url_for("eventos.tipos_entrada", evento_id=cursor.lastrowid))

    return render_template("eventos/form.html", evento=None, datos=None)


@eventos_bp.route("/eventos/<int:evento_id>/editar", methods=["GET", "POST"])
@login_required
def editar(evento_id):
    db = get_db()
    evento = _evento_del_organizador_o_404(db, evento_id)

    if request.method == "POST":
        datos = _leer_formulario(request.form)
        error = _validar_formulario(datos) or _procesar_imagen(datos)
        if error:
            flash(error, "danger")
            return render_template("eventos/form.html", evento=evento, datos=datos)

        slug = evento["slug"]
        if datos["nombre"] != evento["nombre"]:
            slug = _generar_slug_unico(db, datos["nombre"], evento_id=evento_id)

        db.execute(
            """UPDATE eventos SET nombre = ?, slug = ?, descripcion = ?, fecha = ?, hora = ?,
               lugar = ?, imagen_url = ? WHERE id = ?""",
            (
                datos["nombre"],
                slug,
                datos["descripcion"],
                datos["fecha"],
                datos["hora"] or None,
                datos["lugar"],
                datos["imagen_url"] or None,
                evento_id,
            ),
        )
        db.commit()
        flash("Evento actualizado.", "success")
        return redirect(url_for("eventos.detalle", evento_id=evento_id))

    return render_template("eventos/form.html", evento=evento, datos=None)


@eventos_bp.route("/eventos/<int:evento_id>/publicar", methods=["POST"])
@login_required
def publicar(evento_id):
    db = get_db()
    evento = _evento_del_organizador_o_404(db, evento_id)

    if evento["estado"] == "publicado":
        db.execute("UPDATE eventos SET estado = 'borrador' WHERE id = ?", (evento_id,))
        db.commit()
        flash("Evento pasado a borrador (ya no es visible al público).", "info")
    elif evento["bloqueado"]:
        flash(
            "Este evento fue pausado por la plataforma y no se puede publicar. "
            "Escribinos para saber más.",
            "danger",
        )
    else:
        tiene_tipos = db.execute(
            "SELECT id FROM tipos_entrada WHERE evento_id = ? LIMIT 1", (evento_id,)
        ).fetchone()
        if not tiene_tipos:
            flash("Agregá al menos un tipo de entrada antes de publicar.", "warning")
            return redirect(url_for("eventos.tipos_entrada", evento_id=evento_id))

        tiene_pagas = db.execute(
            "SELECT id FROM tipos_entrada WHERE evento_id = ? AND precio > 0 LIMIT 1",
            (evento_id,),
        ).fetchone()
        if (
            tiene_pagas
            and obtener_modo_cobro(db) == "organizador"
            and not g.organizador["mp_access_token"]
        ):
            flash(
                "Conectá tu cuenta de Mercado Pago antes de publicar un evento con "
                "entradas pagas — así la plata te llega directo a vos.",
                "warning",
            )
            return redirect(url_for("auth.cuenta"))

        db.execute("UPDATE eventos SET estado = 'publicado' WHERE id = ?", (evento_id,))
        db.commit()
        flash("¡Evento publicado! Ya es visible en la página pública.", "success")

    return redirect(url_for("eventos.detalle", evento_id=evento_id))


@eventos_bp.route("/eventos/<int:evento_id>/tipos-entrada", methods=["GET", "POST"])
@login_required
def tipos_entrada(evento_id):
    db = get_db()
    evento = _evento_del_organizador_o_404(db, evento_id)

    if request.method == "POST":
        nombre = request.form.get("nombre", "").strip()
        precio_raw = request.form.get("precio", "").strip()
        stock_raw = request.form.get("stock", "").strip()

        error = None
        precio_val = stock_val = None
        if not nombre:
            error = "El tipo de entrada necesita un nombre."
        else:
            try:
                precio_val = float(precio_raw)
                stock_val = int(stock_raw)
                if precio_val < 0 or stock_val < 1:
                    raise ValueError
            except ValueError:
                error = "Precio y stock tienen que ser números válidos (stock mínimo 1)."

        if error:
            flash(error, "danger")
        else:
            db.execute(
                """INSERT INTO tipos_entrada (evento_id, nombre, precio, stock_total, stock_vendido)
                   VALUES (?, ?, ?, ?, 0)""",
                (evento_id, nombre, precio_val, stock_val),
            )
            db.commit()
            flash("Tipo de entrada agregado.", "success")

        return redirect(url_for("eventos.tipos_entrada", evento_id=evento_id))

    tipos = db.execute(
        "SELECT * FROM tipos_entrada WHERE evento_id = ? ORDER BY id", (evento_id,)
    ).fetchall()
    return render_template("eventos/tipos_entrada.html", evento=evento, tipos=tipos)


@eventos_bp.route(
    "/eventos/<int:evento_id>/tipos-entrada/<int:tipo_id>/eliminar", methods=["POST"]
)
@login_required
def eliminar_tipo_entrada(evento_id, tipo_id):
    db = get_db()
    _evento_del_organizador_o_404(db, evento_id)

    tipo = db.execute(
        "SELECT * FROM tipos_entrada WHERE id = ? AND evento_id = ?", (tipo_id, evento_id)
    ).fetchone()
    if tipo is None:
        abort(404)

    if tipo["stock_vendido"] > 0:
        flash("No se puede eliminar un tipo de entrada que ya tiene ventas.", "danger")
    else:
        db.execute("DELETE FROM tipos_entrada WHERE id = ?", (tipo_id,))
        db.commit()
        flash("Tipo de entrada eliminado.", "info")

    return redirect(url_for("eventos.tipos_entrada", evento_id=evento_id))


def _buscar_entrada_por_codigo(db, evento_id, texto):
    """Busca la entrada aceptando el código como lo escriban: con o sin guiones,
    en mayúsculas o minúsculas, con espacios, el link completo de la entrada o solo
    el principio del código (mínimo 6 caracteres, si no hay otra que empiece igual).
    Devuelve (entrada, ambiguo)."""
    texto = (texto or "").strip().lower()
    if "/entrada/" in texto:
        texto = texto.split("/entrada/", 1)[1].split("?")[0].split("/")[0]
    limpio = re.sub(r"[^0-9a-z]", "", texto)
    if len(limpio) < 6:
        return None, False
    base = """SELECT entradas.*, tipos_entrada.nombre AS tipo_nombre, tipos_entrada.evento_id
              FROM entradas JOIN tipos_entrada ON tipos_entrada.id = entradas.tipo_entrada_id
              WHERE REPLACE(LOWER(entradas.codigo_unico), '-', '') """
    exacta = db.execute(base + "= ?", (limpio,)).fetchone()
    if exacta is not None:
        return exacta, False
    candidatas = db.execute(
        base + "LIKE ? AND tipos_entrada.evento_id = ? LIMIT 2", (limpio + "%", evento_id)
    ).fetchall()
    if len(candidatas) == 1:
        return candidatas[0], False
    return None, len(candidatas) > 1


@eventos_bp.route("/eventos/<int:evento_id>/validar", methods=["GET", "POST"])
@login_required
def validar(evento_id):
    db = get_db()
    evento = _evento_del_organizador_o_404(db, evento_id)

    resultado = None
    if request.method == "POST":
        codigo = request.form.get("codigo", "").strip()
        entrada, ambiguo = _buscar_entrada_por_codigo(db, evento_id, codigo)
        if not codigo:
            resultado = {"ok": False, "mensaje": "Ingresá o escaneá un código."}
        elif ambiguo:
            resultado = {"ok": False, "mensaje": "Hay más de una entrada que empieza así: escribí unos caracteres más del código."}
        elif entrada is None or entrada["evento_id"] != evento_id:
            resultado = {"ok": False, "mensaje": "Ese código no corresponde a este evento."}
        elif entrada["estado"] == "usada":
            resultado = {
                "ok": False,
                "mensaje": "Esta entrada ya fue validada antes.",
                "tipo_nombre": entrada["tipo_nombre"],
            }
        else:
            db.execute(
                "UPDATE entradas SET estado = 'usada', usada_en = ? WHERE id = ?",
                (now_iso(), entrada["id"]),
            )
            db.commit()
            resultado = {
                "ok": True,
                "mensaje": "¡Entrada válida! Acceso permitido.",
                "tipo_nombre": entrada["tipo_nombre"],
            }

    stats = db.execute(
        """SELECT
             COUNT(*) AS total,
             SUM(CASE WHEN entradas.estado = 'usada' THEN 1 ELSE 0 END) AS usadas
           FROM entradas
           JOIN tipos_entrada ON tipos_entrada.id = entradas.tipo_entrada_id
           WHERE tipos_entrada.evento_id = ?""",
        (evento_id,),
    ).fetchone()

    return render_template(
        "eventos/validar.html", evento=evento, resultado=resultado, stats=stats
    )


# ------------------------------------------------------------------ Cupones


def _leer_cupon(form):
    """Lee y valida el formulario de cupón. Devuelve (datos, None) o (None, error)."""
    codigo = normalizar_codigo(form.get("codigo"))
    tipo = form.get("tipo", "porcentaje")
    valor_raw = form.get("valor", "").strip()
    usos_raw = form.get("usos_maximos", "").strip()
    vence_raw = form.get("vence_en", "").strip()

    if not re.fullmatch(r"[A-Z0-9_-]{3,30}", codigo):
        return None, "El código tiene que tener entre 3 y 30 letras, números, - o _ (sin espacios)."
    if tipo not in TIPOS_CUPON:
        return None, "Tipo de descuento inválido."
    try:
        valor = float(valor_raw)
        if valor <= 0 or (tipo == "porcentaje" and valor > 100):
            raise ValueError
    except ValueError:
        return None, "El descuento tiene que ser un número mayor a 0 (y hasta 100 si es porcentaje)."

    usos_maximos = None
    if usos_raw:
        try:
            usos_maximos = int(usos_raw)
            if usos_maximos < 1:
                raise ValueError
        except ValueError:
            return None, "El límite de usos tiene que ser un número entero mayor a 0."

    vence_en = None
    if vence_raw:
        try:
            datetime.strptime(vence_raw, "%Y-%m-%d")
        except ValueError:
            return None, "Fecha de vencimiento inválida."
        vence_en = vence_raw

    return {
        "codigo": codigo,
        "tipo": tipo,
        "valor": valor,
        "usos_maximos": usos_maximos,
        "vence_en": vence_en,
    }, None


def _cupon_del_evento_o_404(db, evento_id, cupon_id):
    cupon = db.execute(
        "SELECT * FROM cupones WHERE id = ? AND evento_id = ?", (cupon_id, evento_id)
    ).fetchone()
    if cupon is None:
        abort(404)
    return cupon


@eventos_bp.route("/eventos/<int:evento_id>/cupones", methods=["GET", "POST"])
@login_required
def cupones(evento_id):
    db = get_db()
    evento = _evento_del_organizador_o_404(db, evento_id)

    if request.method == "POST":
        datos, error = _leer_cupon(request.form)
        if not error and db.execute(
            "SELECT id FROM cupones WHERE evento_id = ? AND codigo = ?",
            (evento_id, datos["codigo"]),
        ).fetchone():
            error = f'Ya existe un cupón "{datos["codigo"]}" para este evento.'

        if error:
            flash(error, "danger")
        else:
            db.execute(
                """INSERT INTO cupones
                   (evento_id, codigo, tipo, valor, usos_maximos, usos, vence_en, activo, creado_en)
                   VALUES (?, ?, ?, ?, ?, 0, ?, 1, ?)""",
                (
                    evento_id,
                    datos["codigo"],
                    datos["tipo"],
                    datos["valor"],
                    datos["usos_maximos"],
                    datos["vence_en"],
                    now_iso(),
                ),
            )
            db.commit()
            flash(f'Cupón {datos["codigo"]} creado.', "success")
        return redirect(url_for("eventos.cupones", evento_id=evento_id))

    lista = db.execute(
        """SELECT cupones.*,
                  COALESCE((SELECT SUM(ordenes.descuento) FROM ordenes
                            WHERE ordenes.cupon_id = cupones.id
                              AND ordenes.estado = 'pagada'), 0) AS descuento_total
           FROM cupones WHERE evento_id = ? ORDER BY id DESC""",
        (evento_id,),
    ).fetchall()
    return render_template(
        "eventos/cupones.html",
        evento=evento,
        cupones=lista,
        describir_cupon=describir_cupon,
        hoy=datetime.now().strftime("%Y-%m-%d"),
    )


@eventos_bp.route("/eventos/<int:evento_id>/cupones/<int:cupon_id>/activar", methods=["POST"])
@login_required
def activar_cupon(evento_id, cupon_id):
    db = get_db()
    _evento_del_organizador_o_404(db, evento_id)
    cupon = _cupon_del_evento_o_404(db, evento_id, cupon_id)
    db.execute(
        "UPDATE cupones SET activo = ? WHERE id = ?", (0 if cupon["activo"] else 1, cupon_id)
    )
    db.commit()
    estado = "desactivado" if cupon["activo"] else "activado"
    flash(f'Cupón {cupon["codigo"]} {estado}.', "info")
    return redirect(url_for("eventos.cupones", evento_id=evento_id))


@eventos_bp.route("/eventos/<int:evento_id>/cupones/<int:cupon_id>/eliminar", methods=["POST"])
@login_required
def eliminar_cupon(evento_id, cupon_id):
    db = get_db()
    _evento_del_organizador_o_404(db, evento_id)
    cupon = _cupon_del_evento_o_404(db, evento_id, cupon_id)
    if cupon["usos"] > 0:
        flash(
            "Este cupón ya se usó en compras, así que no se puede eliminar (queda en los "
            "reportes). Podés desactivarlo para que no se use más.",
            "warning",
        )
    else:
        db.execute("DELETE FROM cupones WHERE id = ?", (cupon_id,))
        db.commit()
        flash(f'Cupón {cupon["codigo"]} eliminado.', "info")
    return redirect(url_for("eventos.cupones", evento_id=evento_id))


# ----------------------------------------------------------------- Reportes

# Las fechas se guardan en UTC; para agrupar por día se pasan a hora de Argentina.
_DIA_LOCAL = "date(ordenes.creado_en, '-3 hours')"


def _datos_reporte(db, evento_id):
    resumen = db.execute(
        """SELECT COUNT(*) AS ordenes,
                  COALESCE(SUM(COALESCE(subtotal, total)), 0) AS bruto,
                  COALESCE(SUM(COALESCE(descuento, 0)), 0) AS descuentos,
                  COALESCE(SUM(COALESCE(recargo_total, 0)), 0) AS recargos,
                  COALESCE(SUM(total), 0) AS cobrado
           FROM ordenes WHERE evento_id = ? AND estado = 'pagada'""",
        (evento_id,),
    ).fetchone()

    entradas = db.execute(
        """SELECT COUNT(*) AS vendidas,
                  COALESCE(SUM(CASE WHEN entradas.estado = 'usada' THEN 1 ELSE 0 END), 0) AS usadas
           FROM entradas
           JOIN tipos_entrada ON tipos_entrada.id = entradas.tipo_entrada_id
           WHERE tipos_entrada.evento_id = ?""",
        (evento_id,),
    ).fetchone()

    por_tipo = db.execute(
        """SELECT tipos_entrada.nombre, tipos_entrada.precio, tipos_entrada.stock_total,
                  tipos_entrada.stock_vendido,
                  COALESCE((SELECT SUM(orden_items.cantidad * orden_items.precio_unitario)
                            FROM orden_items JOIN ordenes ON ordenes.id = orden_items.orden_id
                            WHERE orden_items.tipo_entrada_id = tipos_entrada.id
                              AND ordenes.estado = 'pagada'), 0) AS recaudado,
                  (SELECT COUNT(*) FROM entradas
                   WHERE entradas.tipo_entrada_id = tipos_entrada.id
                     AND entradas.estado = 'usada') AS ingresaron
           FROM tipos_entrada WHERE evento_id = ? ORDER BY tipos_entrada.id""",
        (evento_id,),
    ).fetchall()

    por_dia = db.execute(
        f"""SELECT {_DIA_LOCAL} AS dia,
                   SUM((SELECT SUM(cantidad) FROM orden_items
                        WHERE orden_items.orden_id = ordenes.id)) AS entradas,
                   SUM(COALESCE(subtotal, total) - COALESCE(descuento, 0)) AS monto
            FROM ordenes WHERE evento_id = ? AND estado = 'pagada'
            GROUP BY dia ORDER BY dia""",
        (evento_id,),
    ).fetchall()

    cupones_usados = db.execute(
        """SELECT cupones.codigo, COUNT(ordenes.id) AS usos,
                  COALESCE(SUM(ordenes.descuento), 0) AS descuento_total
           FROM ordenes JOIN cupones ON cupones.id = ordenes.cupon_id
           WHERE ordenes.evento_id = ? AND ordenes.estado = 'pagada'
           GROUP BY cupones.id ORDER BY usos DESC""",
        (evento_id,),
    ).fetchall()

    return {
        "resumen": resumen,
        "neto": resumen["bruto"] - resumen["descuentos"],
        "entradas": entradas,
        "stock_total": sum(t["stock_total"] for t in por_tipo),
        "por_tipo": por_tipo,
        "por_dia": por_dia,
        "cupones_usados": cupones_usados,
    }


def _ordenes_pagadas(db, evento_id):
    return db.execute(
        f"""SELECT ordenes.*, {_DIA_LOCAL} AS dia_local,
                   time(ordenes.creado_en, '-3 hours') AS hora_local,
                   cupones.codigo AS cupon_codigo,
                   (SELECT GROUP_CONCAT(orden_items.cantidad || 'x ' || tipos_entrada.nombre, ', ')
                    FROM orden_items
                    JOIN tipos_entrada ON tipos_entrada.id = orden_items.tipo_entrada_id
                    WHERE orden_items.orden_id = ordenes.id) AS detalle,
                   (SELECT SUM(cantidad) FROM orden_items
                    WHERE orden_items.orden_id = ordenes.id) AS cantidad
            FROM ordenes LEFT JOIN cupones ON cupones.id = ordenes.cupon_id
            WHERE ordenes.evento_id = ? AND ordenes.estado = 'pagada'
            ORDER BY ordenes.creado_en DESC""",
        (evento_id,),
    ).fetchall()


@eventos_bp.route("/eventos/<int:evento_id>/reporte")
@login_required
def reporte(evento_id):
    db = get_db()
    evento = _evento_del_organizador_o_404(db, evento_id)
    return render_template(
        "eventos/reporte.html",
        evento=evento,
        ordenes=_ordenes_pagadas(db, evento_id),
        **_datos_reporte(db, evento_id),
    )


@eventos_bp.route("/eventos/<int:evento_id>/reporte.csv")
@login_required
def reporte_csv(evento_id):
    db = get_db()
    evento = _evento_del_organizador_o_404(db, evento_id)

    salida = io.StringIO()
    # ";" como separador: es lo que espera Excel con configuración regional de Argentina.
    writer = csv.writer(salida, delimiter=";")
    writer.writerow(
        [
            "Orden", "Fecha", "Hora", "Comprador", "Email", "DNI", "Entradas", "Cantidad",
            "Subtotal", "Cupón", "Descuento", "Neto organizador", "Cargo por servicio",
            "Total pagado",
        ]
    )

    def numero(valor):
        return f"{(valor or 0):.2f}".replace(".", ",")

    for orden in _ordenes_pagadas(db, evento_id):
        subtotal = orden["subtotal"] if orden["subtotal"] is not None else orden["total"]
        descuento = orden["descuento"] or 0
        writer.writerow(
            [
                orden["id"],
                orden["dia_local"],
                orden["hora_local"],
                orden["comprador_nombre"],
                orden["comprador_email"],
                orden["comprador_dni"] or "",
                orden["detalle"] or "",
                orden["cantidad"] or 0,
                numero(subtotal),
                orden["cupon_codigo"] or "",
                numero(descuento),
                numero(subtotal - descuento),
                numero(orden["recargo_total"]),
                numero(orden["total"]),
            ]
        )

    nombre_archivo = f"ventas-{evento['slug']}.csv"
    return Response(
        # BOM al principio para que Excel respete los acentos (UTF-8).
        "﻿" + salida.getvalue(),
        mimetype="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{nombre_archivo}"'},
    )


# ------------------------------------------------- Panel del organizador

# Ventas pagadas de los eventos del organizador logueado, con la fecha en hora local.
_MIS_VENTAS = f"""
    FROM ordenes JOIN eventos ON eventos.id = ordenes.evento_id
    WHERE eventos.organizador_id = ? AND ordenes.estado = 'pagada'
      AND {_DIA_LOCAL} BETWEEN ? AND ?
"""
_NETO = "COALESCE(ordenes.subtotal, ordenes.total) - COALESCE(ordenes.descuento, 0)"
_CANTIDAD = "(SELECT SUM(cantidad) FROM orden_items WHERE orden_items.orden_id = ordenes.id)"


@eventos_bp.route("/panel")
@login_required
def panel():
    """Dashboard del organizador: métricas del período elegido, ventas por día y
    ventas por evento."""
    db = get_db()
    oid = g.organizador["id"]
    desde, hasta = rango_fechas(request.args)
    params = (oid, desde, hasta)

    totales = db.execute(
        f"""SELECT COUNT(*) AS compras, COALESCE(SUM({_NETO}), 0) AS vendido,
                   COALESCE(SUM({_CANTIDAD}), 0) AS entradas,
                   COALESCE(SUM(CASE WHEN ordenes.cupon_id IS NOT NULL THEN 1 ELSE 0 END), 0) AS con_cupon
            {_MIS_VENTAS}""",
        params,
    ).fetchone()
    eventos = db.execute(
        """SELECT COUNT(*) AS total,
                  COALESCE(SUM(CASE WHEN estado = 'publicado' AND bloqueado = 0 THEN 1 ELSE 0 END), 0) AS publicados
           FROM eventos WHERE organizador_id = ?""",
        (oid,),
    ).fetchone()
    ingresos = db.execute(
        """SELECT COUNT(*) AS usadas FROM entradas
           JOIN tipos_entrada ON tipos_entrada.id = entradas.tipo_entrada_id
           JOIN eventos ON eventos.id = tipos_entrada.evento_id
           WHERE eventos.organizador_id = ? AND entradas.estado = 'usada'
             AND date(entradas.usada_en, '-3 hours') BETWEEN ? AND ?""",
        params,
    ).fetchone()
    por_dia = db.execute(
        f"""SELECT {_DIA_LOCAL} AS dia, SUM({_NETO}) AS monto, SUM({_CANTIDAD}) AS entradas
            {_MIS_VENTAS} GROUP BY dia""",
        params,
    ).fetchall()
    por_evento = db.execute(
        f"""SELECT eventos.id, eventos.nombre, eventos.fecha, eventos.estado, eventos.bloqueado,
                   COUNT(ordenes.id) AS compras, COALESCE(SUM({_CANTIDAD}), 0) AS entradas,
                   COALESCE(SUM({_NETO}), 0) AS vendido
            {_MIS_VENTAS} GROUP BY eventos.id ORDER BY vendido DESC""",
        params,
    ).fetchall()
    ultimas = db.execute(
        f"""SELECT ordenes.comprador_nombre, ordenes.comprador_email, eventos.nombre AS evento,
                   datetime(ordenes.creado_en, '-3 hours') AS fecha_local,
                   {_NETO} AS neto, {_CANTIDAD} AS cantidad
            {_MIS_VENTAS} ORDER BY ordenes.creado_en DESC LIMIT 8""",
        params,
    ).fetchall()

    return render_template(
        "eventos/panel.html",
        desde=desde,
        hasta=hasta,
        totales=totales,
        eventos=eventos,
        ingresos=ingresos,
        serie=serie_por_dia(por_dia, desde, hasta, "monto"),
        serie_entradas=serie_por_dia(por_dia, desde, hasta, "entradas"),
        por_evento=por_evento,
        ultimas=ultimas,
        modo_cobro=obtener_modo_cobro(db),
        saldo=saldo_de(db, oid),
    )


@eventos_bp.route("/ventas")
@login_required
def ventas():
    """Todas las compras de los eventos del organizador, con filtro por evento,
    búsqueda por comprador y rango de fechas."""
    db = get_db()
    oid = g.organizador["id"]
    desde, hasta = rango_fechas(request.args, dias=90)
    evento_id = request.args.get("evento", type=int)
    texto = request.args.get("q", "").strip().lower()

    condiciones, params = [], [oid, desde, hasta]
    if evento_id:
        condiciones.append("eventos.id = ?")
        params.append(evento_id)
    if texto:
        condiciones.append("(lower(ordenes.comprador_nombre) LIKE ? OR lower(ordenes.comprador_email) LIKE ?)")
        params += [f"%{texto}%", f"%{texto}%"]
    extra = "".join(f" AND {c}" for c in condiciones)

    lista = db.execute(
        f"""SELECT ordenes.*, eventos.nombre AS evento, eventos.id AS evento_id,
                   datetime(ordenes.creado_en, '-3 hours') AS fecha_local,
                   {_NETO} AS neto, {_CANTIDAD} AS cantidad, cupones.codigo AS cupon_codigo,
                   (SELECT GROUP_CONCAT(orden_items.cantidad || 'x ' || tipos_entrada.nombre, ', ')
                    FROM orden_items JOIN tipos_entrada ON tipos_entrada.id = orden_items.tipo_entrada_id
                    WHERE orden_items.orden_id = ordenes.id) AS detalle
            FROM ordenes JOIN eventos ON eventos.id = ordenes.evento_id
            LEFT JOIN cupones ON cupones.id = ordenes.cupon_id
            WHERE eventos.organizador_id = ? AND ordenes.estado = 'pagada'
              AND {_DIA_LOCAL} BETWEEN ? AND ?{extra}
            ORDER BY ordenes.creado_en DESC LIMIT 300""",
        params,
    ).fetchall()
    mis_eventos = db.execute(
        "SELECT id, nombre FROM eventos WHERE organizador_id = ? ORDER BY fecha DESC", (oid,)
    ).fetchall()
    return render_template(
        "eventos/ventas.html",
        ventas=lista,
        mis_eventos=mis_eventos,
        desde=desde,
        hasta=hasta,
        evento_id=evento_id,
        q=request.args.get("q", ""),
        total=sum(v["neto"] or 0 for v in lista),
        entradas=sum(v["cantidad"] or 0 for v in lista),
    )


@eventos_bp.route("/compradores")
@login_required
def compradores():
    """Compradores únicos (por email) de los eventos del organizador."""
    db = get_db()
    texto = request.args.get("q", "").strip().lower()
    params = [g.organizador["id"]]
    filtro = ""
    if texto:
        filtro = " AND (lower(ordenes.comprador_nombre) LIKE ? OR lower(ordenes.comprador_email) LIKE ?)"
        params += [f"%{texto}%", f"%{texto}%"]
    lista = db.execute(
        f"""SELECT lower(ordenes.comprador_email) AS email,
                   MAX(ordenes.comprador_nombre) AS nombre,
                   MAX(ordenes.comprador_dni) AS dni,
                   COUNT(ordenes.id) AS compras,
                   COALESCE(SUM({_CANTIDAD}), 0) AS entradas,
                   COALESCE(SUM({_NETO}), 0) AS gastado,
                   COUNT(DISTINCT ordenes.evento_id) AS eventos,
                   MAX(datetime(ordenes.creado_en, '-3 hours')) AS ultima
            FROM ordenes JOIN eventos ON eventos.id = ordenes.evento_id
            WHERE eventos.organizador_id = ? AND ordenes.estado = 'pagada'{filtro}
            GROUP BY lower(ordenes.comprador_email)
            ORDER BY gastado DESC LIMIT 500""",
        params,
    ).fetchall()
    return render_template("eventos/compradores.html", compradores=lista, q=request.args.get("q", ""))


@eventos_bp.route("/ingreso")
@login_required
def ingreso():
    """Control de ingreso: elegir el evento para validar entradas en la puerta."""
    db = get_db()
    lista = db.execute(
        """SELECT eventos.*,
                  (SELECT COUNT(*) FROM entradas JOIN tipos_entrada ON tipos_entrada.id = entradas.tipo_entrada_id
                   WHERE tipos_entrada.evento_id = eventos.id) AS vendidas,
                  (SELECT COUNT(*) FROM entradas JOIN tipos_entrada ON tipos_entrada.id = entradas.tipo_entrada_id
                   WHERE tipos_entrada.evento_id = eventos.id AND entradas.estado = 'usada') AS usadas
           FROM eventos WHERE organizador_id = ? ORDER BY fecha DESC""",
        (g.organizador["id"],),
    ).fetchall()
    return render_template("eventos/ingreso.html", eventos=lista)


@eventos_bp.route("/cupones")
@login_required
def cupones_inicio():
    """Cupones: elegir el evento para administrar sus códigos de descuento."""
    db = get_db()
    lista = db.execute(
        """SELECT eventos.*,
                  (SELECT COUNT(*) FROM cupones WHERE cupones.evento_id = eventos.id) AS cupones,
                  (SELECT COUNT(*) FROM cupones WHERE cupones.evento_id = eventos.id AND activo = 1) AS activos,
                  (SELECT COALESCE(SUM(usos), 0) FROM cupones WHERE cupones.evento_id = eventos.id) AS usos
           FROM eventos WHERE organizador_id = ? ORDER BY fecha DESC""",
        (g.organizador["id"],),
    ).fetchall()
    return render_template("eventos/cupones_inicio.html", eventos=lista)
