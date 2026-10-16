from flask import Blueprint

cuentas_bp = Blueprint("cuentas", __name__, url_prefix="/mi-cuenta")

from . import routes  # noqa: E402,F401
