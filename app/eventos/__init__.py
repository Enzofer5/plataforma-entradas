from flask import Blueprint

eventos_bp = Blueprint("eventos", __name__, url_prefix="/organizador")

from . import routes  # noqa: E402,F401
