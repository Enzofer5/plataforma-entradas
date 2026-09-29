import os

from dotenv import load_dotenv

load_dotenv()

BASE_DIR = os.path.abspath(os.path.dirname(__file__))


class Config:
    SECRET_KEY = os.environ.get("SECRET_KEY", "cambiar-esta-clave-en-produccion")
    DATABASE_PATH = os.environ.get(
        "DATABASE_PATH", os.path.join(BASE_DIR, "instance", "entradas.db")
    )

    # Ya no se usan para cobrar (el pago ahora se hace con la cuenta de cada
    # organizador, conectada por OAuth) — quedan solo por compatibilidad.
    MP_ACCESS_TOKEN = os.environ.get("MP_ACCESS_TOKEN", "")
    MP_PUBLIC_KEY = os.environ.get("MP_PUBLIC_KEY", "")

    # Credenciales OAuth de la aplicación de Mercado Pago (distintas del access
    # token): las necesita cada organizador para conectar su propia cuenta.
    MP_CLIENT_ID = os.environ.get("MP_CLIENT_ID", "")
    MP_CLIENT_SECRET = os.environ.get("MP_CLIENT_SECRET", "")

    # Email del organizador que puede entrar a /admin/configuracion a cambiar el
    # porcentaje de recargo de la plataforma.
    ADMIN_EMAIL = os.environ.get("ADMIN_EMAIL", "")

    BASE_URL = os.environ.get("BASE_URL", "http://localhost:5000")
