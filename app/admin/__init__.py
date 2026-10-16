from flask import Blueprint

# cli_group=None: el comando queda como "flask recuperar-dueno" (no "flask admin recuperar-dueno").
admin_bp = Blueprint("admin", __name__, url_prefix="/admin", cli_group=None)

from . import routes  # noqa: E402,F401
