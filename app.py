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

            tables = page.extract_tables()
            for tbl in tables:
                for row in tbl:
                    if not row:
                        continue
                    rc = [
                        str(c).replace("\n", " ").strip()
                        for c in row
                        if c is not None
                    ]
                    if len(rc) < 2:
                        continue
                    for cell in rc:
                        m = re.search(
                            r"[\$]?\s*([0-9]{1,3}(?:,[0-9]{3})*(?:\.[0-9]{2})?)",
                            cell,
                        )
                        if m:
                            try:
                                v = float(m.group(1).replace(",", ""))
                                if v > 0:
                                    linea_str = " ".join(rc)
                                    tipo = clasificar_concepto(linea_str)
                                    rows.append({
                                        "Origen": f"Pág.{i}",
                                        "Fecha": rc[0] if len(rc) > 0 else "N/A",
                                        "Concepto": (
                                            rc[1] if len(rc) > 1 else "Movimiento"
                                        ),
                                        "Monto": v,
                                        "Tipo": tipo,
                                        "Estado": "Normal",
                                    })
                                    break
                            except ValueError:
                                pass

            if not tables and txt.strip():
                rows.extend(parsear_lineas_texto(txt, f"Pág.{i}"))

        if len(texto_total.strip()) < 50 and len(rows) == 0:
            es_escaneado = True

    df = (
        pd.DataFrame(rows)
        if rows
        else pd.DataFrame(
            columns=["Origen", "Fecha", "Concepto", "Monto", "Tipo", "Estado"]
        )
    )

    if not df.empty:
        df["Estado"] = "Normal"
        p95 = df["Monto"].quantile(0.95) if len(df) > 5 else 999999
        df.loc[
            (df["Monto"] > p95) & (df["Tipo"] == "Egreso"), "Estado"
        ] = "⚠️ Inconsistencia"

    return df, es_escaneado

def ocr_pdf_a_digital(pdf_bytes: bytes) -> tuple[pd.DataFrame, bytes]:
    if not OCR_DISPONIBLE:
        return pd.DataFrame(), b""

    images = convert_from_bytes(pdf_bytes)
    all_text = ""
    rows = []

    for idx, img in enumerate(images, 1):
        txt = pytesseract.image_to_string(img, lang="spa+eng")
        all_text += f"\n--- Página {idx} ---\n" + txt
        rows.extend(parsear_lineas_texto(txt, f"OCR Pág.{idx}"))

    df = (
        pd.DataFrame(rows)
        if rows
        else pd.DataFrame(
            columns=["Origen", "Fecha", "Concepto", "Monto", "Tipo", "Estado"]
        )
    )

    buffer_out = BytesIO()
    doc = SimpleDocTemplate(buffer_out, pagesize=letter)
    styles = getSampleStyleSheet()
    story = [
        Paragraph("Estado de Cuenta — Digitalizado vía OCR", styles["Heading1"]),
        Spacer(1, 12),
        Paragraph(all_text.replace("\n", "<br/>"), styles["BodyText"]),
    ]
    doc.build(story)
    buffer_out.seek(0)

    return df, buffer_out.getvalue()

def generar_pdf_reporte(
    empresa: str,
    periodo: str,
    ingresos: float,
    egresos: float,
    utilidad: float,
    margen: float,
    df_tx: pd.DataFrame,
    hallazgos: list,
) -> bytes:
    buffer = BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        rightMargin=1.8 * cm,
        leftMargin=1.8 * cm,
        topMargin=2 * cm,
        bottomMargin=2 * cm,
    )

    c_navy = colors.HexColor("#0F172A")
    c_blue = colors.HexColor("#1E3A8A")
    c_accent = colors.HexColor("#2563EB")
    c_light = colors.HexColor("#F8FAFC")
    c_dark = colors.HexColor("#334155")
    c_red = colors.HexColor("#DC2626")
    c_green = colors.HexColor("#16A34A")

    styles = getSampleStyleSheet()
    s_title = ParagraphStyle(
        "DocTitle",
        parent=styles["Normal"],
        fontName="Helvetica-Bold",
        fontSize=20,
        leading=24,
        textColor=c_navy,
    )
    s_subtitle = ParagraphStyle(
        "DocSubtitle",
        parent=styles["Normal"],
        fontName="Helvetica",
        fontSize=10,
        leading=14,
        textColor=colors.HexColor("#64748B"),
    )
    s_h2 = ParagraphStyle(
        "SectionH2",
        parent=styles["Normal"],
        fontName="Helvetica-Bold",
        fontSize=13,
        leading=17,
        textColor=c_blue,
        spaceBefore=14,
        spaceAfter=6,
    )
    s_body = ParagraphStyle(
        "Body",
        parent=styles["Normal"],
        fontName="Helvetica",
        fontSize=9,
        leading=13,
        textColor=c_dark,
    )

    story = []

    story.append(Paragraph("AUDITSAAS — INFORME EJECUTIVO", s_title))
    story.append(
        Paragraph(
            f"Empresa: <b>{empresa}</b> &nbsp;|&nbsp; Período: <b>{periodo}</b> &nbsp;|&nbsp; Emisión: {date.today().strftime('%d/%m/%Y')}",
            s_subtitle,
        )
    )
    story.append(Spacer(1, 8))
    story.append(HRFlowable(width="100%", thickness=2, color=c_accent, spaceAfter=14))

    story.append(Paragraph("1. RESUMEN DE SALUD FINANCIERA", s_h2))
    kpi_data = [
        [
            Paragraph(
                f"<b>TOTAL INGRESOS</b><br/><font size=12 color='{c_green}'>${ingresos:,.2f}</font>",
                s_body,
            ),
            Paragraph(
                f"<b>TOTAL EGRESOS</b><br/><font size=12 color='{c_red}'>${egresos:,.2f}</font>",
                s_body,
            ),
            Paragraph(
                f"<b>UTILIDAD NETA</b><br/><font size=12 color='{c_blue}'>${utilidad:,.2f}</font>",
                s_body,
            ),
            Paragraph(
                f"<b>MARGEN NETO</b><br/><font size=12 color='{c_navy}'>{margen:.1f}%</font>",
                s_body,
            ),
        ]
    ]
    t_kpi = Table(kpi_data, colWidths=[4.2 * cm] * 4)
    t_kpi.setStyle(
        TableStyle([
            ("BACKGROUND", (0, 0), (-1, -1), c_light),
            ("BOX", (0, 0), (-1, -1), 0.5, colors.HexColor("#CBD5E1")),
            ("INNERGRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#E2E8F0")),
            ("TOPPADDING", (0, 0), (-1, -1), 8),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
            ("ALIGN", (0, 0), (-1, -1), "CENTER"),
        ])
    )
    story.append(t_kpi)
    story.append(Spacer(1, 12))

    story.append(Paragraph("2. DIAGNÓSTICO FINANCIERO Y HALLAZGOS", s_h2))
    for h in hallazgos:
        story.append(Paragraph(f"• {h}", s_body))
        story.append(Spacer(1, 3))

    story.append(Spacer(1, 10))

    story.append(Paragraph("3. MUESTRA DE TRANSACCIONES AUDITADAS", s_h2))
    if not df_tx.empty:
        tx_sub = df_tx.head(15)
        t_rows = [["Origen", "Fecha", "Concepto", "Monto", "Tipo", "Estado"]]
        for _, r in tx_sub.iterrows():
            t_rows.append([
                str(r.get("Origen", "")),
                str(r.get("Fecha", "")),
                str(r.get("Concepto", ""))[:30],
                f"${r.get('Monto', 0):,.2f}",
                str(r.get("Tipo", "")),
                str(r.get("Estado", "")),
            ])
        t_tx = Table(
            t_rows,
            colWidths=[
                2 * cm,
                2.2 * cm,
                6.5 * cm,
                2.5 * cm,
                2 * cm,
                2.2 * cm,
            ],
        )
        t_tx.setStyle(
            TableStyle([
                ("BACKGROUND", (0, 0), (-1, 0), c_navy),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                ("FONTSIZE", (0, 0), (-1, 0), 8),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
                ("TOPPADDING", (0, 0), (-1, -1), 4),
                ("INNERGRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#E2E8F0")),
                ("BOX", (0, 0), (-1, -1), 0.5, colors.HexColor("#CBD5E1")),
            ])
        )
        story.append(t_tx)
    else:
        story.append(
            Paragraph("No se registraron transacciones detalladas.", s_body)
        )

    story.append(Spacer(1, 16))
    story.append(HRFlowable(width="100%", thickness=1, color=colors.HexColor("#E2E8F0"), spaceAfter=8))
    story.append(
        Paragraph(
            "<b>AuditSaaS Intelligence</b> — Informe generado de forma confidencial.",
            s_subtitle,
        )
    )

    doc.build(story)
    buffer.seek(0)
    return buffer.getvalue()


# ─────────────────────────────────────────────
# SIDEBAR / CONFIGURACIÓN DE PARÁMETROS
# ─────────────────────────────────────────────
st.sidebar.markdown("### ⚙️ Parámetros de Auditoría")
empresa_input = st.sidebar.text_input("Nombre de la Empresa", value="Mi PyME S.A. de C.V.")
periodo_input = st.sidebar.text_input("Período Auditoría", value="Enero 2026")

st.sidebar.markdown("---")
st.sidebar.markdown("### 🎯 Umbrales Anti-Fraude")
umbral_egreso = st.sidebar.number_input(
    "Alerta Egreso Mayor a ($)", value=25000.0, step=5000.0
)
alertar_duplicados = st.sidebar.checkbox("Detectar Montos Duplicados", value=True)

# BOTÓN DE WHATSAPP CON TU NÚMERO
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
# HEADER PRINCIPAL
# ─────────────────────────────────────────────
st.markdown(
    """
<div style="
    background: linear-gradient(135deg, #0F172A 0%, #1E3A8A 60%, #2563EB 100%);
    border-radius: 18px;
    padding: 2.2rem 2.5rem;
    margin-bottom: 2rem;
    color: white;
    box-shadow: 0 10px 25px -5px rgba(30, 58, 138, 0.3);
">
    <div style="display: flex; align-items: center; gap: 1.2rem;">
        <div style="font-size: 3rem; background: rgba(255,255,255,0.1); padding: 0.5rem 0.8rem; border-radius: 14px;">📊</div>
        <div>
            <h1 style="margin: 0; font-size: 2rem; font-weight: 800; color: white; letter-spacing: -0.02em;">
                AuditSaaS — Auditor Financiero B2B
            </h1>
            <p style="margin: 0.4rem 0 0 0; color: #93C5FD; font-size: 1rem; font-weight: 400;">
                Analítica bancaria avanzada, detección de anomalías y conversión de estados de cuenta a Excel.
            </p>
        </div>
    </div>
</div>
""",
    unsafe_allow_html=True,
)


# ─────────────────────────────────────────────
# CARGA DE ARCHIVO
# ─────────────────────────────────────────────
uploaded_file = st.file_uploader(
    "📄 Arrastra tu estado de cuenta (PDF, Excel o Imagen) para iniciar el análisis",
    type=["pdf", "xlsx", "xls", "png", "jpg", "jpeg"],
    help="Soporta PDFs digitales, estados de cuenta escaneados (OCR) y archivos Excel.",
)

if uploaded_file is not None:
    ext = uploaded_file.name.split(".")[-1].lower()
    df_tx = pd.DataFrame()
    es_escaneado = False
    pdf_digital = b""

    with st.spinner("🔍 Analizando estructura del documento..."):
        if ext == "pdf":
            df_tx, es_escaneado = extraer_transacciones_pdf(uploaded_file)
            if es_escaneado:
                st.warning(
                    "⚠️ El PDF parece ser un archivo escaneado (imagen). Ejecutando motor OCR..."
                )
                uploaded_file.seek(0)
                df_tx, pdf_digital = ocr_pdf_a_digital(uploaded_file.read())

        elif ext in ["xlsx", "xls"]:
            try:
                df_tx = pd.read_excel(uploaded_file)
                if "Tipo" not in df_tx.columns and "Concepto" in df_tx.columns:
                    df_tx["Tipo"] = df_tx["Concepto"].apply(clasificar_concepto)
                if "Monto" not in df_tx.columns:
                    st.error("El archivo Excel no contiene una columna 'Monto'.")
            except Exception as e:
                st.error(f"Error al leer el archivo Excel: {e}")

    # ─────────────────────────────────────────────
    # PROCESAMIENTO Y MÉTRICAS
    # ─────────────────────────────────────────────
    if not df_tx.empty and "Monto" in df_tx.columns:
        if "Tipo" in df_tx.columns:
            ingresos_calc = float(
                df_tx[df_tx["Tipo"] == "Ingreso"]["Monto"].sum()
            )
            egresos_calc = float(df_tx[df_tx["Tipo"] == "Egreso"]["Monto"].sum())
        else:
            ingresos_calc = float(df_tx["Monto"].sum())
            egresos_calc = 0.0

        util_neta = ingresos_calc - egresos_calc
        margen_calc = (
            (util_neta / ingresos_calc * 100) if ingresos_calc > 0 else 0.0
        )
        conteo_calc = len(df_tx)

        hallazgos = []
        if egresos_calc > ingresos_calc:
            hallazgos.append(
                f"<b>Alerta Crítica:</b> Los egresos (${egresos_calc:,.2f}) superan a los ingresos (${ingresos_calc:,.2f}). Flujo de caja negativo."
            )
        else:
            hallazgos.append(
                f"<b>Salud Financiera Positiva:</b> Margen neto del {margen_calc:.1f}% con una utilidad de ${util_neta:,.2f}."
            )

        egresos_altos = df_tx[
            (df_tx["Tipo"] == "Egreso") & (df_tx["Monto"] >= umbral_egreso)
        ]
        if not egresos_altos.empty:
            hallazgos.append(
                f"<b>Egresos Elevados:</b> Se detectaron {len(egresos_altos)} movimientos de egreso iguales o superiores al umbral de ${umbral_egreso:,.2f}."
            )

        if alertar_duplicados:
            dups = df_tx[df_tx.duplicated(subset=["Monto", "Tipo"], keep=False)]
            if not dups.empty:
                hallazgos.append(
                    f"<b>Posibles Duplicados:</b> Se identificaron {len(dups)} transacciones con montos idénticos."
                )

        # ── TARJETAS DE MÉTRICAS (KPIs) ──
        m1, m2, m3, m4 = st.columns(4)
        m1.metric("Total Ingresos", f"${ingresos_calc:,.2f}")
        m2.metric("Total Egresos", f"${egresos_calc:,.2f}")
        m3.metric("Utilidad Neta", f"${util_neta:,.2f}")
        m4.metric("Margen Neto", f"{margen_calc:.1f}%")

        st.markdown("<br/>", unsafe_allow_html=True)

        # ── PESTAÑAS DE CONTENIDO ──
        tab_tx, tab_pdf, tab_audit, tab_export = st.tabs([
            "📋 Transacciones Extraídas",
            "📄 Reporte PDF Ejecutivo",
            "🛡️ Diagnóstico Anti-Fraude",
            "📥 Conversión & Exportar a Excel",
        ])
