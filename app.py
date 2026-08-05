import streamlit as st
import pandas as pd
import pdfplumber
import re
from io import BytesIO
from datetime import date

from reportlab.lib.pagesizes import letter, A4
from reportlab.lib import colors
from reportlab.platypus import (
    SimpleDocTemplate,
    Paragraph,
    Spacer,
    Table,
    TableStyle,
    HRFlowable,
)
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle

try:
    import pytesseract
    from pdf2image import convert_from_bytes
    OCR_DISPONIBLE = True
except ImportError:
    OCR_DISPONIBLE = False

# ─────────────────────────────────────────────
# CONFIGURACIÓN DE PÁGINA
# ─────────────────────────────────────────────
st.set_page_config(
    page_title="AuditSaaS — Auditor Bancario & Conversor",
    page_icon="📊",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ─────────────────────────────────────────────
# CSS Y ESTILOS
# ─────────────────────────────────────────────
st.markdown(
    """
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap');
html, body, [class*="css"] { font-family: 'Inter', sans-serif; }
#MainMenu, footer { visibility: hidden; }

/* Sidebar Gradient */
[data-testid="stSidebar"] {
    background: linear-gradient(160deg, #0F172A 0%, #1E3A8A 100%) !important;
}
[data-testid="stSidebar"] * { color: #E2E8F0 !important; }

/* Metric Cards */
[data-testid="stMetric"] {
    background: white;
    border-radius: 14px;
    padding: 1.2rem;
    box-shadow: 0 2px 8px rgba(15,23,42,0.08);
    border-top: 4px solid #2563EB;
}
[data-testid="stMetricLabel"] { font-weight: 600; color: #475569 !important; font-size: 0.82rem; }
[data-testid="stMetricValue"] { font-size: 1.6rem !important; font-weight: 700; color: #0F172A !important; }

/* Botones de descarga */
.stDownloadButton > button {
    background: linear-gradient(135deg, #1E3A8A, #2563EB) !important;
    color: white !important;
    border: none !important;
    border-radius: 10px !important;
    font-weight: 600;
    padding: 0.65rem 1.6rem;
    font-size: 0.92rem;
}
</style>
""",
    unsafe_allow_html=True,
)

# ─────────────────────────────────────────────
# BARRA LATERAL (SIDEBAR) & BOTÓN WHATSAPP
# ─────────────────────────────────────────────
st.sidebar.title("📌 Menú & Soporte")
st.sidebar.info("Procesa y audita tus estados de cuenta bancarios con Inteligencia Artificial.")

# Configuración de WhatsApp con tu número
NUMERO_WHATSAPP = "528121106491"
MENSAJE_WHATSAPP = "Hola, utilicé la app de Auditoría Bancaria y me gustaría solicitar una consulta personalizada."
url_whatsapp = f"https://wa.me/{NUMERO_WHATSAPP}?text={MENSAJE_WHATSAPP.replace(' ', '%20')}"

st.sidebar.markdown("---")
st.sidebar.subheader("💬 ¿Auditoría Personalizada?")
st.sidebar.markdown(f'''
    <a href="{url_whatsapp}" target="_blank" style="text-decoration: none;">
        <button style="
            background-color: #25D366;
            color: white;
            border: none;
            padding: 12px 15px;
            text-align: center;
            display: block;
            font-size: 15px;
            margin: 8px 0px;
            cursor: pointer;
            border-radius: 10px;
            font-weight: bold;
            width: 100%;
            box-shadow: 0 4px 12px rgba(37,211,102,0.3);">
            📲 Hablar por WhatsApp
        </button>
    </a>
''', unsafe_allow_html=True)

# ─────────────────────────────────────────────
# HEADER VISUAL
# ─────────────────────────────────────────────
st.markdown(
    """
<div style="
    background: linear-gradient(135deg, #0F172A 0%, #1E3A8A 60%, #2563EB 100%);
    border-radius: 18px;
    padding: 2rem;
    margin-bottom: 1.8rem;
    display: flex; align-items: center; gap: 1.2rem;
    box-shadow: 0 4px 24px rgba(30,58,138,0.25);
">
    <div style="font-size:3rem; line-height:1;">📊</div>
    <div>
        <div style="font-size:1.75rem; font-weight:800; color:white; line-height:1.1;">
            AuditSaaS — Auditor Bancario Express
        </div>
        <div style="font-size:0.95rem; color:#93C5FD; margin-top:4px;">
            Convierte tus estados de cuenta PDF a Excel y detecta anomalías financieras en segundos.
        </div>
    </div>
</div>
""",
    unsafe_allow_html=True,
)

# ─────────────────────────────────────────────
# PALABRAS CLAVE PARA CLASIFICACIÓN
# ─────────────────────────────────────────────
PALABRAS_INGRESO = ["abono", "deposito", "depositos", "recibido", "credito", "transferencia recibida", "ingreso", "venta", "cobro"]
PALABRAS_EGRESO = ["cargo", "retiro", "pago", "compra", "comision", "iva", "spei enviado", "debito", "cheque", "egreso", "gasto", "servicio"]

def clasificar_transaccion(texto_lower):
    if any(w in texto_lower for w in PALABRAS_INGRESO):
        return "Ingreso"
    return "Egreso"

def procesar_texto_lineas(lines, origen):
    rows = []
    for line in lines:
        m = re.search(r"(\d{2}[/-]\d{2}[/-]\d{2,4}|\d{2}\s+[A-Za-z]{3})\s+(.*?)\s+[\$]?\s*([0-9,]+\.[0-9]{2})", line)
        if m:
            fecha, concepto, monto_str = m.groups()
            rows.append({
                "Origen": origen,
                "Fecha": fecha,
                "Concepto": concepto.strip(),
                "Monto": float(monto_str.replace(",", "")),
                "Tipo": clasificar_transaccion(concepto.lower())
            })
    return rows

def extraer_datos_pdf(file_pdf):
    transacciones = []
    pdf_bytes = file_pdf.read()
    
    with pdfplumber.open(BytesIO(pdf_bytes)) as pdf:
        for num, page in enumerate(pdf.pages, 1):
            # A: Extracción de Tablas
            tables = page.extract_tables()
            for table in tables:
                for row in table:
                    if not row: continue
                    rc = [str(c).replace("\n", " ").strip() for c in row if c is not None]
                    if len(rc) < 3: continue
                    for idx, cell in enumerate(rc):
                        mo = re.search(r"[\$]?\s*([0-9]{1,3}(?:,[0-9]{3})*(?:\.[0-9]{2})?)", cell)
                        if mo:
                            try:
                                val = float(mo.group(1).replace(",", ""))
                                if val > 0:
                                    texto = " ".join(rc).lower()
                                    tipo = clasificar_transaccion(texto)
                                    transacciones.append({
                                        "Origen": f"Pág.{num}",
                                        "Fecha": rc[0],
                                        "Concepto": rc[1] if len(rc) > 1 else "Transacción",
                                        "Monto": val,
                                        "Tipo": tipo
                                    })
                                    break
                            except ValueError:
                                continue
            
            # B: Texto digital en líneas
            text = page.extract_text() or ""
            if text.strip() and not transacciones:
                transacciones.extend(procesar_texto_lineas(text.split("\n"), f"Pág.{num}"))

    return pd.DataFrame(transacciones) if transacciones else pd.DataFrame(columns=["Origen", "Fecha", "Concepto", "Monto", "Tipo"])

# ─────────────────────────────────────────────
# INTERFAZ PRINCIPAL
# ─────────────────────────────────────────────
uploaded_file = st.file_uploader("📂 Sube tu Estado de Cuenta en PDF o Excel", type=["pdf", "xlsx", "xls"])

if uploaded_file is not None:
    file_ext = uploaded_file.name.split(".")[-1].lower()
    
    with st.spinner("🔄 Procesando y analizando archivo..."):
        if file_ext == "pdf":
            df_tx = extraer_datos_pdf(uploaded_file)
        else:
            df_tx = pd.read_excel(uploaded_file)
            if "Tipo" not in df_tx.columns and "Concepto" in df_tx.columns:
                df_tx["Tipo"] = df_tx["Concepto"].apply(lambda x: clasificar_transaccion(str(x).lower()))

    if not df_tx.empty:
        st.success("✅ ¡Archivo procesado exitosamente!")
        
        # --- CÁLCULOS PRINCIPALES ---
        ingresos = df_tx[df_tx["Tipo"] == "Ingreso"]["Monto"].sum() if "Tipo" in df_tx.columns else 0.0
        egresos = df_tx[df_tx["Tipo"] == "Egreso"]["Monto"].sum() if "Tipo" in df_tx.columns else 0.0
        utilidad = ingresos - egresos
        margin = (utilidad / ingresos * 100) if ingresos > 0 else 0.0

        # --- MÉTRICAS ---
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Total Ingresos", f"${ingresos:,.2f}")
        c2.metric("Total Egresos", f"${egresos:,.2f}")
        c3.metric("Utilidad Neta", f"${utilidad:,.2f}")
        c4.metric("Margen Neto", f"{margin:.1f}%")

        st.markdown("---")

        # --- PESTAÑAS ---
        tab1, tab2 = st.tabs(["📋 Tabla de Transacciones", "📥 Descargar Archivos"])

        with tab1:
            st.subheader("Visualización de Transacciones Extradas")
            st.dataframe(df_tx, use_container_width=True)

        with tab2:
            st.subheader("Exportar Resultados")
            col_a, col_b = st.columns(2)

            with col_a:
                # EXPORTAR A EXCEL
                excel_buf = BytesIO()
                with pd.ExcelWriter(excel_buf, engine="openpyxl") as writer:
                    df_tx.to_excel(writer, index=False, sheet_name="Transacciones")
                    resumen = pd.DataFrame({
                        "Indicador": ["Ingresos", "Egresos", "Utilidad Neta", "Total Registros"],
                        "Valor": [ingresos, egresos, utilidad, len(df_tx)]
                    })
                    resumen.to_excel(writer, index=False, sheet_name="Resumen")
                
                st.download_button(
                    label="📊 Descargar en Excel (.xlsx)",
                    data=excel_buf.getvalue(),
                    file_name=f"Estado_de_Cuenta_Convertido_{date.today().strftime('%Y%m%d')}.xlsx",
                    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    use_container_width=True
                )

            with col_b:
                st.info("💡 **¿Deseas una auditoría profunda o un reporte para el SAT?**")
                st.markdown(f"Haz clic en el botón de la barra lateral o [contáctanos por WhatsApp aquí]({url_whatsapp}) para ayudarte de forma personalizada.")

    else:
        st.warning("⚠️ No se pudieron extraer tablas o transacciones claras del documento. Asegúrate de que no sea un archivo escaneado sin texto seleccionable.")
