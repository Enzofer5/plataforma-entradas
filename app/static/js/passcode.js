/* passcode_ — efectos de la portada: lluvia "Matrix" de fondo y texto que se tipea
   en la terminal del hero. Si el usuario pidió menos movimiento, quedan quietos. */
(function () {
  const reducir = window.matchMedia("(prefers-reduced-motion: reduce)").matches;

  // ---- Texto que se tipea: "acceso --fiesta", "acceso --recital", ...
  const tipeo = document.getElementById("tipeo");
  if (tipeo) {
    const frases = ["acceso --fiesta", "acceso --recital", "acceso --festival", "acceso --boliche"];
    if (reducir) {
      tipeo.textContent = frases[0];
    } else {
      let f = 0, i = 0, borrando = false;
      (function paso() {
        const frase = frases[f];
        tipeo.textContent = frase.slice(0, i);
        if (!borrando && i < frase.length) { i++; setTimeout(paso, 90); }
        else if (!borrando) { borrando = true; setTimeout(paso, 1800); }
        else if (i > "acceso --".length) { i--; setTimeout(paso, 45); }
        else { borrando = false; f = (f + 1) % frases.length; setTimeout(paso, 250); }
      })();
    }
  }

  // ---- Lluvia de caracteres de fondo
  const canvas = document.getElementById("matrix");
  if (!canvas || reducir) return;
  const ctx = canvas.getContext("2d");
  const caracteres = "アイウエオカキクケコサシスセソ0123456789$#@%&*+-=<>/PASSCODE";
  const tam = 16;
  let columnas = [], ancho = 0, alto = 0, visible = true;

  function medir() {
    const r = canvas.getBoundingClientRect();
    const dpr = Math.min(window.devicePixelRatio || 1, 2);
    ancho = r.width; alto = r.height;
    canvas.width = ancho * dpr; canvas.height = alto * dpr;
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    columnas = Array.from({ length: Math.ceil(ancho / tam) }, () => Math.random() * -alto / tam);
  }

  function dibujar() {
    if (visible) {
      ctx.fillStyle = "rgba(5, 8, 6, 0.12)";
      ctx.fillRect(0, 0, ancho, alto);
      ctx.font = tam + "px 'JetBrains Mono', monospace";
      columnas.forEach(function (y, x) {
        const c = caracteres[Math.floor(Math.random() * caracteres.length)];
        ctx.fillStyle = Math.random() > 0.975 ? "#c8ffdf" : "#2bff88";
        ctx.fillText(c, x * tam, y * tam);
        columnas[x] = y * tam > alto && Math.random() > 0.975 ? 0 : y + 1;
      });
    }
    setTimeout(function () { requestAnimationFrame(dibujar); }, 55);
  }

  // No gastar batería cuando el hero no se ve.
  new IntersectionObserver(function (e) { visible = e[0].isIntersecting; }).observe(canvas);
  window.addEventListener("resize", medir);
  medir();
  dibujar();
})();
