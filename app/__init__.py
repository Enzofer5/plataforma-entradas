import os
from datetime import datetime

from flask import Flask, flash, redirect, request

from . import db as db_module


def _version_estaticos(app):
    try:
        return int(os.path.getmtime(os.path.join(app.static_folder, "css", "estilo.css")))
    except OSError:
        return 0


def create_app(config_object="config.Config"):
    app = Flask(__name__, instance_relative_config=True)
    app.config.from_object(config_object)

    os.makedirs(app.instance_path, exist_ok=True)
    os.makedirs(os.path.dirname(app.config["DATABASE_PATH"]), exist_ok=True)

    db_module.init_app(app)

    from .configuracion import describir_recargo

    app.jinja_env.globals["describir_recargo"] = describir_recargo

    @app.context_processor
    def contexto_global():
        """Datos disponibles en todas las plantillas."""
        from .configuracion import obtener_modo_cobro
        from .db import get_db

        try:
            simulacion = (
                obtener_modo_cobro(get_db()) == "centralizado"
                and not app.config.get("MP_ACCESS_TOKEN")
            )
        except Exception:  # la base todavía no está lista (no debería pasar)
            simulacion = False
        return {
            "modo_simulacion": simulacion,
            "anio_actual": datetime.now().year,
            # Cambia cuando cambian los estilos: así el navegador no usa una versión vieja.
            "version_estaticos": _version_estaticos(app),
        }

    @app.errorhandler(413)
    def archivo_muy_grande(error):
        flash("La imagen es muy pesada: el máximo es 5 MB.", "danger")
        return redirect(request.url)

    @app.template_filter("pesos")
    def pesos(valor):
        """1234.5 -> '$1.234,50' (formato argentino). Sin decimales si es redondo."""
        valor = float(valor or 0)
        texto = f"{valor:,.0f}" if valor == int(valor) else f"{valor:,.2f}"
        return "$" + texto.replace(",", "X").replace(".", ",").replace("X", ".")

    @app.template_filter("fecha_larga")
    def fecha_larga(valor):
        """'2026-10-18' -> {'dia': '18', 'mes': 'OCT', 'semana': 'Sáb'} para las tarjetas."""
        try:
            fecha = datetime.strptime(valor, "%Y-%m-%d")
        except (TypeError, ValueError):
            return None
        meses = ["ENE", "FEB", "MAR", "ABR", "MAY", "JUN", "JUL", "AGO", "SEP", "OCT", "NOV", "DIC"]
        dias = ["Lun", "Mar", "Mié", "Jue", "Vie", "Sáb", "Dom"]
        return {
            "dia": fecha.strftime("%d"),
            "mes": meses[fecha.month - 1],
            "semana": dias[fecha.weekday()],
        }

    @app.template_filter("fecha_texto")
    def fecha_texto(valor):
        """'2026-10-24' -> 'Sábado 24 de octubre de 2026'."""
        try:
            fecha = datetime.strptime(valor, "%Y-%m-%d")
        except (TypeError, ValueError):
            return valor or ""
        dias = ["Lunes", "Martes", "Miércoles", "Jueves", "Viernes", "Sábado", "Domingo"]
        meses = ["enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto",
                 "septiembre", "octubre", "noviembre", "diciembre"]
        return f"{dias[fecha.weekday()]} {fecha.day} de {meses[fecha.month - 1]} de {fecha.year}"

    @app.template_filter("fecha_es")
    def fecha_es(valor):
        if not valor:
            return ""
        try:
            return datetime.strptime(valor, "%Y-%m-%d").strftime("%d/%m/%Y")
        except ValueError:
            return valor

    from .admin import admin_bp
    from .auth import auth_bp
    from .compras import compras_bp
    from .cuentas import cuentas_bp
    from .entradas import entradas_bp
    from .eventos import eventos_bp
    from .pagos import pagos_bp
    from .public import public_bp

    app.register_blueprint(admin_bp)
    app.register_blueprint(auth_bp)
    app.register_blueprint(compras_bp)
    app.register_blueprint(cuentas_bp)
    app.register_blueprint(entradas_bp)
    app.register_blueprint(eventos_bp)
    app.register_blueprint(pagos_bp)
    app.register_blueprint(public_bp)

    return app
