# Entradas — plataforma de venta de entradas online

Plataforma completa de venta de entradas: organizadores con cuenta propia crean eventos,
definen tipos de entrada y los publican. El público compra de punta a punta, con **pago
real por Mercado Pago** directo a la cuenta de cada organizador (modelo marketplace —
ver más abajo); si un organizador no conectó su cuenta todavía, sigue funcionando con un
pago simulado. Cada entrada comprada tiene su **código QR**, y el organizador tiene un
**panel de validación** para escanearlas en la puerta del evento.

## Cómo correrla en tu máquina

**Windows (PowerShell):**

```powershell
python -m venv venv
venv\Scripts\Activate.ps1
pip install -r requirements.txt
copy .env.example .env
python run.py
```

Si `Activate.ps1` da error de política de ejecución, corré una vez
`Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass` y volvé a intentar. Si no
tenés `python` en el PATH, probá `py` en su lugar.

**Mac / Linux:**

```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
python run.py
```

Abrí http://localhost:5000 — la base de datos SQLite se crea sola en `instance/entradas.db`
la primera vez que corre.

## Qué probar

**Como organizador:**
1. "Crear cuenta de organizador" → te loguea automáticamente.
2. "Mis eventos" → "+ Nuevo evento" → completá nombre, fecha, lugar.
3. Te lleva directo a "Tipos de entrada" → agregá uno o más (ej: General, $5000, stock 100).
4. Volvé a "Mis eventos" → botón "Publicar".
5. Botón "Ver página" → así la ve el público.

**Como comprador** (podés usar otra ventana/navegador sin sesión de organizador):
1. Entrá a la página pública del evento → "Comprar entradas".
2. Elegí cantidades por tipo de entrada y completá tus datos → "Continuar".
3. Si el organizador del evento no conectó Mercado Pago: pantalla de resumen con
   "Pagar (simulado)". Si ya la conectó: te manda directo al checkout real de Mercado
   Pago, con el desglose de subtotal + cargo por servicio + total.
4. Al confirmarse el pago vas a ver una pantalla con un código único por cada entrada
   comprada, y un botón "Ver entrada con QR" que te lleva a una pantalla con el código QR
   para mostrar en la puerta. Si hay SMTP configurado (ver abajo), también te llega un
   mail con las entradas y sus QR.
5. Volvé a la página del evento como organizador: el stock disponible ya bajó, y si
   agotás las entradas de un tipo, un nuevo comprador no va a poder pasarse de ese límite.

## Validar entradas en la puerta

En "Mis eventos", los eventos publicados tienen un botón **"Validar entradas"** que abre
un panel con:
- **Lector de cámara**: apunta la cámara del celu/notebook al QR y valida solo (necesita
  que aceptes el permiso de cámara del navegador — con Mercado Pago real ya estás
  navegando por HTTPS vía ngrok, que es lo que hace falta para que el navegador permita
  usar la cámara).
- **Carga manual**: por si no hay cámara a mano, pegás el código a mano.

Cada código solo se puede validar una vez (si lo volvés a escanear, avisa que ya fue
usado), y un código de otro evento no sirve para validar en este.

## Cómo se cobra: modelo marketplace (la plata va a cada organizador)

La plataforma **no cobra las entradas**: eso lo recibe cada organizador en su propia
cuenta de Mercado Pago. La plataforma se queda automáticamente con un **recargo por
servicio** que se le suma al comprador arriba del precio de la entrada (modelo
**marketplace / split payments** de Mercado Pago):

1. **Conectar la cuenta de cada organizador**: "Mi cuenta" → "Conectar con Mercado
   Pago" (OAuth). Desde ahí la plata de sus ventas le llega directo. Un evento con
   entradas pagas no se puede publicar hasta que su organizador conecte su cuenta.
2. **El recargo lo fija el dueño** desde su panel (ver "Panel del dueño" abajo).
3. **En el checkout** el comprador ve el desglose (entradas, descuento, cargo por
   servicio, total). Mercado Pago le descuenta el recargo al organizador y se lo
   deposita a la plataforma (`application_fee` / `marketplace_fee`).

### Formulario de pago dentro de la página

El comprador paga **sin salir del sitio**, con el formulario oficial de Mercado Pago
(*Payment Brick*), que valida número de tarjeta, vencimiento, código de seguridad, DNI
y cuotas. Medios aceptados:

- **Tarjetas de crédito, débito y prepagas** (Visa, Mastercard, Amex, Naranja, Cabal,
  etc., hasta 12 cuotas). Las tarjetas de billeteras como Ualá, Brubank, Naranja X,
  Lemon o Prex funcionan porque son Visa/Mastercard.
- **Dinero en cuenta de Mercado Pago.**
- **Efectivo** en Rapipago / Pago Fácil: se genera un cupón y las entradas llegan
  cuando se acredita.

(MODO no está integrado con Mercado Pago, así que no aparece.)

Los datos de la tarjeta **nunca pasan por nuestro servidor**: el formulario los manda
directo a Mercado Pago, que devuelve un `token`, y con ese token el servidor crea el
pago. El monto se toma siempre de la orden guardada (no del navegador). Si el pago se
rechaza, el comprador ve el motivo en castellano ("la tarjeta no tiene saldo", "revisá
el código de seguridad"…) y puede reintentar con otra. Si se aprueba justo cuando se
agotaron las entradas, se le **devuelve la plata automáticamente**.

Para usar el formulario, el organizador tiene que tener guardada su **clave pública**,
que se obtiene al conectar Mercado Pago. Los que se conectaron antes de esta versión
ven un aviso en "Mi cuenta" para **volver a conectar** una vez; mientras tanto, sus
compradores pagan en la página de Mercado Pago (como antes).

Cada compra tiene un **código secreto** en sus links (`/checkout/<código>/...`): ya no
se usa el número de orden, que permitía ver las entradas de otro cambiando la URL.

### Configuración necesaria en tu `.env`

1. En [Mercado Pago Developers](https://www.mercadopago.com.ar/developers), entrá a tu
   aplicación y copiá el **Client ID** y el **Client Secret** en `MP_CLIENT_ID` y
   `MP_CLIENT_SECRET` (usá los de **prueba** hasta tener todo probado).
2. En esa misma app, agregá como **Redirect URI**
   `BASE_URL/organizador/mercadopago/callback` (con tu `BASE_URL` real).
3. **Webhook y dirección pública**: Mercado Pago avisa los pagos (sobre todo los en
   efectivo, que se acreditan después) llamando a `BASE_URL/webhook/mercadopago`, y eso
   solo funciona con una dirección **https pública**, no con `localhost`. Para probar
   en tu máquina usá [ngrok](https://ngrok.com/) (`ngrok http 5000`) y poné esa URL en
   `BASE_URL`. Sin eso, los pagos con tarjeta igual se confirman al instante, y el
   comprador tiene un botón "Ya pagué, revisar estado" para los demás.
4. Para probar sin plata real usá las **cuentas de prueba** de Mercado Pago Developers
   (una "Vendedor" para conectar como organizador y una "Comprador" para pagar) y las
   [tarjetas de prueba](https://www.mercadopago.com.ar/developers/es/docs/checkout-bricks/additional-content/your-integrations/test/cards).

Si el organizador no conectó Mercado Pago, sigue disponible el **pago simulado** para
probar el circuito sin plata real.

## Panel del dueño de la plataforma

En `/admin` (con su propio inicio de sesión, separado del de los organizadores):

- **Resumen**: tus ganancias (recargos cobrados), ventas totales, ganancias por mes,
  organizadores que más te hacen ganar y últimas ventas.
- **Recargos**: recargo **general** (porcentaje y/o monto fijo por entrada, con un
  simulador), y recargos **especiales por organizador o por evento**. Prioridad:
  evento → organizador → general. Los cambios se aplican a las compras nuevas.
- **Organizadores**: lista con su estado de Mercado Pago y cuánto vendieron;
  **suspender / reactivar** cuentas (suspender cierra su sesión y oculta sus eventos).
- **Eventos**: todos los eventos; **pausar** uno lo saca de la página pública y el
  organizador no lo puede republicar hasta que lo habilites.

Las entradas ya vendidas siguen siendo válidas aunque se suspenda o pause algo.

**Cuenta de dueño (una sola):** la primera vez que entrás a `/admin`, la página te pide
crear la cuenta (nombre, email y contraseña de al menos 8 caracteres). Apenas se crea,
esa página se desactiva y no se puede crear ninguna otra. Desde "Mi cuenta", dentro del
panel, podés cambiar el nombre, el email o la contraseña.

⚠️ Creala **antes de publicar la plataforma en internet**: mientras no exista, el
primero que entre a `/admin` la puede crear.

Si te olvidás la contraseña, se cambia desde la consola, en la carpeta del proyecto:

```bash
python -m flask --app run recuperar-dueno
```

## Envío de las entradas por mail

Cuando se confirma un pago (real o simulado), si hay SMTP configurado en el `.env`
(`SMTP_HOST`, `SMTP_USER`, `SMTP_PASSWORD`), el comprador recibe automáticamente un
mail con sus entradas: el QR de cada una (insertado en el cuerpo del mail y también
como adjunto descargable) y un link para verla online. No hace falta instalar ningún
paquete nuevo — usa solo `smtplib`/`email`, que vienen con Python.

**Con Gmail** (la opción más simple si no tenés otro proveedor de mail):
1. Activá la verificación en 2 pasos en tu cuenta de Google, si no la tenés.
2. Andá a [myaccount.google.com/apppasswords](https://myaccount.google.com/apppasswords)
   y generá una "contraseña de aplicación" (no es tu contraseña normal de Gmail).
3. En tu `.env`:
   ```
   SMTP_HOST=smtp.gmail.com
   SMTP_PORT=587
   SMTP_USER=tu_email@gmail.com
   SMTP_PASSWORD=la_contraseña_de_aplicación_de_16_letras
   SMTP_FROM=Matrix Code <tu_email@gmail.com>
   ```

Si dejás estas variables vacías, la app sigue funcionando exactamente igual que antes
— simplemente no manda el mail (el comprador siempre puede ver/descargar su entrada
desde el link de la pantalla de confirmación). Un envío de mail que falle (SMTP mal
configurado, sin conexión, etc.) tampoco rompe nada de la compra — sólo queda
registrado en los logs del servidor.

Probé la generación del mail (con las imágenes de QR insertadas e inline, el texto
plano de respaldo, y que un fallo de SMTP no interrumpa la confirmación del pago)
contra un servidor SMTP de prueba en este entorno, ya que tampoco tiene salida de red
para mandar un mail real desde acá.

## Cupones de descuento

Desde "Mis eventos" → **🏷️ Cupones**, el organizador crea códigos para cada evento:

- **Porcentaje** (ej: `PREVENTA` = 15% off) o **monto fijo** (ej: `AMIGOS2K` = $2.000 off).
- **Límite de usos** opcional (cada compra que lo usa cuenta como un uso) y **fecha de
  vencimiento** opcional (vale hasta ese día inclusive).
- Se pueden **pausar** y volver a activar. Solo se pueden eliminar si nunca se usaron
  (los usados quedan en los reportes).

El comprador escribe el código al comprar (o entra con un link que ya lo trae cargado:
`/evento/<slug>/comprar?cupon=PREVENTA`). El descuento se aplica sobre el precio de las
entradas y el cargo por servicio se calcula sobre el monto ya descontado. Con Mercado
Pago, las entradas con descuento van como un único ítem (Mercado Pago no acepta precios
negativos). Si el total queda en $0 (cupón del 100% o entradas gratis), la compra se
confirma directo sin pasar por el pago.

## Reportes de ventas

"Mis eventos" → **📊 Reporte** muestra, por evento: recaudación neta (descontados los
cupones), entradas vendidas sobre el total, cantidad de compras y ticket promedio,
cuántos ya ingresaron (entradas validadas), un gráfico de entradas vendidas por día,
el desglose por tipo de entrada, los cupones más usados y las últimas compras.

El botón **Descargar Excel (CSV)** baja todas las compras (con `;` como separador y
coma decimal, para que Excel en español lo abra bien directamente).

## Imagen del evento

Al crear o editar un evento se puede **subir el flyer** (JPG, PNG, WEBP o GIF, hasta
5 MB — se verifica que sea una imagen de verdad) o pegar el link de una imagen. Las
imágenes subidas se guardan en `app/static/uploads/eventos/` (no se suben a git).

## Identidad visual

El sitio usa el logo y la paleta negro/verde neón de **Matrix Code**
(`app/static/css/estilo.css` y `app/static/img/logo-matrix-code.jpg`), y el pie de
página dice "Plataforma desarrollada por Matrix Code" en todas las pantallas. Para
cambiar colores o el logo más adelante, esos son los dos archivos a tocar.

## Tecnologías

- **Python 3 + Flask** — backend y plantillas Jinja2; sesiones de Flask para el login del organizador
- **SQLite** (`sqlite3` de la librería estándar, sin ORM)
- **Bootstrap 5** (por CDN) — interfaz
- **Mercado Pago** — SDK oficial `mercadopago` + OAuth para cobrar en la cuenta de cada organizador
- **qrcode + Pillow** — generación de los códigos QR de las entradas
- **html5-qrcode** (JS, por CDN) — lectura de QR con la cámara en el panel de validación
- **smtplib** (librería estándar) — envío de entradas por mail
- **python-dotenv** — configuración por variables de entorno (`.env`)

## Qué sigue

Con esto está completo el circuito del plan original (crear evento → comprar → cobrar →
validar en la puerta), más el modelo de marketplace, el envío de entradas por mail,
cupones de descuento, reportes de ventas e imagen por evento. Como mejoras posibles para
más adelante: renovar automáticamente el permiso de Mercado Pago de cada organizador
(dura 180 días), y pasar de SQLite a Postgres si el proyecto crece.
