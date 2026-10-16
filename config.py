import os

from dotenv import load_dotenv

load_dotenv()

BASE_DIR = os.path.abspath(os.path.dirname(__file__))


class Config:
    SECRET_KEY = os.environ.get("SECRET_KEY", "cambiar-esta-clave-en-produccion")
    DATABASE_PATH = os.environ.get(
        "DATABASE_PATH", os.path.join(BASE_DIR, "instance", "entradas.db")
    )

    # Credenciales de la cuenta de Mercado Pago de la PLATAFORMA (las de producción de
    # tu aplicación). Se usan en el modo "cobro centralizado": todos los pagos entran a
    # esta cuenta y el dueño le transfiere a cada organizador.
    MP_ACCESS_TOKEN = os.environ.get("MP_ACCESS_TOKEN", "")
    MP_PUBLIC_KEY = os.environ.get("MP_PUBLIC_KEY", "")

    # Credenciales OAuth de la aplicación de Mercado Pago (distintas del access
    # token): las necesita cada organizador para conectar su propia cuenta.
    MP_CLIENT_ID = os.environ.get("MP_CLIENT_ID", "")
    MP_CLIENT_SECRET = os.environ.get("MP_CLIENT_SECRET", "")

    BASE_URL = os.environ.get("BASE_URL", "http://localhost:5000")

    # Tamaño máximo de lo que se puede subir (ej: la imagen de un evento): 5 MB.
    MAX_CONTENT_LENGTH = 5 * 1024 * 1024

    # SMTP para mandar las entradas por mail al comprador cuando se confirma el pago.
    # Si SMTP_HOST/SMTP_USER/SMTP_PASSWORD quedan vacíos, la app sigue funcionando
    # igual — simplemente no manda el mail (el comprador siempre puede ver/descargar
    # su entrada desde el link de la confirmación).
    SMTP_HOST = os.environ.get("SMTP_HOST", "")
    SMTP_PORT = int(os.environ.get("SMTP_PORT") or 587)
    SMTP_USER = os.environ.get("SMTP_USER", "")
    SMTP_PASSWORD = os.environ.get("SMTP_PASSWORD", "")
    SMTP_FROM = os.environ.get("SMTP_FROM", "") or SMTP_USER
