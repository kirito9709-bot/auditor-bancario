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
    PageBreak,
)
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import cm

try:
    import pytesseract
    from pdf2image import convert_from_bytes

    OCR_DISPONIBLE = True
except ImportError:
    OCR_DISPONIBLE = False

# ─────────────────────────────────────────────
# CONFIG
# ─────────────────────────────────────────────
st.set_page_config(
    page_title="AuditSaaS — Auditor Financiero para PyMEs",
    page_icon="📊",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ─────────────────────────────────────────────
# CSS PROFESIONAL
# ─────────────────────────────────────────────
st.markdown(
    """
<style>
/* ── Globals ── */
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap');
html, body, [class*="css"] { font-family: 'Inter', sans-serif; }
#MainMenu, footer { visibility: hidden; }

/* ── Sidebar ── */
[data-testid="stSidebar"] {
    background: linear-gradient(160deg, #0F172A 0%, #1E3A8A 100%) !important;
}
[data-testid="stSidebar"] * { color: #E2E8F0 !important; }
[data-testid="stSidebar"] .stSelectbox label,
[data-testid="stSidebar"] .stNumberInput label {
    color: #93C5FD !important;
    font-weight: 600;
}

/* ── Metric Cards ── */
[data-testid="stMetric"] {
    background: white;
    border-radius: 14px;
    padding: 1.2rem 1.4rem;
    box-shadow: 0 2px 8px rgba(15,23,42,0.06), 0 1px 2px rgba(15,23,42,0.04);
    border: 1px solid #E2E8F0;
    border-top: 4px solid #2563EB;
}
[data-testid="stMetricLabel"] {
    font-size: 0.82rem !important;
    font-weight: 600 !important;
    color: #64748B !important;
    text-transform: uppercase;
    letter-spacing: 0.05em;
}
[data-testid="stMetricValue"] {
    font-size: 1.65rem !important;
    font-weight: 700 !important;
    color: #0F172A !important;
}

/* ── Buttons ── */
.stDownloadButton > button {
    background: linear-gradient(135deg, #1E3A8A 0%, #2563EB 100%) !important;
    color: white !important;
    border: none !important;
    border-radius: 10px !important;
    padding: 0.65rem 1.4rem !important;
    font-weight: 600 !important;
    font-size: 0.92rem !important;
    box-shadow: 0 4px 12px rgba(37,99,235,0.2) !important;
    transition: all 0.2s ease !important;
}
.stDownloadButton > button:hover {
    transform: translateY(-1px) !important;
    box-shadow: 0 6px 16px rgba(37,99,235,0.3) !important;
}

/* ── File Uploader ── */
[data-testid="stFileUploader"] {
    background: #F8FAFC;
    border: 2px dashed #CBD5E1;
    border-radius: 14px;
    padding: 1rem;
}

/* ── Tabs ── */
.stTabs [data-baseweb="tab-list"] { gap: 8px; }
.stTabs [data-baseweb="tab"] {
    border-radius: 8px 8px 0 0;
    padding: 8px 16px;
    font-weight: 600;
}
</style>
""",
    unsafe_allow_html=True,
)

# ─────────────────────────────────────────────
# PALABRAS CLAVE Y REGLAS DE NEGOCIO
# ─────────────────────────────────────────────
KEYWORDS_INGRESO = [
    "abono", "deposito", "depositos", "recibido", "credito",
    "transferencia recibida", "ingreso", "intereses ganados",
    "spei recibido", "nomm", "factura", "cobro", "venta",
]
KEYWORDS_EGRESO = [
    "cargo", "retiro", "pago", "compra", "comision", "iva",
    "spei enviado", "debito", "cheque", "egreso", "disposicion",
    "impuesto", "isr", "comision por", "mantenimiento", "gasto",
]

def clasificar_concepto(texto: str) -> str:
    t = texto.lower()
    if any(k in t for k in KEYWORDS_INGRESO):
        return "Ingreso"
    if any(k in t for k in KEYWORDS_EGRESO):
        return "Egreso"
    return "Egreso"

def parsear_lineas_texto(text: str, origen: str) -> list:
    rows = []
    lines = text.split("\n")
    pattern = re.compile(
        r"(\d{2}[/-]\d{2}[/-]\d{2,4}|\d{2}\s+[A-Za-z]{3})\s+(.*?)\s+[\$]?\s*([0-9,]+\.[0-9]{2})"
    )
    for line in lines:
        match = pattern.search(line)
        if match:
            fecha, concepto, monto_str = match.groups()
            try:
                monto = float(monto_str.replace(",", ""))
                if monto > 0:
                    tipo = clasificar_concepto(concepto)
                    rows.append({
                        "Origen": origen,
                        "Fecha": fecha.strip(),
                        "Concepto": concepto.strip(),
                        "Monto": monto,
                        "Tipo": tipo,
                        "Estado": "Normal",
                    })
            except ValueError:
                pass
    return rows

def extraer_transacciones_pdf(file_pdf) -> tuple[pd.DataFrame, bool]:
    rows = []
    es_escaneado = False
    pdf_bytes = file_pdf.read()

    with pdfplumber.open(BytesIO(pdf_bytes)) as pdf:
        texto_total = ""
        for i, page in enumerate(pdf.pages, 1):
            txt = page.extract_text() or ""
            texto_total += txt

            # Intentar extracción de tablas
            tables = page.extract_tables()
            for tbl
