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
   para mostrar en la puerta.
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

La plataforma **no cobra las entradas** — eso lo recibe cada organizador en su propia
cuenta de Mercado Pago. Matrix Code se queda automáticamente con un **recargo por
servicio** (un % configurable) que se le suma al comprador arriba del precio de la
entrada. Esto se hace con el modelo de **marketplace / split payments** de Mercado
Pago:

1. **Conectar la cuenta de cada organizador**: cada organizador entra a "Mi cuenta" →
   "Conectar con Mercado Pago" y autoriza su cuenta (OAuth). A partir de ahí, la plata
   de sus ventas le llega directo a él. Un evento con entradas pagas no se puede
   publicar hasta que su organizador conecte su cuenta.
2. **El recargo lo fija la plataforma**: el organizador logueado con el email de
   `ADMIN_EMAIL` (ver abajo) tiene un link "Configuración" en el menú, donde puede
   cambiar el % de recargo en cualquier momento, sin tocar código.
3. **En el checkout**, el comprador ve el desglose: subtotal de entradas + cargo por
   servicio + total. Ese recargo se lo descuenta Mercado Pago automáticamente al
   organizador y se lo deposita a la plataforma (parámetro `marketplace_fee`) — el
   organizador termina recibiendo el precio completo que puso.

### Configuración necesaria en tu `.env`

1. En [Mercado Pago Developers](https://www.mercadopago.com.ar/developers), entrá a tu
   aplicación (o creá una) y buscá, además del **Access Token**, el **Client ID** y el
   **Client Secret** (sección de Credenciales de la app) — son los que habilitan OAuth.
   Completá `MP_CLIENT_ID` y `MP_CLIENT_SECRET` con esos valores (usá los de **prueba**
   hasta tener todo probado).
2. En la configuración de esa misma app, agregá como **Redirect URI**
   `BASE_URL/organizador/mercadopago/callback` (con tu `BASE_URL` real, por ejemplo la
   de ngrok) — Mercado Pago exige que coincida exacto con la que use la app al pedir
   autorización.
3. Completá `ADMIN_EMAIL` con el email de la cuenta de organizador que va a poder
   cambiar el % de recargo.
4. **Importante sobre el webhook** (sigue igual que antes): Mercado Pago confirma el
   pago llamando a `BASE_URL/webhook/mercadopago` desde sus propios servidores — no
   puede llegar a `localhost`. Para probarlo en tu máquina necesitás exponerla con algo
   como [ngrok](https://ngrok.com/) (`ngrok http 5000`) y poner esa URL pública en
   `BASE_URL`.
5. Para probar sin plata real, usá las **cuentas de prueba** de tu app en Mercado Pago
   Developers: una cuenta "Vendedor" para loguearte como organizador y conectarla, y
   una cuenta "Comprador" para hacer la compra en el checkout.

Si un organizador todavía no conectó su cuenta, sus eventos con entradas pagas no se
pueden publicar; sigue disponible el modo de **pago simulado** para eventos de prueba
sin conexión a Mercado Pago (marca la orden como pagada directo, sin plata real).

Probé la lógica de creación de la preferencia (con el item de recargo y
`marketplace_fee`), el intercambio de OAuth y el webhook (incluida la idempotencia —
que un mismo pago notificado dos veces no duplique entradas) contra versiones de
prueba del SDK y de la API, porque este entorno no tiene salida a internet para
instalar el paquete real. Cuando tengas tus credenciales y ngrok corriendo, probamos
el circuito end-to-end con Mercado Pago de verdad.

## Identidad visual

El sitio usa el logo y la paleta negro/verde neón de **Matrix Code**
(`app/static/css/estilo.css` y `app/static/img/logo-matrix-code.jpg`), y el pie de
página dice "Plataforma desarrollada por Matrix Code" en todas las pantallas. Para
cambiar colores o el logo más adelante, esos son los dos archivos a tocar.

## Stack

Flask + sqlite3 (librería estándar de Python, sin ORM) + sesiones de Flask para el login
del organizador + Bootstrap 5 por CDN + SDK oficial de `mercadopago` para los pagos +
`qrcode`/`Pillow` para generar los QR + `html5-qrcode` (JS, por CDN) para leerlos con la
cámara en el panel de validación.

## Qué sigue

Con esto está completo el circuito del plan original (crear evento → comprar → cobrar →
validar en la puerta). Como mejoras posibles para más adelante: envío de la entrada por
email, cupones/descuentos, reportes de ventas más detallados, y pasar de SQLite a
Postgres si el proyecto crece para producción real.
