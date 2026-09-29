import os
from datetime import datetime

from flask import Flask

from . import db as db_module


def create_app(config_object="config.Config"):
    app = Flask(__name__, instance_relative_config=True)
    app.config.from_object(config_object)

    os.makedirs(app.instance_path, exist_ok=True)
    os.makedirs(os.path.dirname(app.config["DATABASE_PATH"]), exist_ok=True)

    db_module.init_app(app)

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
    from .entradas import entradas_bp
    from .eventos import eventos_bp
    from .pagos import pagos_bp
    from .public import public_bp

    app.register_blueprint(admin_bp)
    app.register_blueprint(auth_bp)
    app.register_blueprint(compras_bp)
    app.register_blueprint(entradas_bp)
    app.register_blueprint(eventos_bp)
    app.register_blueprint(pagos_bp)
    app.register_blueprint(public_bp)

    return app
