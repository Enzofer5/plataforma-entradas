"""Envío del mail con las entradas (QR incluido) al comprador, cuando se confirma un
pago. Usa solo smtplib/email (librería estándar): no hace falta instalar nada nuevo.

Si no hay SMTP configurado (SMTP_HOST/SMTP_USER/SMTP_PASSWORD vacíos), no hace nada:
el comprador igual ve sus entradas en la confirmación, así que un mail que no se manda
nunca tiene que romper la confirmación del pago. Por eso además se manda en segundo
plano: si el servidor de correo tarda, el comprador no espera.
"""

import html
import smtplib
import threading
from datetime import datetime
from email.mime.image import MIMEImage
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.utils import formataddr, parseaddr

from .utils import generar_qr_png_bytes

_MESES = ["enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto",
          "septiembre", "octubre", "noviembre", "diciembre"]
_DIAS = ["Lunes", "Martes", "Miércoles", "Jueves", "Viernes", "Sábado", "Domingo"]


def smtp_configurado(app):
    return bool(
        app.config.get("SMTP_HOST") and app.config.get("SMTP_USER") and app.config.get("SMTP_PASSWORD")
    )


def _fecha_texto(valor):
    try:
        f = datetime.strptime(valor, "%Y-%m-%d")
    except (TypeError, ValueError):
        return valor or ""
    return f"{_DIAS[f.weekday()]} {f.day} de {_MESES[f.month - 1]} de {f.year}"


def _remitente(app):
    """'Passcode <casilla@gmail.com>' si SMTP_FROM no trae un nombre."""
    valor = (app.config.get("SMTP_FROM") or "").strip()
    nombre, direccion = parseaddr(valor)
    if "@" not in direccion:
        # SMTP_FROM trae solo un nombre (ej: "Passcode"): se usa con la casilla de SMTP_USER.
        nombre, direccion = valor or nombre, app.config["SMTP_USER"]
    return formataddr((nombre or "Passcode", direccion))


def _conectar(app):
    host, puerto = app.config["SMTP_HOST"], int(app.config.get("SMTP_PORT") or 587)
    if puerto == 465:  # SSL directo (algunos proveedores lo usan en vez de STARTTLS)
        servidor = smtplib.SMTP_SSL(host, puerto, timeout=20)
    else:
        servidor = smtplib.SMTP(host, puerto, timeout=20)
        servidor.starttls()
    servidor.login(app.config["SMTP_USER"], app.config["SMTP_PASSWORD"])
    return servidor


def enviar_entradas_por_email(app, orden, evento, entradas):
    """Manda las entradas en segundo plano. No lanza errores: si falla, queda en el
    registro de la app."""
    if not smtp_configurado(app):
        return  # no configurado todavía: no es un error, simplemente no se manda

    # Copias simples (las filas de la base no se pueden usar desde otro hilo).
    orden, evento = dict(orden), dict(evento)
    entradas = [dict(e) for e in entradas]

    def tarea():
        try:
            mensaje = armar_mail_entradas(app, orden, evento, entradas)
            with _conectar(app) as servidor:
                servidor.send_message(mensaje)
            app.logger.info("Mail de entradas enviado (orden %s)", orden["id"])
        except Exception:
            app.logger.exception("No se pudo mandar el mail de las entradas (orden %s)", orden["id"])

    if app.config.get("TESTING"):
        tarea()  # en las pruebas, en el momento
    else:
        threading.Thread(target=tarea, daemon=True).start()


def enviar_mail_de_prueba(app, destinatario):
    """Para el botón del panel del dueño: manda un mail simple y devuelve None si salió
    bien, o el texto del error para mostrarlo."""
    if not smtp_configurado(app):
        return "Falta configurar SMTP_HOST, SMTP_USER y SMTP_PASSWORD en el archivo .env."
    mensaje = MIMEText(
        "¡Funciona! Passcode ya puede mandar las entradas por mail a tus compradores.",
        "plain",
        "utf-8",
    )
    mensaje["Subject"] = "Prueba de correo · Passcode"
    mensaje["From"] = _remitente(app)
    mensaje["To"] = destinatario
    try:
        with _conectar(app) as servidor:
            servidor.send_message(mensaje)
    except smtplib.SMTPAuthenticationError:
        return ("El servidor de correo rechazó el usuario o la contraseña. Con Gmail hay que "
                "usar una contraseña de aplicación, no la contraseña normal.")
    except Exception as exc:  # red, host mal escrito, puerto, etc.
        return f"No se pudo conectar al servidor de correo: {exc}"
    return None


def armar_mail_entradas(app, orden, evento, entradas):
    base_url = app.config["BASE_URL"].rstrip("/")
    e = html.escape  # todo lo que escribe el usuario se escapa antes de ir al HTML

    raiz = MIMEMultipart("mixed")
    raiz["Subject"] = f"🎟️ Tus entradas para {evento['nombre']}"
    raiz["From"] = _remitente(app)
    raiz["To"] = orden["comprador_email"]

    alternativa = MIMEMultipart("alternative")
    raiz.attach(alternativa)

    fecha = _fecha_texto(evento["fecha"]) + (f" · {evento['hora']} hs" if evento.get("hora") else "")

    # ---- Versión texto (para clientes de correo sin HTML)
    lineas = [f"¡Hola {orden['comprador_nombre']}!", "",
              f"Acá están tus entradas para {evento['nombre']}.", f"{fecha} · {evento['lugar']}", ""]
    for entrada in entradas:
        lineas.append(f"- {entrada['tipo_nombre']}: {base_url}/entrada/{entrada['codigo_unico']}")
    lineas += ["", "Mostrá el QR de cada entrada en la puerta. Cada QR vale para un solo ingreso.",
               "", "Passcode · tu acceso a las mejores fiestas"]
    alternativa.attach(MIMEText("\n".join(lineas), "plain", "utf-8"))

    # ---- Versión HTML (tablas y estilos en línea: es lo que entienden los mails)
    relacionado = MIMEMultipart("related")
    alternativa.attach(relacionado)

    tarjetas = []
    for i, entrada in enumerate(entradas):
        cid = f"qr{i}@passcode"
        link = f"{base_url}/entrada/{entrada['codigo_unico']}"
        tarjetas.append(f"""
        <tr><td style="padding:0 0 18px;">
          <table role="presentation" width="100%" cellpadding="0" cellspacing="0"
                 style="background:#0b110e;border:1px solid #1e5c3a;border-radius:14px;">
            <tr><td style="padding:18px 20px 14px;">
              <div style="font-family:Arial,sans-serif;font-size:11px;letter-spacing:3px;color:#8b9a92;">ENTRADA {i + 1} DE {len(entradas)} · ADMIT ONE</div>
              <div style="font-family:Arial,sans-serif;font-size:20px;font-weight:900;color:#ffffff;margin-top:6px;">{e(entrada['tipo_nombre'])}</div>
            </td></tr>
            <tr><td style="border-top:2px dashed #1e5c3a;font-size:0;line-height:0;">&nbsp;</td></tr>
            <tr><td align="center" style="padding:18px 20px;">
              <img src="cid:{cid}" width="200" height="200" alt="Código QR de la entrada"
                   style="display:block;background:#ffffff;padding:8px;border-radius:8px;">
              <div style="font-family:'Courier New',monospace;font-size:12px;color:#8b9a92;margin-top:10px;">{e(entrada['codigo_unico'])}</div>
              <a href="{link}" style="display:inline-block;margin-top:14px;background:#2bff88;color:#03140a;
                 font-family:Arial,sans-serif;font-weight:700;font-size:14px;text-decoration:none;
                 padding:11px 22px;border-radius:8px;">Ver mi entrada</a>
            </td></tr>
          </table>
        </td></tr>""")

    cuerpo = f"""<!doctype html>
<html lang="es"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1"><meta name="color-scheme" content="dark"></head>
<body style="margin:0;padding:0;background:#050806;">
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="background:#050806;">
  <tr><td align="center" style="padding:28px 14px;">
    <table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="max-width:520px;">
      <tr><td style="padding:0 0 22px;font-family:Arial,sans-serif;font-size:24px;font-weight:900;color:#ffffff;">
        pass<span style="color:#2bff88;">code</span><span style="color:#2bff88;">_</span>
      </td></tr>
      <tr><td style="padding:0 0 6px;font-family:'Courier New',monospace;font-size:13px;color:#2bff88;">// compra confirmada</td></tr>
      <tr><td style="padding:0 0 8px;font-family:Arial,sans-serif;font-size:26px;line-height:1.15;font-weight:900;color:#ffffff;">
        ¡Hola {e(orden['comprador_nombre'])}! Acá están tus entradas.
      </td></tr>
      <tr><td style="padding:0 0 22px;font-family:Arial,sans-serif;font-size:15px;line-height:1.5;color:#c4d2ca;">
        <strong style="color:#ffffff;">{e(evento['nombre'])}</strong><br>
        {e(fecha)}<br>{e(evento['lugar'] or '')}
      </td></tr>
      {''.join(tarjetas)}
      <tr><td style="padding:4px 0 0;font-family:Arial,sans-serif;font-size:13px;line-height:1.6;color:#8b9a92;">
        Mostrá el QR de cada entrada en la puerta, desde el celular. No hace falta imprimirla.<br>
        Cada QR vale para <strong style="color:#ffffff;">un solo ingreso</strong>: no lo compartas.
      </td></tr>
      <tr><td style="padding:26px 0 0;font-family:'Courier New',monospace;font-size:11px;color:#5c6c63;">
        &gt; tu acceso a las mejores fiestas · desarrollado por <span style="color:#2bff88;">MatrixCode</span>
      </td></tr>
    </table>
  </td></tr>
</table>
</body></html>"""
    relacionado.attach(MIMEText(cuerpo, "html", "utf-8"))

    for i, entrada in enumerate(entradas):
        png = generar_qr_png_bytes(entrada["codigo_unico"])
        en_linea = MIMEImage(png, _subtype="png")
        en_linea.add_header("Content-ID", f"<qr{i}@passcode>")
        en_linea.add_header("Content-Disposition", "inline")
        relacionado.attach(en_linea)

        adjunto = MIMEImage(png, _subtype="png")
        adjunto.add_header("Content-Disposition", "attachment",
                           filename=f"entrada-{i + 1}-{entrada['tipo_nombre'][:20]}.png")
        raiz.attach(adjunto)

    return raiz
