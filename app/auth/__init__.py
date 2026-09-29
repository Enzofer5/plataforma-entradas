from flask import Blueprint

auth_bp = Blueprint("auth", __name__, url_prefix="/organizador")

from . import routes  # noqa: E402,F401
