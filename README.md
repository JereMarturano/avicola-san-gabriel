# Avícola San Gabriel - Molinari
## Sistema Móvil (Mobile-First Web App / PWA) para Control Diario de Stock Avícola

Aplicación web progresiva (PWA) moderna, ligera, rápida y autocontenida diseñada específicamente para smartphones, pensada para el trabajo operativo en galpón y reparto.

---

### 📱 Características Principales
- **Diseño Mobile-First 100% Táctil:**
  - Botones táctiles amplios (touch targets > 48px).
  - Barra de navegación inferior fija (**Bottom Navigation Bar**).
  - Modal deslizante (**Bottom Sheet**) para registrar movimientos con una sola mano.
  - Campos numéricos con teclado numérico directo (`inputmode="numeric"`).
  - Experiencia tipo app nativa a pantalla completa (**PWA Standalone**).
- **Cálculo y Conversión Automática de Unidades:**
  - `1 Cajón = 12 Maples = 360 Huevos`.
  - `1 Maple = 30 Huevos (1/12 de Cajón)`.
  - Carga combinada: podés ingresar cajones, maples sueltos, o ambos al mismo tiempo.
  - Visualización dual constante: ej. `10.5 Cajones (126 Maples)`.
- **Flujos de Negocio de Granja Avícola:**
  1. **Ingreso de Galpón:** Carga directa a stock *Por Seleccionar* (Blanco o De Color).
  2. **Clasificación / Embalado:** Pasa huevos de *Por Seleccionar* a *Seleccionado* clasificándolos por calibre (*Chico, Mediano, Grande, Especial*).
  3. **Venta / Despacho:** Salida de stock clasificado con nota de cliente/destino.
  4. **Ajuste Físico:** Para cuadrar inventario si se detectan diferencias.
- **Autenticación y Roles:**
  - Sesión protegida y contraseñas hasheadas (`werkzeug.security`).
  - Roles: **Admin** (acceso total y gestión de operarios) y **Operario** (carga de stock e historial).
  - Usuario inicial `admin` creado solo si se define `ADMIN_PASSWORD` (mínimo 6 caracteres).
- **Persistencia Local y Cero Costo:**
  - Base de datos local SQLite (`avicola.db`). Sin costos de bases de datos externas en la nube.

---

### 💻 1. Ejecución Local en tu Computadora

#### Requisitos:
- Python 3.9 o superior instalado.

#### Pasos:
1. Abrí la terminal en la carpeta del proyecto:
   ```bash
   cd "C:\Users\Jerem\.gemini\antigravity-ide\scratch\avicola-san-gabriel"
   ```
2. Instalar dependencias:
   ```bash
   pip install -r requirements.txt
   ```
3. Iniciar la aplicación:
   ```bash
   python app.py
   ```
4. Abrir en el navegador:
   - En tu computadora: `http://localhost:5000`
   - Desde tu celular en la misma red Wi-Fi: `http://[IP-DE-TU-PC]:5000` (ej: `http://192.168.1.45:5000`).

---

### 📲 2. Cómo Instalarla como App Nativa en el Celular (PWA)

1. Abrí la URL de la web app en tu teléfono:
   - **En Android (Google Chrome):**
     Toca los 3 puntos arriba a la derecha y selecciona **"Agregar a la pantalla principal"** o **"Instalar aplicación"**.
   - **En iPhone (Safari):**
     Toca el botón compartir (icono de cuadro con flecha hacia arriba) y selecciona **"Agregar al inicio"**.
2. Aparecerá el icono de **Avícola San Gabriel** en la pantalla de inicio de tu teléfono. Al abrirla, funcionará a pantalla completa sin la barra de direcciones de Safari ni Chrome, como si fuera una app descargada del App Store o Google Play.

---

### ☁️ 3. Despliegue Gratuito en la Nube con Persistencia SQLite

#### Opción A: Despliegue en Render (Recomendado y Gratis)
1. Subí este código a un repositorio en **GitHub** (público o privado).
2. Registrate gratis en [render.com](https://render.com).
3. Hacé clic en **New +** y seleccioná **Web Service**.
4. Conectá tu repositorio de GitHub.
5. Configurá los siguientes campos:
   - **Name:** `avicola-san-gabriel`
   - **Runtime:** `Python 3`
   - **Build Command:** `pip install -r requirements.txt`
   - **Start Command:** `gunicorn app:app`
   - **Instance Type:** `Free`
6. *(Opcional para persistencia permanente tras reinicios en el plan Free)*:
   En Render podés adjuntar un **Disk** (Persistent Storage) en la ruta `/opt/render/project/src/data` y configurar la variable de entorno `DB_PATH=/opt/render/project/src/data/avicola.db`.
7. Hacé clic en **Deploy Web Service**. ¡En 2 minutos tendrás una URL pública HTTPS lista para compartir con los operarios!

#### Opción B: Despliegue en Railway
1. Registrate en [railway.app](https://railway.app).
2. Hacé clic en **New Project** -> **Deploy from GitHub repo**.
3. Seleccioná el repositorio. Railway detectará automáticamente el archivo `Procfile` y desplegará la app.
4. En la pestaña **Settings** -> **Networking**, hacé clic en **Generate Domain** para obtener tu enlace web público.

## Desarrollo

- **Tests:** `python -m unittest discover tests` (usan una base SQLite temporal, nunca Turso).
- **Estilos:** si se agregan clases de Tailwind nuevas en los templates, regenerar el CSS con
  `npx tailwindcss@3 -i static/css/tailwind.src.css -o static/css/tailwind.css --minify`.
