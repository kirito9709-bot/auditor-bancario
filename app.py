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
[data-testid="stSidebar"] .stFileUploader label,
[data-testid="stSidebar"] .stNumberInput label,
[data-testid="stSidebar"] h1,
[data-testid="stSidebar"] h2,
[data-testid="stSidebar"] h3 { color: #F8FAFC !important; }
[data-testid="stSidebar"] [data-testid="stFileUploader"] {
    background: rgba(255,255,255,0.08);
    border-radius: 10px;
    padding: 8px;
}
[data-testid="stSidebar"] .stButton > button {
    background: #2563EB; color: white; border: none; border-radius: 8px;
}

/* ── Main background ── */
.main .block-container { padding-top: 1.5rem; padding-bottom: 3rem; }
.stApp { background-color: #F1F5F9; }

/* ── Metric cards override ── */
[data-testid="stMetric"] {
    background: white;
    border-radius: 14px;
    padding: 1.2rem 1.4rem;
    box-shadow: 0 2px 8px rgba(15,23,42,0.08);
    border-top: 4px solid #2563EB;
}
[data-testid="stMetricLabel"] { font-weight: 600; color: #475569 !important; font-size: 0.82rem; }
[data-testid="stMetricValue"] { font-size: 1.6rem !important; font-weight: 700; color: #0F172A !important; }

/* ── Tabs ── */
[data-testid="stTabs"] [role="tablist"] {
    background: white;
    border-radius: 12px;
    padding: 4px;
    box-shadow: 0 1px 4px rgba(15,23,42,0.08);
    gap: 4px;
}
[data-testid="stTabs"] button[role="tab"] {
    border-radius: 9px !important;
    font-weight: 600;
    font-size: 0.88rem;
    color: #64748B;
    padding: 8px 20px;
    border: none;
}
[data-testid="stTabs"] button[role="tab"][aria-selected="true"] {
    background: #2563EB !important;
    color: white !important;
}

/* ── Dataframe ── */
[data-testid="stDataFrame"] { border-radius: 12px; overflow: hidden; }

/* ── Download button ── */
.stDownloadButton > button {
    background: linear-gradient(135deg, #1E3A8A, #2563EB) !important;
    color: white !important;
    border: none !important;
    border-radius: 10px !important;
    font-weight: 600;
    padding: 0.65rem 1.6rem;
    font-size: 0.92rem;
    transition: all 0.2s;
}
.stDownloadButton > button:hover { opacity: 0.9; transform: translateY(-1px); }

/* ── Alerts / success / warning / error ── */
[data-testid="stAlert"] { border-radius: 10px !important; }
</style>
""",
    unsafe_allow_html=True,
)

# ─────────────────────────────────────────────
# HEADER VISUAL
# ─────────────────────────────────────────────
st.markdown(
    """
<div style="
    background: linear-gradient(135deg, #0F172A 0%, #1E3A8A 60%, #2563EB 100%);
    border-radius: 18px;
    padding: 2rem 2.5rem;
    margin-bottom: 1.8rem;
    display: flex; align-items: center; gap: 1.2rem;
    box-shadow: 0 4px 24px rgba(30,58,138,0.25);
">
    <div style="font-size:3rem; line-height:1;">📊</div>
    <div>
        <div style="font-size:1.75rem; font-weight:800; color:white; line-height:1.1;">
            AuditSaaS
        </div>
        <div style="font-size:0.95rem; color:#93C5FD; margin-top:4px; font-weight:400;">
            Auditor Financiero Inteligente para PyMEs · PDF · Excel · OCR · Recomendaciones
        </div>
    </div>
    <div style="margin-left:auto; text-align:right;">
        <div style="
            background:rgba(255,255,255,0.12); border-radius:8px;
            padding:6px 14px; color:#BAE6FD; font-size:0.78rem; font-weight:500;
        ">v2.0 — Profesional</div>
    </div>
</div>
""",
    unsafe_allow_html=True,
)

# ─────────────────────────────────────────────
# PALABRAS CLAVE
# ─────────────────────────────────────────────
PALABRAS_INGRESO = [
    "abono",
    "deposito",
    "depositos",
    "recibido",
    "credito",
    "transferencia recibida",
    "interes pagado",
    "ingreso",
    "venta",
    "cobro",
]
PALABRAS_EGRESO = [
    "cargo",
    "retiro",
    "pago",
    "compra",
    "comision",
    "iva",
    "spei enviado",
    "debito",
    "cheque",
    "egreso",
    "gasto",
    "servicio",
    "factura",
]


# ─────────────────────────────────────────────
# 1. MOTOR PDF
# ─────────────────────────────────────────────
def _clasificar(texto_lower):
    if any(w in texto_lower for w in PALABRAS_INGRESO):
        return "Ingreso"
    return "Egreso"


def _procesar_lineas(lines, origen):
    rows = []
    for line in lines:
        m = re.search(
            r"(\d{2}[/-]\d{2}[/-]\d{2,4}|\d{2}\s+[A-Za-z]{3})\s+(.*?)\s+[\$]?\s*([0-9,]+\.[0-9]{2})",
            line,
        )
        if m:
            fecha, concepto, monto_str = m.groups()
            rows.append(
                {
                    "Origen": origen,
                    "Fecha": fecha,
                    "Concepto": concepto.strip(),
                    "Monto": float(monto_str.replace(",", "")),
                    "Tipo": _clasificar(concepto.lower()),
                }
            )
    return rows


def extraer_transacciones_pdf(file_pdf):
    transacciones, paginas_ocr_texto, paginas_sin_texto = [], {}, []
    pdf_bytes = file_pdf.read()

    with pdfplumber.open(BytesIO(pdf_bytes)) as pdf:
        for num, page in enumerate(pdf.pages, 1):
            # A: tablas
            for table in page.extract_tables():
                for row in table:
                    if not row:
                        continue
                    rc = [
                        str(c).replace("\n", " ").strip() for c in row if c is not None
                    ]
                    if len(rc) < 3:
                        continue
                    for idx, cell in enumerate(rc):
                        mo = re.search(
                            r"[\$]?\s*([0-9]{1,3}(?:,[0-9]{3})*(?:\.[0-9]{2})?)", cell
                        )
                        if mo:
                            try:
                                val = float(mo.group(1).replace(",", ""))
                                if val > 0:
                                    texto = " ".join(rc).lower()
                                    if any(w in texto for w in PALABRAS_INGRESO):
                                        tipo = "Ingreso"
                                    elif any(w in texto for w in PALABRAS_EGRESO):
                                        tipo = "Egreso"
                                    else:
                                        tipo = (
                                            "Ingreso"
                                            if idx == len(rc) - 1
                                            else "Egreso"
                                        )
                                    transacciones.append(
                                        {
                                            "Origen": f"Pág.{num}",
                                            "Fecha": rc[0],
                                            "Concepto": rc[1]
                                            if len(rc) > 1
                                            else "Transacción",
                                            "Monto": val,
                                            "Tipo": tipo,
                                        }
                                    )
                                    break
                            except ValueError:
                                continue
            # B: texto digital
            text = page.extract_text() or ""
            if text.strip():
                transacciones.extend(_procesar_lineas(text.split("\n"), f"Pág.{num}"))
            else:
                paginas_sin_texto.append(num)

    # C: OCR
    if paginas_sin_texto and OCR_DISPONIBLE:
        with st.spinner(
            f"🔍 Aplicando OCR en {len(paginas_sin_texto)} página(s) escaneadas..."
        ):
            imgs = convert_from_bytes(pdf_bytes, dpi=300)
            for i, img in enumerate(imgs, 1):
                if i in paginas_sin_texto:
                    texto_ocr = pytesseract.image_to_string(img, lang="spa")
                    paginas_ocr_texto[i] = texto_ocr
                    if texto_ocr.strip():
                        transacciones.extend(
                            _procesar_lineas(texto_ocr.split("\n"), f"Pág.{i}")
                        )
    elif paginas_sin_texto and not OCR_DISPONIBLE:
        st.warning("⚠️ PDF escaneado detectado pero OCR no disponible.")

    df = (
        pd.DataFrame(transacciones)
        if transacciones
        else pd.DataFrame(columns=["Origen", "Fecha", "Concepto", "Monto", "Tipo"])
    )
    return df, bool(paginas_sin_texto), paginas_ocr_texto


# ─────────────────────────────────────────────
# 2. MOTOR EXCEL
# ─────────────────────────────────────────────
def extraer_transacciones_excel(file_excel):
    try:
        df_raw = pd.read_excel(file_excel, sheet_name=0, header=None)
    except Exception as e:
        st.error(f"No se pudo leer el Excel: {e}")
        return pd.DataFrame(columns=["Origen", "Fecha", "Concepto", "Monto", "Tipo"])

    header_row = 0
    for i, row in df_raw.iterrows():
        ne = row.dropna()
        if len(ne) >= 3 and any(isinstance(v, str) for v in ne):
            header_row = i
            break

    df = pd.read_excel(file_excel, sheet_name=0, header=header_row)
    df.columns = [str(c).strip().lower() for c in df.columns]
    df = df.dropna(how="all")

    def find(aliases):
        for a in aliases:
            for c in df.columns:
                if a in c:
                    return c
        return None

    col_fecha = find(["fecha", "date", "f.operacion", "día", "dia"])
    col_concepto = find(
        [
            "concepto",
            "descripcion",
            "descripción",
            "movimiento",
            "detalle",
            "referencia",
        ]
    )
    col_monto = find(["monto", "importe", "cantidad", "amount", "valor", "total"])
    col_cargo = find(["cargo", "egreso", "retiro", "debito", "débito", "salida"])
    col_abono = find(
        ["abono", "ingreso", "deposito", "depósito", "credito", "crédito", "entrada"]
    )

    rows = []
    if col_cargo and col_abono and not col_monto:
        for _, r in df.iterrows():
            cargo = pd.to_numeric(r.get(col_cargo), errors="coerce")
            abono = pd.to_numeric(r.get(col_abono), errors="coerce")
            if pd.notna(cargo) and cargo > 0:
                rows.append(
                    {
                        "Origen": "Excel",
                        "Fecha": str(r[col_fecha]).strip() if col_fecha else "",
                        "Concepto": str(r[col_concepto]).strip()
                        if col_concepto
                        else "Movimiento",
                        "Monto": float(cargo),
                        "Tipo": "Egreso",
                    }
                )
            if pd.notna(abono) and abono > 0:
                rows.append(
                    {
                        "Origen": "Excel",
                        "Fecha": str(r[col_fecha]).strip() if col_fecha else "",
                        "Concepto": str(r[col_concepto]).strip()
                        if col_concepto
                        else "Movimiento",
                        "Monto": float(abono),
                        "Tipo": "Ingreso",
                    }
                )
    elif col_monto:
        for _, r in df.iterrows():
            monto = pd.to_numeric(r.get(col_monto), errors="coerce")
            if pd.isna(monto) or monto == 0:
                continue
            concepto_txt = str(r.get(col_concepto, "")).lower() if col_concepto else ""
            tipo = _clasificar(concepto_txt)
            if monto < 0:
                tipo = "Egreso"
            rows.append(
                {
                    "Origen": "Excel",
                    "Fecha": str(r[col_fecha]).strip() if col_fecha else "",
                    "Concepto": str(r[col_concepto]).strip()
                    if col_concepto
                    else "Movimiento",
                    "Monto": abs(float(monto)),
                    "Tipo": tipo,
                }
            )
    else:
        st.warning(
            "No se encontraron columnas de monto. Verifica encabezados: 'Monto', 'Cargo', 'Abono'."
        )

    result = (
        pd.DataFrame(rows)
        if rows
        else pd.DataFrame(columns=["Origen", "Fecha", "Concepto", "Monto", "Tipo"])
    )
    return result


# ─────────────────────────────────────────────
# 3. RECOMENDACIONES
# ─────────────────────────────────────────────
def generar_recomendaciones(ingresos, egresos, margen_neto_pct, conteo, df):
    recs = []

    if ingresos == 0:
        recs.append(
            (
                "danger",
                "Sin ingresos registrados",
                "No se detectaron entradas. Verifica que el archivo tenga columnas de abono/ingreso reconocibles.",
            )
        )
    elif margen_neto_pct < 0:
        recs.append(
            (
                "danger",
                "Flujo de caja negativo",
                f"Los egresos superan a los ingresos en {abs(margen_neto_pct):.1f}%. "
                "Revisa gastos recurrentes no esenciales y reduce compromisos fijos de forma urgente.",
            )
        )
    elif margen_neto_pct < 15:
        recs.append(
            (
                "warning",
                "Margen neto ajustado",
                f"Margen neto del {margen_neto_pct:.1f}% (umbral saludable ≥15%). "
                "Identifica los 3 mayores egresos y evalúa si pueden renegociarse o eliminarse.",
            )
        )
    else:
        recs.append(
            (
                "success",
                "Flujo de caja saludable",
                f"Margen neto del {margen_neto_pct:.1f}% — buena salud financiera. "
                "Considera canalizar el excedente a un fondo de reserva o capital de trabajo.",
            )
        )

    if not df.empty and egresos > 0:
        egr = df[df["Tipo"] == "Egreso"]
        if not egr.empty:
            top3 = egr.groupby("Concepto")["Monto"].sum().nlargest(3)
            pct = top3.sum() / egresos * 100
            if pct > 60:
                recs.append(
                    (
                        "warning",
                        "Alta concentración de gastos",
                        f"{pct:.0f}% de egresos en: {', '.join(top3.index.tolist())}. "
                        "Renegociar o diversificar estos rubros puede liberar liquidez significativa.",
                    )
                )

    if conteo > 0 and egresos > 0:
        ticket = egresos / conteo
        if ticket < 50:
            recs.append(
                (
                    "info",
                    "Muchas transacciones de bajo monto",
                    f"Ticket promedio de egreso: ${ticket:,.2f}. "
                    "Consolida compras pequeñas para reducir comisiones bancarias y simplificar la contabilidad.",
                )
            )

    if ingresos > 0:
        ratio = egresos / ingresos
        if ratio > 0.9:
            recs.append(
                (
                    "danger",
                    "Egresos críticos vs ingresos",
                    f"Gastas el {ratio * 100:.0f}% de tus ingresos. "
                    "Define un techo de gasto del 80% y crea una reserva mínima de 3 meses de operación.",
                )
            )

    if margen_neto_pct > 10 and ingresos > 0:
        reserva = (ingresos - egresos) * 0.3
        recs.append(
            (
                "success",
                "Oportunidad de ahorro",
                f"Con tu excedente, podrías reservar ${reserva:,.2f} (30% del flujo positivo). "
                "Busca cuentas empresariales con rendimiento ≥ inflación o CETES empresariales.",
            )
        )

    if margen_neto_pct > 20:
        recs.append(
            (
                "info",
                "Considera invertir en crecimiento",
                "Tu margen neto es robusto. Evalúa reinvertir en marketing digital, automatización "
                "o inventario estratégico para escalar tu negocio con bajo riesgo.",
            )
        )

    return recs


# ─────────────────────────────────────────────
# 4. INFORME EJECUTIVO PDF
# ─────────────────────────────────────────────
def _estilos_reporte():
    styles = getSampleStyleSheet()
    azul = colors.HexColor("#1E3A8A")
    azul2 = colors.HexColor("#2563EB")
    gris = colors.HexColor("#475569")
    extra = {
        "Titulo": ParagraphStyle(
            "Titulo",
            parent=styles["Normal"],
            fontSize=22,
            textColor=azul,
            fontName="Helvetica-Bold",
            spaceAfter=4,
        ),
        "Sub": ParagraphStyle(
            "Sub",
            parent=styles["Normal"],
            fontSize=13,
            textColor=azul2,
            fontName="Helvetica-Bold",
            spaceBefore=14,
            spaceAfter=6,
        ),
        "Body": ParagraphStyle(
            "Body", parent=styles["Normal"], fontSize=10, textColor=gris, leading=14
        ),
        "RecTitle": ParagraphStyle(
            "RecTitle",
            parent=styles["Normal"],
            fontSize=11,
            textColor=azul,
            fontName="Helvetica-Bold",
            spaceAfter=2,
        ),
        "Small": ParagraphStyle(
            "Small",
            parent=styles["Normal"],
            fontSize=8,
            textColor=colors.HexColor("#94A3B8"),
        ),
    }
    return {**styles, **extra}


def generar_informe_ejecutivo(
    ingresos,
    egresos,
    util_bruta,
    util_neta,
    mb_pct,
    mn_pct,
    conteo,
    dictamen,
    recs,
    nombre_archivo,
):
    buf = BytesIO()
    doc = SimpleDocTemplate(
        buf,
        pagesize=letter,
        rightMargin=2 * cm,
        leftMargin=2 * cm,
        topMargin=2 * cm,
        bottomMargin=2 * cm,
    )
    s = _estilos_reporte()
    story = []
    hoy = date.today().strftime("%d/%m/%Y")

    # Portada
    story += [
        Paragraph("INFORME EJECUTIVO DE AUDITORÍA FINANCIERA", s["Titulo"]),
        Paragraph(f"Archivo analizado: <b>{nombre_archivo}</b>", s["Body"]),
        Paragraph(f"Generado por AuditSaaS · Fecha: {hoy}", s["Small"]),
        Spacer(1, 8),
        HRFlowable(width="100%", thickness=2, color=colors.HexColor("#2563EB")),
        Spacer(1, 12),
    ]

    # Dictamen
    story += [
        Paragraph("1. Dictamen de Integridad", s["Sub"]),
        Paragraph(dictamen, s["Body"]),
        Spacer(1, 10),
    ]

    # KPIs
    story.append(Paragraph("2. Indicadores Financieros Clave", s["Sub"]))
    tabla_kpis = [
        ["Indicador", "Valor", "Interpretación"],
        ["Ingresos Totales", f"${ingresos:,.2f}", "Total de abonos / entradas"],
        ["Egresos Totales", f"${egresos:,.2f}", "Total de cargos / salidas"],
        [
            "Margen Bruto Estimado",
            f"${util_bruta:,.2f}",
            f"{mb_pct:.1f}% sobre ingresos",
        ],
        ["Margen Neto", f"${util_neta:,.2f}", f"{mn_pct:.1f}% del flujo"],
        ["Total Transacciones", f"{conteo} movs.", "Operaciones detectadas"],
    ]
    t = Table(tabla_kpis, colWidths=[6 * cm, 4.5 * cm, 7 * cm])
    t.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1E3A8A")),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                ("FONTSIZE", (0, 0), (-1, -1), 9),
                ("BACKGROUND", (0, 1), (-1, -1), colors.HexColor("#F8FAFC")),
                (
                    "ROWBACKGROUNDS",
                    (0, 1),
                    (-1, -1),
                    [colors.HexColor("#F8FAFC"), colors.white],
                ),
                ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#CBD5E1")),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("TOPPADDING", (0, 0), (-1, -1), 6),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
            ]
        )
    )
    story += [t, Spacer(1, 14)]

    # Recomendaciones
    if recs:
        story.append(Paragraph("3. Recomendaciones Financieras", s["Sub"]))
        iconos = {"danger": "🔴", "warning": "🟡", "success": "🟢", "info": "💡"}
        for nivel, titulo, texto in recs:
            ico = iconos.get(nivel, "•")
            story.append(Paragraph(f"<b>{ico} {titulo}</b>", s["RecTitle"]))
            story.append(Paragraph(texto, s["Body"]))
            story.append(Spacer(1, 8))

    doc.build(story)
    buf.seek(0)
    return buf


# ─────────────────────────────────────────────
# 5. CONVERTIDOR PDF ESCANEADO → PDF DIGITAL
# ─────────────────────────────────────────────
def convertir_a_pdf_digital(paginas_ocr_texto, nombre_original):
    """Genera un PDF limpio y legible con el texto extraído por OCR, organizado por páginas."""
    buf = BytesIO()
    doc = SimpleDocTemplate(
        buf,
        pagesize=A4,
        rightMargin=2 * cm,
        leftMargin=2 * cm,
        topMargin=2 * cm,
        bottomMargin=2 * cm,
    )
    s = _estilos_reporte()
    story = []
    hoy = date.today().strftime("%d/%m/%Y")

    azul = colors.HexColor("#1E3A8A")
    PagTitulo = ParagraphStyle(
        "PagTitulo",
        parent=s["Normal"],
        fontSize=11,
        fontName="Helvetica-Bold",
        textColor=azul,
        spaceBefore=10,
        spaceAfter=4,
    )
    Cuerpo = ParagraphStyle(
        "Cuerpo",
        parent=s["Normal"],
        fontSize=9,
        leading=13,
        textColor=colors.HexColor("#1E293B"),
    )

    # Portada
    story += [
        Paragraph("DOCUMENTO DIGITAL — TEXTO EXTRAÍDO POR OCR", s["Titulo"]),
        Paragraph(f"Archivo original: <b>{nombre_original}</b>", s["Body"]),
        Paragraph(f"Convertido por AuditSaaS · {hoy}", s["Small"]),
        Spacer(1, 6),
        HRFlowable(width="100%", thickness=2, color=azul),
        Spacer(1, 12),
        Paragraph(
            "Este documento contiene el texto extraído automáticamente mediante OCR "
            "(reconocimiento óptico de caracteres) de cada página del PDF original escaneado. "
            "La precisión depende de la calidad del escaneo original.",
            s["Body"],
        ),
        PageBreak(),
    ]

    for num_pag in sorted(paginas_ocr_texto.keys()):
        texto = paginas_ocr_texto[num_pag].strip()
        if not texto:
            continue
        story.append(Paragraph(f"── PÁGINA {num_pag} ──", PagTitulo))
        story.append(
            HRFlowable(width="100%", thickness=0.5, color=colors.HexColor("#CBD5E1"))
        )
        story.append(Spacer(1, 4))
        # Divide en párrafos para mejor legibilidad
        for linea in texto.split("\n"):
            linea = linea.strip()
            if linea:
                try:
                    story.append(Paragraph(linea, Cuerpo))
                except Exception:
                    story.append(Paragraph(re.sub(r"[<>&]", " ", linea), Cuerpo))
        story.append(Spacer(1, 16))

    doc.build(story)
    buf.seek(0)
    return buf


# ─────────────────────────────────────────────
# 6. SIDEBAR
# ─────────────────────────────────────────────
with st.sidebar:
    st.markdown(
        """
    <div style="text-align:center; padding:1rem 0 1.5rem;">
        <div style="font-size:2.5rem;">📊</div>
        <div style="font-size:1.1rem; font-weight:700; color:white;">AuditSaaS</div>
        <div style="font-size:0.72rem; color:#93C5FD;">Auditor Financiero para PyMEs</div>
    </div>
    """,
        unsafe_allow_html=True,
    )

    st.markdown("**📂 Estado de Cuenta**")
    archivo = st.file_uploader(
        "PDF o Excel",
        type=["pdf", "xlsx", "xls"],
        help="Acepta estados de cuenta en PDF (digital o escaneado) y Excel (.xlsx / .xls)",
    )

    st.markdown("---")
    st.markdown("**🔍 Verificación Anti-Fraude**")
    st.caption("Opcional: ingresa los totales de la carátula para cotejar integridad.")
    total_ing_decl = st.number_input(
        "Ingresos declarados ($)", value=0.0, min_value=0.0
    )
    total_egr_decl = st.number_input("Egresos declarados ($)", value=0.0, min_value=0.0)
    conteo_decl = st.number_input(
        "Nº transacciones declarado", value=0, min_value=0, step=1
    )

    st.markdown("---")
    st.markdown(
        """
    <div style="font-size:0.72rem; color:#94A3B8; line-height:1.6;">
    ✅ PDF digital & escaneado (OCR)<br>
    ✅ Excel con columnas flexibles<br>
    ✅ Auditoría anti-fraude<br>
    ✅ Recomendaciones personalizadas<br>
    ✅ Exportación a PDF profesional<br>
    ✅ Conversión PDF escaneado → digital
    </div>
    """,
        unsafe_allow_html=True,
    )

# ─────────────────────────────────────────────
# 7. PANTALLA DE BIENVENIDA
# ─────────────────────────────────────────────
if archivo is None:
    col_a, col_b, col_c = st.columns(3)

    def feature_card(icon, title, desc, col):
        col.markdown(
            f"""
        <div style="background:white; border-radius:14px; padding:1.5rem;
                    box-shadow:0 2px 8px rgba(15,23,42,0.08); height:100%;">
            <div style="font-size:2rem; margin-bottom:.5rem;">{icon}</div>
            <div style="font-weight:700; font-size:1rem; color:#0F172A; margin-bottom:.4rem;">{title}</div>
            <div style="font-size:0.85rem; color:#64748B; line-height:1.5;">{desc}</div>
        </div>
        """,
            unsafe_allow_html=True,
        )

    feature_card(
        "📄",
        "PDF Digital y Escaneado",
        "Lee tablas y texto de PDFs nativos. Si está escaneado, aplica OCR automáticamente.",
        col_a,
    )
    feature_card(
        "📊",
        "Excel Flexible",
        "Detecta columnas de cargo/abono con cualquier nombre o idioma y las procesa al instante.",
        col_b,
    )
    feature_card(
        "🛡️",
        "Auditoría Anti-Fraude",
        "Coteja totales declarados vs. calculados para detectar alteraciones en el documento.",
        col_c,
    )

    st.markdown("<br>", unsafe_allow_html=True)
    col_d, col_e, col_f = st.columns(3)
    feature_card(
        "💡",
        "Recomendaciones Financieras",
        "Análisis automático del flujo de caja con consejos accionables para tu PyME.",
        col_d,
    )
    feature_card(
        "📑",
        "Informe Ejecutivo PDF",
        "Descarga un reporte profesional con KPIs, dictamen y recomendaciones listo para presentar.",
        col_e,
    )
    feature_card(
        "🔄",
        "Convertir PDF a Digital",
        "Transforma un PDF escaneado en un PDF digital con texto buscable y estructurado.",
        col_f,
    )

    st.markdown("<br>", unsafe_allow_html=True)
    st.info(
        "👈 **Sube tu estado de cuenta** en la barra lateral para comenzar el análisis."
    )
    st.stop()

# ─────────────────────────────────────────────
# 8. PROCESAMIENTO
# ─────────────────────────────────────────────
ext = archivo.name.rsplit(".", 1)[-1].lower()
es_escaneado = False
paginas_ocr = {}

if ext == "pdf":
    with st.spinner("📄 Procesando PDF..."):
        df_tx, es_escaneado, paginas_ocr = extraer_transacciones_pdf(archivo)
    if es_escaneado:
        st.info("🖼️ **PDF escaneado detectado** — se aplicó OCR para extraer el texto.")
else:
    with st.spinner("📊 Leyendo Excel..."):
        df_tx = extraer_transacciones_excel(archivo)

if df_tx.empty:
    st.warning(
        "⚠️ No se pudieron extraer transacciones. "
        "**PDF:** verifica que no esté protegido con contraseña. "
        "**Excel:** usa encabezados como 'Monto', 'Cargo', 'Abono', 'Concepto', 'Fecha'."
    )
    st.stop()

# ─────────────────────────────────────────────
# CÁLCULOS
# ─────────────────────────────────────────────
ing_df = df_tx[df_tx["Tipo"] == "Ingreso"]
egr_df = df_tx[df_tx["Tipo"] == "Egreso"]
ingresos_calc = ing_df["Monto"].sum()
egresos_calc = egr_df["Monto"].sum()
conteo_calc = len(df_tx)

util_bruta = ingresos_calc - (egresos_calc * 0.7)
mb_pct = (util_bruta / ingresos_calc * 100) if ingresos_calc > 0 else 0
util_neta = ingresos_calc - egresos_calc
mn_pct = (util_neta / ingresos_calc * 100) if ingresos_calc > 0 else 0

ing_ok = not (total_ing_decl > 0 and abs(ingresos_calc - total_ing_decl) > 0.01)
egr_ok = not (total_egr_decl > 0 and abs(egresos_calc - total_egr_decl) > 0.01)
cnt_ok = not (conteo_decl > 0 and conteo_calc != conteo_decl)
todo_ok = ing_ok and egr_ok and cnt_ok

dictamen_str = (
    "✅ Documento Íntegro — Sin Alteraciones Detectadas"
    if todo_ok
    else "🚨 ALERTA — Inconsistencia entre movimientos y carátula declarada"
)

recomendaciones = generar_recomendaciones(
    ingresos_calc, egresos_calc, mn_pct, conteo_calc, df_tx
)

# ─────────────────────────────────────────────
# 9. TABS
# ─────────────────────────────────────────────
tab1, tab2, tab3, tab4 = st.tabs(
    [
        "📊 Resumen Ejecutivo",
        "📋 Transacciones",
        "💡 Recomendaciones",
        "📄 Reportes y Descargas",
    ]
)

# ── TAB 1: RESUMEN ──────────────────────────
with tab1:
    # KPIs principales
    st.markdown("#### Indicadores Clave del Período")
    k1, k2, k3, k4 = st.columns(4)
    k1.metric("💰 Ingresos Totales", f"${ingresos_calc:,.2f}")
    k2.metric("💸 Egresos Totales", f"${egresos_calc:,.2f}")
    k3.metric(
        "📈 Margen Neto",
        f"${util_neta:,.2f}",
        f"{mn_pct:.1f}%",
        delta_color="normal" if util_neta >= 0 else "inverse",
    )
    k4.metric(
        "🔢 Transacciones",
        f"{conteo_calc}",
        f"{len(ing_df)} abonos · {len(egr_df)} cargos",
        delta_color="off",
    )

    st.markdown("<br>", unsafe_allow_html=True)

    # Margen bruto
    col_mb, col_mn = st.columns(2)
    col_mb.metric(
        "🏷️ Margen Bruto Estimado",
        f"${util_bruta:,.2f}",
        f"{mb_pct:.1f}% sobre ingresos",
    )
    col_mn.metric(
        "🎯 Ratio Egreso/Ingreso",
        f"{(egresos_calc / ingresos_calc * 100 if ingresos_calc else 0):.1f}%",
        "Óptimo < 80%",
        delta_color="off",
    )

    st.markdown("---")

    # Auditoría anti-fraude
    st.markdown("#### 🛡️ Auditoría de Integridad")

    dictamen_color = "#059669" if todo_ok else "#DC2626"
    dictamen_bg = "#ECFDF5" if todo_ok else "#FEF2F2"
    dictamen_borde = "#6EE7B7" if todo_ok else "#FCA5A5"
    st.markdown(
        f"""
    <div style="background:{dictamen_bg}; border:1.5px solid {dictamen_borde};
                border-radius:12px; padding:1rem 1.4rem; margin-bottom:1rem;">
        <span style="font-size:1rem; font-weight:700; color:{dictamen_color};">
            {dictamen_str}
        </span>
    </div>
    """,
        unsafe_allow_html=True,
    )

    a1, a2, a3 = st.columns(3)

    def audit_card(col, ok, label_ok, label_fail, detalle_ok, detalle_fail):
        if ok:
            col.success(f"✅ **{label_ok}**\n\n{detalle_ok}")
        else:
            col.error(f"❌ **{label_fail}**\n\n{detalle_fail}")

    audit_card(
        a1,
        ing_ok,
        "Ingresos coinciden",
        "Descuadre en Ingresos",
        f"Calculado: ${ingresos_calc:,.2f}",
        f"Calculado: ${ingresos_calc:,.2f} | Declarado: ${total_ing_decl:,.2f}",
    )
    audit_card(
        a2,
        egr_ok,
        "Egresos coinciden",
        "Descuadre en Egresos",
        f"Calculado: ${egresos_calc:,.2f}",
        f"Calculado: ${egresos_calc:,.2f} | Declarado: ${total_egr_decl:,.2f}",
    )
    audit_card(
        a3,
        cnt_ok,
        "Conteo correcto",
        "Diferencia en conteo",
        f"Total: {conteo_calc} transacciones",
        f"Leídas: {conteo_calc} | Declaradas: {conteo_decl}",
    )

# ── TAB 2: TRANSACCIONES ──────────────────────
with tab2:
    st.markdown("#### 📋 Detalle de Movimientos Detectados")

    col_fil1, col_fil2, col_fil3 = st.columns([2, 1, 1])
    with col_fil1:
        buscar = st.text_input(
            "🔍 Buscar concepto", placeholder="Ej. SPEI, comisión, nómina..."
        )
    with col_fil2:
        tipo_fil = st.selectbox("Tipo", ["Todos", "Ingreso", "Egreso"])
    with col_fil3:
        orden = st.selectbox("Ordenar por", ["Monto ↓", "Monto ↑", "Fecha"])

    df_view = df_tx.copy()
    if buscar:
        df_view = df_view[
            df_view["Concepto"].str.contains(buscar, case=False, na=False)
        ]
    if tipo_fil != "Todos":
        df_view = df_view[df_view["Tipo"] == tipo_fil]
    if orden == "Monto ↓":
        df_view = df_view.sort_values("Monto", ascending=False)
    elif orden == "Monto ↑":
        df_view = df_view.sort_values("Monto", ascending=True)
    else:
        df_view = df_view.sort_values("Fecha")

    st.dataframe(
        df_view.style.format({"Monto": "${:,.2f}"}).apply(
            lambda row: [
                "background-color:#ECFDF5; color:#065F46"
                if row["Tipo"] == "Ingreso"
                else "background-color:#FEF2F2; color:#991B1B"
                if col == "Tipo"
                else ""
                for col in row.index
            ],
            axis=1,
        ),
        use_container_width=True,
        height=420,
    )
    st.caption(f"Mostrando **{len(df_view)}** de **{conteo_calc}** transacciones")

# ── TAB 3: RECOMENDACIONES ──────────────────
with tab3:
    st.markdown("#### 💡 Recomendaciones Financieras Personalizadas")
    st.caption("Basadas en el análisis automático de tus movimientos.")
    st.markdown("<br>", unsafe_allow_html=True)

    colores_nivel = {
        "danger": ("#FEF2F2", "#DC2626", "#FCA5A5", "🔴"),
        "warning": ("#FFFBEB", "#D97706", "#FCD34D", "🟡"),
        "success": ("#ECFDF5", "#059669", "#6EE7B7", "🟢"),
        "info": ("#EFF6FF", "#2563EB", "#93C5FD", "💡"),
    }

    for nivel, titulo, texto in recomendaciones:
        bg, txt_color, borde, ico = colores_nivel.get(nivel, colores_nivel["info"])
        st.markdown(
            f"""
        <div style="background:{bg}; border-left:4px solid {borde};
                    border-radius:10px; padding:1.1rem 1.4rem; margin-bottom:1rem;
                    box-shadow:0 1px 4px rgba(0,0,0,0.05);">
            <div style="font-weight:700; font-size:1rem; color:{txt_color}; margin-bottom:.4rem;">
                {ico} {titulo}
            </div>
            <div style="font-size:0.92rem; color:#374151; line-height:1.6;">{texto}</div>
        </div>
        """,
            unsafe_allow_html=True,
        )

# ── TAB 4: REPORTES ─────────────────────────
with tab4:
    st.markdown("#### 📄 Reportes y Exportaciones")

    col_r1, col_r2 = st.columns(2)

    with col_r1:
        st.markdown(
            """
        <div style="background:white; border-radius:14px; padding:1.4rem;
                    box-shadow:0 2px 8px rgba(15,23,42,0.08); margin-bottom:1rem;">
            <div style="font-size:1.5rem; margin-bottom:.5rem;">📑</div>
            <div style="font-weight:700; font-size:1rem; color:#0F172A; margin-bottom:.3rem;">
                Informe Ejecutivo PDF
            </div>
            <div style="font-size:0.85rem; color:#64748B; line-height:1.5; margin-bottom:1rem;">
                Reporte profesional con KPIs, dictamen de auditoría y recomendaciones.
                Listo para presentar a socios, contadores o bancos.
            </div>
        </div>
        """,
            unsafe_allow_html=True,
        )
        pdf_informe = generar_informe_ejecutivo(
            ingresos_calc,
            egresos_calc,
            util_bruta,
            util_neta,
            mb_pct,
            mn_pct,
            conteo_calc,
            dictamen_str,
            recomendaciones,
            archivo.name,
        )
        st.download_button(
            "📥 Descargar Informe Ejecutivo",
            data=pdf_informe,
            file_name=f"AuditSaaS_Informe_{date.today().strftime('%Y%m%d')}.pdf",
            mime="application/pdf",
            use_container_width=True,
        )

    with col_r2:
        st.markdown(
            """
        <div style="background:white; border-radius:14px; padding:1.4rem;
                    box-shadow:0 2px 8px rgba(15,23,42,0.08); margin-bottom:1rem;">
            <div style="font-size:1.5rem; margin-bottom:.5rem;">🔄</div>
            <div style="font-weight:700; font-size:1rem; color:#0F172A; margin-bottom:.3rem;">
                Convertir PDF Escaneado → PDF Digital
            </div>
            <div style="font-size:0.85rem; color:#64748B; line-height:1.5; margin-bottom:1rem;">
                Genera un PDF con el texto extraído por OCR organizado por página.
                El resultado es un documento legible, buscable y listo para archivar.
            </div>
        </div>
        """,
            unsafe_allow_html=True,
        )

        if es_escaneado and paginas_ocr:
            pdf_digital = convertir_a_pdf_digital(paginas_ocr, archivo.name)
            st.download_button(
                "📥 Descargar PDF Digital (OCR)",
                data=pdf_digital,
                file_name=f"AuditSaaS_Digital_{date.today().strftime('%Y%m%d')}.pdf",
                mime="application/pdf",
                use_container_width=True,
            )
        elif ext == "pdf" and not es_escaneado:
            st.info(
                "✅ Tu PDF ya es digital (tiene texto embebido). No requiere conversión."
            )
        else:
            st.info(
                "📂 Sube un PDF escaneado para habilitar la conversión a PDF digital."
            )

    st.markdown("---")

    # Descarga de transacciones en Excel
    st.markdown("##### 📊 Exportar transacciones a Excel")
    excel_buf = BytesIO()
    with pd.ExcelWriter(excel_buf, engine="openpyxl") as writer:
        df_tx.to_excel(writer, index=False, sheet_name="Transacciones")
        resumen = pd.DataFrame(
            {
                "Indicador": ["Ingresos", "Egresos", "Margen Neto", "Transacciones"],
                "Valor": [ingresos_calc, egresos_calc, util_neta, conteo_calc],
            }
        )
        resumen.to_excel(writer, index=False, sheet_name="Resumen")
    excel_buf.seek(0)
    st.download_button(
        "📥 Descargar Transacciones en Excel",
        data=excel_buf,
        file_name=f"AuditSaaS_Transacciones_{date.today().strftime('%Y%m%d')}.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        use_container_width=False,
    )
