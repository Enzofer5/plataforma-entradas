/* Pantalla de compra: botones − / +, resumen en vivo (entradas + cargo por servicio)
   y botón Continuar activo solo cuando hay al menos una entrada elegida. */
(function () {
  const form = document.getElementById("form-compra");
  if (!form) return;
  const pct = parseFloat(form.dataset.recargoPct) || 0;
  const fijo = parseFloat(form.dataset.recargoFijo) || 0;
  const tipos = Array.from(form.querySelectorAll("[data-tipo]"));

  function pesos(v) {
    const redondo = Math.abs(v - Math.round(v)) < 0.005;
    return "$" + v.toLocaleString("es-AR", { minimumFractionDigits: redondo ? 0 : 2, maximumFractionDigits: 2 });
  }

  function cantidad(input) {
    const max = parseInt(input.max, 10) || 0;
    let n = parseInt(input.value, 10);
    if (isNaN(n) || n < 0) n = 0;
    if (n > max) n = max;
    return n;
  }

  function actualizar() {
    let subtotal = 0, pagas = 0, total = 0;
    const lista = [];
    tipos.forEach(function (fila) {
      const input = fila.querySelector("input");
      if (input.disabled) return;
      const n = cantidad(input);
      const precio = parseFloat(fila.dataset.precio) || 0;
      fila.classList.toggle("elegido", n > 0);
      fila.querySelector("[data-menos]").disabled = n <= 0;
      fila.querySelector("[data-mas]").disabled = n >= (parseInt(input.max, 10) || 0);
      if (n > 0) {
        subtotal += n * precio;
        if (precio > 0) pagas += n;
        lista.push({ nombre: fila.dataset.nombre, n: n, monto: n * precio });
      }
    });
    const cargo = subtotal > 0 ? Math.round((subtotal * pct / 100 + fijo * pagas) * 100) / 100 : 0;
    total = subtotal + cargo;

    const ul = form.querySelector("[data-items]");
    ul.innerHTML = "";
    if (!lista.length) {
      const li = document.createElement("li");
      li.className = "text-muted";
      li.textContent = "Todavía no elegiste entradas.";
      ul.appendChild(li);
    }
    lista.forEach(function (it) {
      const li = document.createElement("li");
      const a = document.createElement("span"); a.textContent = it.n + " × " + it.nombre;
      const b = document.createElement("span"); b.textContent = pesos(it.monto);
      li.append(a, b); ul.appendChild(li);
    });
    form.querySelector("[data-subtotal]").textContent = pesos(subtotal);
    form.querySelector("[data-cargo]").textContent = pesos(cargo);
    form.querySelectorAll("[data-total]").forEach(function (el) { el.textContent = pesos(total); });
    form.querySelectorAll("[data-continuar]").forEach(function (b) { b.disabled = lista.length === 0; });
    form.classList.toggle("con-entradas", lista.length > 0);
  }

  tipos.forEach(function (fila) {
    const input = fila.querySelector("input");
    fila.querySelector("[data-menos]").addEventListener("click", function () {
      input.value = Math.max(0, cantidad(input) - 1); actualizar();
    });
    fila.querySelector("[data-mas]").addEventListener("click", function () {
      input.value = Math.min(parseInt(input.max, 10) || 0, cantidad(input) + 1); actualizar();
    });
    input.addEventListener("input", actualizar);
    input.addEventListener("change", function () { input.value = cantidad(input); actualizar(); });
  });

  form.addEventListener("submit", function (e) {
    const nombre = form.querySelector("#nombre"), email = form.querySelector("#email");
    [nombre].forEach(function (c) { c.classList.toggle("is-invalid", !c.value.trim()); });
    const invalido = form.querySelector(".is-invalid");
    if (invalido) { e.preventDefault(); invalido.focus(); return; }
    form.querySelectorAll("[data-continuar]").forEach(function (b) { b.disabled = true; b.textContent = "Procesando…"; });
  });

  actualizar();
})();
