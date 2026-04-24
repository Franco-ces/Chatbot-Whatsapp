import gradio as gr
import os
import shutil
from pathlib import Path

# --- RUTAS ---
FILE_PATH = Path(__file__).resolve()
ROOT_DIR = FILE_PATH.parent.parent
PDF_FOLDER = ROOT_DIR / "PDFs"
LOGS_DIR = ROOT_DIR / "logs"
ENV_FILE = ROOT_DIR / ".env"

PDF_FOLDER.mkdir(parents=True, exist_ok=True)
LOGS_DIR.mkdir(parents=True, exist_ok=True)

# --- LÓGICA ---

def guardar_api_key(key):
    try:
        with open(ENV_FILE, "w", encoding="utf-8") as f:
            f.write(f"GOOGLE_API_KEY={key}")
        return "✅ API Key guardada exitosamente en .env"
    except Exception as e:
        return f"❌ Error al guardar: {e}"

def actualizar_lista_pdfs():
    archivos = [f.name for f in PDF_FOLDER.glob("*.pdf")]
    if not archivos:
        return gr.update(choices=[], value=None, label="Carpeta vacía")
    return gr.update(choices=archivos, label=f"Documentos en servidor ({len(archivos)})")

def eliminar_pdf_fijo(nombre_archivo):
    if not nombre_archivo:
        return "⚠️ Selecciona un archivo", actualizar_lista_pdfs()
    try:
        ruta = PDF_FOLDER / nombre_archivo
        if ruta.exists():
            os.remove(ruta)
        return f"✅ Eliminado: {nombre_archivo}", actualizar_lista_pdfs()
    except Exception as e:
        return f"❌ Error: {e}", actualizar_lista_pdfs()

def gestionar_subida(archivos):
    if archivos:
        for file in archivos:
            path_origen = getattr(file, 'path', getattr(file, 'name', None))
            if path_origen:
                shutil.copy(path_origen, PDF_FOLDER / os.path.basename(path_origen))
    return "✅ Subida exitosa", actualizar_lista_pdfs()

# --- LÓGICA DE LOGS ---

def actualizar_lista_logs():
    archivos = [f.name for f in LOGS_DIR.glob("*.txt") if not f.name.startswith("temp_")]
    return gr.update(choices=archivos)

def leer_log_especifico(nombre_archivo):
    if not nombre_archivo: return "Selecciona un log", gr.update(), gr.update(), ""
    ruta = LOGS_DIR / nombre_archivo
    try:
        temp_log = LOGS_DIR / f"temp_v_{nombre_archivo}"
        shutil.copy2(ruta, temp_log)
        with open(temp_log, "r", encoding="utf-8", errors="ignore") as f:
            contenido = f.read()
        os.remove(temp_log)
        return contenido, gr.update(visible=False), gr.update(visible=True), f"📄 {nombre_archivo}"
    except: return "Error", gr.update(visible=True), gr.update(visible=False), "Error"

# --- INTERFAZ ---
with gr.Blocks(theme=gr.themes.Soft()) as demo:
    gr.Markdown("# 🛠️ Panel Administrativo")

    with gr.Tabs():
        # PESTAÑA 1: API (CORREGIDA)
        with gr.Tab("🔑 API"):
            gr.Markdown("### Configuración de Google API Key")
            # Cambiado a type="text" para que se vea lo que se pega
            api_input = gr.Textbox(label="Clave API", type="text", placeholder="Pega tu clave aquí...")
            btn_api = gr.Button("Guardar en .env", variant="primary")
            api_out = gr.Markdown()
            
            # Conexión de la función
            btn_api.click(guardar_api_key, inputs=[api_input], outputs=[api_out])

        # PESTAÑA 2: PDFS
        with gr.Tab("📁 Documentos"):
            with gr.Row():
                with gr.Column():
                    gr.Markdown("### 📤 Subir")
                    up_input = gr.File(label="Nuevos PDFs", file_count="multiple")
                    btn_up = gr.Button("🚀 Cargar", variant="primary")
                    up_status = gr.Markdown()
                
                with gr.Column():
                    gr.Markdown("### 🗑️ Gestionar Archivos")
                    pdf_selector = gr.Dropdown(label="Selecciona para eliminar", choices=[])
                    btn_del = gr.Button("❌ Eliminar Archivo Seleccionado", variant="stop")
                    btn_ref_pdf = gr.Button("🔄 Refrescar Lista")
            
            btn_up.click(gestionar_subida, up_input, [up_status, pdf_selector])
            btn_del.click(eliminar_pdf_fijo, pdf_selector, [up_status, pdf_selector])
            btn_ref_pdf.click(actualizar_lista_pdfs, None, pdf_selector)

        # PESTAÑA 3: LOGS
        with gr.Tab("📜 Logs"):
            with gr.Column() as sec_lista:
                dropdown_logs = gr.Dropdown(label="Logs disponibles", choices=[])
                btn_leer = gr.Button("📂 Abrir", variant="primary")
                btn_ref_logs = gr.Button("🔄 Refrescar")

            with gr.Column(visible=False) as sec_visor:
                titulo_log = gr.Markdown()
                log_text = gr.TextArea(lines=20, interactive=False)
                btn_back = gr.Button("⬅️ Volver")

            btn_leer.click(leer_log_especifico, dropdown_logs, [log_text, sec_lista, sec_visor, titulo_log])
            btn_back.click(lambda: (gr.update(visible=True), gr.update(visible=False)), None, [sec_lista, sec_visor])
            btn_ref_logs.click(actualizar_lista_logs, None, dropdown_logs)

    # Carga inicial
    demo.load(actualizar_lista_pdfs, None, pdf_selector)
    demo.load(actualizar_lista_logs, None, dropdown_logs)

demo.launch()