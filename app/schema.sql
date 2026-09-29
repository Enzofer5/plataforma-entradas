CREATE TABLE IF NOT EXISTS organizadores (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    nombre TEXT NOT NULL,
    email TEXT NOT NULL UNIQUE,
    password_hash TEXT NOT NULL,
    creado_en TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS eventos (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    organizador_id INTEGER NOT NULL,
    nombre TEXT NOT NULL,
    slug TEXT NOT NULL UNIQUE,
    descripcion TEXT,
    fecha TEXT NOT NULL,
    hora TEXT,
    lugar TEXT,
    imagen_url TEXT,
    estado TEXT NOT NULL DEFAULT 'borrador',
    creado_en TEXT NOT NULL,
    FOREIGN KEY (organizador_id) REFERENCES organizadores (id)
);

CREATE TABLE IF NOT EXISTS tipos_entrada (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    evento_id INTEGER NOT NULL,
    nombre TEXT NOT NULL,
    precio REAL NOT NULL,
    stock_total INTEGER NOT NULL,
    stock_vendido INTEGER NOT NULL DEFAULT 0,
    FOREIGN KEY (evento_id) REFERENCES eventos (id)
);

CREATE TABLE IF NOT EXISTS ordenes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    evento_id INTEGER NOT NULL,
    comprador_nombre TEXT NOT NULL,
    comprador_email TEXT NOT NULL,
    comprador_dni TEXT,
    total REAL NOT NULL,
    estado TEXT NOT NULL DEFAULT 'pendiente',
    mp_preference_id TEXT,
    mp_payment_id TEXT,
    creado_en TEXT NOT NULL,
    FOREIGN KEY (evento_id) REFERENCES eventos (id)
);

CREATE TABLE IF NOT EXISTS orden_items (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    orden_id INTEGER NOT NULL,
    tipo_entrada_id INTEGER NOT NULL,
    cantidad INTEGER NOT NULL,
    precio_unitario REAL NOT NULL,
    FOREIGN KEY (orden_id) REFERENCES ordenes (id),
    FOREIGN KEY (tipo_entrada_id) REFERENCES tipos_entrada (id)
);

CREATE TABLE IF NOT EXISTS entradas (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    orden_id INTEGER NOT NULL,
    tipo_entrada_id INTEGER NOT NULL,
    codigo_unico TEXT NOT NULL UNIQUE,
    estado TEXT NOT NULL DEFAULT 'valida',
    usada_en TEXT,
    creado_en TEXT NOT NULL,
    FOREIGN KEY (orden_id) REFERENCES ordenes (id),
    FOREIGN KEY (tipo_entrada_id) REFERENCES tipos_entrada (id)
);

CREATE TABLE IF NOT EXISTS configuracion (
    clave TEXT PRIMARY KEY,
    valor TEXT NOT NULL
);
