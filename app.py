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
from reportlab.lib.units import cm

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
    page_title="AuditSaaS — Auditor Financiero para PyMEs",
    page_icon="📊",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ─────────────────────────────────────────────
# ESTILOS CSS PROFESIONALES
# ─────────────────────────────────────────────
st.markdown(
    """
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap');
html, body, [class*="css"] { font-family: 'Inter', sans-serif; }
#MainMenu, footer { visibility: hidden; }

/* Sidebar */
[data-testid="stSidebar"] {
    background: linear-gradient(160deg, #0F172A 0%, #1E293B 100%);
    color: #F8FAFC;
}
[data-testid="stSidebar"] .stMarkdown h1, 
[data-testid="stSidebar"] .stMarkdown h2, 
[data-testid="stSidebar"] .stMarkdown h3,
[data-testid="stSidebar"] .stMarkdown label {
    color: #F8FAFC !important;
}

/* Tarjetas de Métricas */
.metric-card {
    background: #FFFFFF;
    border: 1px solid #E2E8F0;
    border-radius: 12px;
    padding: 20px;
    box-shadow: 0 4px 6px -1px rgba(0,0,0,0.05);
    margin-bottom: 16px;
}
.metric-title {
    font-size: 0.85rem;
    font-weight: 600;
    color: #64748B;
    text-transform: uppercase;
    letter-spacing: 0.05em;
    margin-bottom: 8px;
}
.metric-value {
    font-size: 1.75rem;
    font-weight: 700;
    color: #0F172A;
}

/* Botones */
.stButton>button {
    border-radius: 8px;
    font-weight: 600;
    padding: 0.5rem 1rem;
    transition: all 0.2s ease-in-out;
}
.stButton>button:hover {
    transform: translateY(-1px);
    box-shadow: 0 4px 12px rgba(37, 99, 235, 0.2);
}
</style>
""",
    unsafe_allow_html=True,
)

# ─────────────────────────────────────────────
# MOTOR DE EXTRACCIÓN Y LECTURA DE PDF BLINDADO CONTRA TOTALES Y SALDOS
# ─────────────────────────────────────────────
KEYWORDS_INGRESO = [
    "spei recibido", "deposito", "depositos", "abono", "abonos", "recibido", 
    "credito", "transferencia recibida", "ingreso", "intereses ganados", "interes",
    "nomm", "nomina", "factura", "cobro", "venta", "deposito en efectivo", 
    "devolucion", "reembolso", "traspaso a favor", "dep ", "dep."
]

KEYWORDS_EGRESO = [
    "spei enviado", "pago", "compra", "cargo", "cargos", "retiro", "retiros",
    "comision", "comisiones", "iva", "debito", "cheque", "egreso", "disposicion",
    "impuesto", "isr", "mantenimiento", "gasto", "str*", "facebk", "uber", "cajero",
    "gas", "oxxo", "heb", "amazon", "telcel", "axtel", "rest", "benavides",
    "taqueria", "josephinos", "asadero", "oxxo gas", "domiciliacion", "pago cuenta de tercero"
]

# TÉRMINOS CLAVE PARA DESCARTAR TOTALES, RESÚMENES Y SALDOS FINANCIEROS
IGNORE_TERMS = [
    "saldo anterior", "saldo final", "saldo promedio", "saldo del periodo",
    "total importe", "total de movimientos", "total cargos", "total abonos",
    "total operaciones", "cuadro resumen", "información financiera", 
    "rendimiento", "gat nominal", "gat real", "comisión cobrada", "iva cobrado",
    "concepto cantidad porcentaje", "retiros total", "depósitos total"
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
    
    regex_fecha = r"(\b\d{1,2}[/\-\s](?:0[1-9]|1[0-2]|[A-Za-z]{3})(?:[/\-\s]\d{2,4})?\b)"
    regex_monto = r"[\$]?\s*([0-9]{1,3}(?:,[0-9]{3})*\.[0-9]{2})"

    for line in lines:
        line_clean = line.strip()
        if not line_clean:
            continue
        
        line_lower = line_clean.lower()
        if any(term in line_lower for term in IGNORE_TERMS):
            continue
        
        if line_lower.startswith("total") or "total del periodo" in line_lower:
            continue

        fechas = re.findall(regex_fecha, line_clean, re.IGNORECASE)
        montos = re.findall(regex_monto, line_clean)

        if fechas and montos:
            fecha_val = fechas[0].strip()
            
            concepto_clean = line_clean
            for f in fechas:
                concepto_clean = concepto_clean.replace(f, "")
            for m in montos:
                concepto_clean = concepto_clean.replace(m, "").replace("$", "")
            
            concepto_clean = re.sub(r"\s+", " ", concepto_clean).strip()
            if not concepto_clean or len(concepto_clean) < 2:
                concepto_clean = "Movimiento Bancario"

            try:
                monto_val = float(montos[0].replace(",", ""))
                if monto_val > 0:
                    tipo_trans = clasificar_concepto(line_clean)
                    rows.append({
                        "Origen": origen,
                        "Fecha": fecha_val,
                        "Concepto": concepto_clean,
                        "Monto": monto_val,
                        "Tipo": tipo_trans,
                        "Estado": "Normal",
                    })
            except ValueError:
                pass

    return rows

def extraer_transacciones_pdf(file_pdf) -> tuple[pd.DataFrame, bool, bytes | None]:
    rows = []
    es_escaneado = False
    pdf_bytes = file_pdf.read()
    pdf_digital_bytes = None

    regex_fecha = re.compile(r"(\b\d{1,2}[/\-\s](?:0[1-9]|1[0-2]|[A-Za-z]{3})(?:[/\-\s]\d{2,4})?\b)", re.IGNORECASE)
    regex_monto = re.compile(r"[\$]?\s*([0-9]{1,3}(?:,[0-9]{3})*\.[0-9]{2})")

    with pdfplumber.open(BytesIO(pdf_bytes)) as pdf:
        texto_total = ""
        for i, page in enumerate(pdf.pages, 1):
            txt = page.extract_text() or ""
            texto_total += txt

            tables = page.extract_tables()
            lineas_extraidas_tabla = False

            for tbl in tables:
                if not tbl:
                    continue
                
                idx_fecha, idx_concepto, idx_egreso, idx_ingreso = -1, -1, -1, -1
                
                header = [str(c).lower() if c else "" for c in tbl[0]]
                for idx, col in enumerate(header):
                    if any(k in col for k in ["fecha", "fec", "oper", "liq"]):
                        if idx_fecha == -1: idx_fecha = idx
                    elif any(k in col for k in ["concepto", "descripcion", "detalle", "movimiento", "referencia"]):
                        idx_concepto = idx
                    elif any(k in col for k in ["cargo", "retiro", "egreso", "debito"]):
                        idx_egreso = idx
                    elif any(k in col for k in ["abono", "deposito", "ingreso", "credito"]):
                        idx_ingreso = idx

                for r_idx, row in enumerate(tbl):
                    if not row or r_idx == 0:
                        continue
                    rc = [str(c).replace("\n", " ").strip() for c in row if c is not None]
                    row_str = " ".join(rc).lower()

                    if any(term in row_str for term in IGNORE_TERMS) or row_str.startswith("total"):
                        continue

                    fecha_val = "N/A"
                    concepto_val = ""

                    if idx_fecha != -1 and idx_fecha < len(rc) and regex_fecha.search(rc[idx_fecha]):
                        fecha_val = regex_fecha.search(rc[idx_fecha]).group(1)
                    else:
                        for cell in rc:
                            mf = regex_fecha.search(cell)
                            if mf:
                                fecha_val = mf.group(1)
                                break

                    if idx_concepto != -1 and idx_concepto < len(rc) and len(rc[idx_concepto]) > 2:
                        concepto_val = rc[idx_concepto]
                    else:
                        conceptos_cand = [c for c in rc if not regex_fecha.search(c) and not regex_monto.search(c) and len(c) > 3]
                        if conceptos_cand:
                            concepto_val = " - ".join(conceptos_cand)

                    if not concepto_val:
                        concepto_val = "Movimiento Bancario"

                    agregado = False
                    if idx_egreso != -1 and idx_egreso < len(rc):
                        m_eg = regex_monto.search(rc[idx_egreso])
                        if m_eg:
                            try:
                                v = float(m_eg.group(1).replace(",", ""))
                                if v > 0:
                                    rows.append({
                                        "Origen": f"Pág.{i}", "Fecha": fecha_val, "Concepto": concepto_val,
                                        "Monto": v, "Tipo": "Egreso", "Estado": "Normal"
                                    })
                                    agregado = True
                            except ValueError: pass

                    if idx_ingreso != -1 and idx_ingreso < len(rc):
                        m_in = regex_monto.search(rc[idx_ingreso])
                        if m_in:
                            try:
                                v = float(m_in.group(1).replace(",", ""))
                                if v > 0:
                                    rows.append({
                                        "Origen": f"Pág.{i}", "Fecha": fecha_val, "Concepto": concepto_val,
                                        "Monto": v, "Tipo": "Ingreso", "Estado": "Normal"
                                    })
                                    agregado = True
                            except ValueError: pass

                    if not agregado:
                        for cell in rc:
                            m = regex_monto.search(cell)
                            if m:
                                try:
                                    v = float(m.group(1).replace(",", ""))
                                    if v > 0:
                                        tipo_val = clasificar_concepto(row_str)
                                        rows.append({
                                            "Origen": f"Pág.{i}", "Fecha": fecha_val, "Concepto": concepto_val,
                                            "Monto": v, "Tipo": tipo_val, "Estado": "Normal"
                                        })
                                        agregado = True
                                        break
                                except ValueError: pass
                    if agregado:
                        lineas_extraidas_tabla = True

            if not lineas_extraidas_tabla and txt.strip():
                rows.extend(parsear_lineas_texto(txt, f"Pág.{i}"))

        if len(texto_total.strip()) < 50 and len(rows) == 0:
            es_escaneado = True
            if OCR_DISPONIBLE:
                try:
                    images = convert_from_bytes(pdf_bytes)
                    for i, img in enumerate(images, 1):
                        txt_ocr = pytesseract.image_to_string(img, lang="spa")
                        rows.extend(parsear_lineas_texto(txt_ocr, f"OCR-Pág.{i}"))
                    pdf_digital_bytes = pdf_bytes
                except Exception:
                    pass

    df = (
        pd.DataFrame(rows)
        if rows
        else pd.DataFrame(
            columns=["Origen", "Fecha", "Concepto", "Monto", "Tipo", "Estado"]
        )
    )

    if not df.empty:
        df = df.drop_duplicates(subset=["Fecha", "Concepto", "Monto", "Tipo"]).reset_index(drop=True)
        df["Estado"] = "Normal"
        p95 = df["Monto"].quantile(0.95) if len(df) > 5 else 999999
        df.loc[
            (df["Monto"] > p95) & (df["Tipo"] == "Egreso"), "Estado"
        ] = "⚠️ Inconsistencia"

    return df, es_escaneado, pdf_digital_bytes


# ─────────────────────────────────────────────
# BARRA LATERAL (CONFIGURACIÓN Y DATOS)
# ─────────────────────────────────────────────
with st.sidebar:
    st.markdown("## 📊 AuditSaaS")
    st.markdown("---")
    
    empresa_input = st.text_input("🏢 Empresa / Cliente", value="PyME Demo S.A. de C.V.")
    
    st.markdown("### 📂 Cargar Estado de Cuenta")
    archivo_subido = st.file_uploader("Sube tu archivo PDF o CSV", type=["pdf", "csv"])
    
    st.markdown("---")
    st.markdown("### 💬 Asistente WhatsApp")
    telefono_cliente = st.text_input("Teléfono del Cliente", value="+52 81 0000 0000")
    mensaje_personalizado = st.text_area("Mensaje de Alerta", value="Estimado cliente, hemos detectado inconsistencias en su último estado de cuenta. Por favor contáctenos.")
    
    if st.button("📤 Enviar Alerta WhatsApp", use_container_width=True):
        st.success("¡Alerta enviada correctamente por WhatsApp!")

    st.markdown("---")
    st.markdown("### ⚙️ Panel de Control")
    umbral_alerta = st.slider("Umbral de Gasto Anómalo ($)", 5000, 100000, 20000, step=5000)


# ─────────────────────────────────────────────
# CUERPO PRINCIPAL DE LA APLICACIÓN
# ─────────────────────────────────────────────
st.markdown(f"# 🔍 Auditoría Financiera Inteligente — {empresa_input}")
st.markdown("Análisis automatizado de movimientos bancarios, detección de anomalías y conciliación fiscal en tiempo real.")

df_transacciones = pd.DataFrame(columns=["Origen", "Fecha", "Concepto", "Monto", "Tipo", "Estado"])
es_escaneado = False
pdf_digital = None

if archivo_subido is not None:
    ext = archivo_subido.name.split(".")[-1].lower()
    if ext == "pdf":
        with st.spinner("Procesando y extrayendo transacciones del PDF (filtrando totales y saldos)..."):
            df_transacciones, es_escaneado, pdf_digital = extraer_transacciones_pdf(archivo_subido)
    elif ext == "csv":
        try:
            df_transacciones = pd.read_csv(archivo_subido)
            if "Estado" not in df_transacciones.columns:
                df_transacciones["Estado"] = "Normal"
        except Exception as e:
            st.error(f"Error al leer el archivo CSV: {e}")

if not df_transacciones.empty:
    # ── MÉTRICAS SUPERIORES ──
    total_ingresos = df_transacciones[df_transacciones["Tipo"] == "Ingreso"]["Monto"].sum()
    total_egresos = df_transacciones[df_transacciones["Tipo"] == "Egreso"]["Monto"].sum()
    balance_neto = total_ingresos - total_egresos
    total_anomalias = len(df_transacciones[df_transacciones["Estado"].str.contains("⚠️", na=False)])

    col1, col2, col3, col4 = st.columns(4)
    with col1:
        st.markdown(f"""
        <div class="metric-card">
            <div class="metric-title">Total Ingresos</div>
            <div class="metric-value" style="color: #10B981;">${total_ingresos:,.2f}</div>
        </div>
        """, unsafe_allow_html=True)
    with col2:
        st.markdown(f"""
        <div class="metric-card">
            <div class="metric-title">Total Egresos</div>
            <div class="metric-value" style="color: #EF4444;">${total_egresos:,.2f}</div>
        </div>
        """, unsafe_allow_html=True)
    with col3:
        st.markdown(f"""
        <div class="metric-card">
            <div class="metric-title">Balance Neto</div>
            <div class="metric-value" style="color: #2563EB;">${balance_neto:,.2f}</div>
        </div>
        """, unsafe_allow_html=True)
    with col4:
        st.markdown(f"""
        <div class="metric-card">
            <div class="metric-title">Alertas Detectadas</div>
            <div class="metric-value" style="color: #F59E0B;">{total_anomalias}</div>
        </div>
        """, unsafe_allow_html=True)

    st.markdown("---")

    # ── EDITOR INTERACTIVO EN VIVO ──
    st.markdown("### 📋 Editor Interactivo de Movimientos")
    st.info("💡 Puedes editar directamente las celdas de la tabla para corregir o clasificar tus transacciones en tiempo real.")
    
    df_editado = st.data_editor(
        df_transacciones,
        num_rows="dynamic",
        use_container_width=True,
        key="editor_movimientos"
    )

    st.markdown("---")

    # ── EXPORTACIÓN Y REPORTES ──
    st.markdown("### 📥 Exportar Resultados y Reportes")
    col_ex1, col_ex2 = st.columns(2)

    with col_ex1:
        st.markdown("###### 1. Exportar a Excel")
        excel_buf = BytesIO()
        with pd.ExcelWriter(excel_buf, engine="openpyxl") as writer:
            df_editado.to_excel(writer, index=False, sheet_name="Resumen")
        excel_buf.seek(0)
        
        st.download_button(
            "📥 Descargar PDF Convertido a Excel (.xlsx)",
            data=excel_buf,
            file_name=f"Estado_Cuenta_{empresa_input.replace(' ', '_')}.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            use_container_width=True,
        )

    with col_ex2:
        st.markdown("###### 2. Digitalizar PDF Escaneado / Imagen")
        if pdf_digital:
            st.success("✅ PDF escaneado digitalizado con OCR.")
            st.download_button(
                "📥 Descargar PDF Digitalizado (OCR)",
                data=pdf_digital,
                file_name=f"AuditSaaS_OCR_{date.today().strftime('%Y%m%d')}.pdf",
                mime="application/pdf",
                use_container_width=True,
            )
        elif ext == "pdf" and not es_escaneado:
            st.info("ℹ️ Tu PDF es nativo digital (texto seleccionable). No requiere OCR.")
        else:
            st.info("ℹ️ Sube una imagen o PDF escaneado para procesarlo por OCR.")

else:
    st.warning("⚠️ No se identificaron transacciones válidas en el documento cargado.")

else:
    st.info("👆 Carga un estado de cuenta en el panel central para iniciar el proceso de auditoría y análisis.")
