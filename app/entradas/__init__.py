from flask import Blueprint

entradas_bp = Blueprint("entradas", __name__)

from . import routes  # noqa: E402,F401
