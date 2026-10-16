from flask import Blueprint

pagos_bp = Blueprint("pagos", __name__)

from . import routes  # noqa: E402,F401
