import os
import subprocess
import sys

# Botón ▷ de VS Code: si se ejecuta con un Python que no es el del proyecto (por ejemplo
# el Python global, sin las librerías instaladas), se vuelve a lanzar con el del venv.
BASE = os.path.dirname(os.path.abspath(__file__))
_VENV_PY = next((r for r in (os.path.join(BASE, "venv", "Scripts", "python.exe"),
                              os.path.join(BASE, "venv", "bin", "python")) if os.path.exists(r)), None)
if __name__ == "__main__" and _VENV_PY and \
        os.path.normcase(os.path.abspath(sys.executable)) != os.path.normcase(_VENV_PY):
    sys.exit(subprocess.call([_VENV_PY, os.path.abspath(__file__), *sys.argv[1:]], cwd=BASE))
os.chdir(BASE)
sys.path.insert(0, BASE)

from app import create_app

app = create_app()

if __name__ == "__main__":
    # El modo debug muestra una consola para ejecutar código si algo falla: útil en tu
    # compu, peligroso si la app está expuesta a internet (ngrok, hosting). Por eso se
    # apaga solo cuando BASE_URL es una dirección pública https.
    publica = app.config["BASE_URL"].startswith("https://")
    app.run(debug=not publica)
