from datetime import date
from io import BytesIO
import re
import pandas as pd
import pdfplumber
import streamlit as st

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, letter
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import cm
from reportlab.platypus import HRFlowable, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

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
    background: linear-gradient(160deg, #0F172A 0%, #1E3A8A 100%) !important;
}
[data-testid="stSidebar"] * { color: #E2E8F0 !important; }
[data-testid="stSidebar"] .stSelectbox label,
[data-testid="stSidebar"] .stNumberInput label,
[data-testid="stSidebar"] .stTextInput label {
    color: #93C5FD !important;
    font-weight: 600;
}

/* Metric Cards */
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

/* Botones */
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

/* Uploader */
[data-testid="stFileUploader"] {
    background: #F8FAFC;
    border: 2px dashed #CBD5E1;
    border-radius: 14px;
    padding: 1rem;
}
</style>
""",
    unsafe_allow_html=True,
)

# ─────────────────────────────────────────────
# FUNCIONES DE PROCESAMIENTO (MOTOR BBVA REAL CORREGIDO)
# ─────────────────────────────────────────────


def clasificar_concepto_bbva(texto: str) -> str:
  t = texto.lower()
  if any(
      k in t
      for k in [
          "deposito",
          "abono",
          "spei recibido",
          "transferencia recibida",
          "recibido",
      ]
  ):
    return "Ingreso"
  return "Egreso"


def extraer_transacciones_pdf(file_pdf) -> tuple[pd.DataFrame, bool]:
  rows = []
  es_escaneado = False
  pdf_bytes = file_pdf.read()

  with pdfplumber.open(BytesIO(pdf_bytes)) as pdf:
    texto_total = ""
    for i, page in enumerate(pdf.pages, 1):
      # Extracción mediante tabla de pdfplumber para asegurar formato estructurado original
      tables = page.extract_tables()
      if tables:
        for table in tables:
          for row in table:
            if not row:
              continue
            row_clean = [str(cell).strip() if cell else "" for cell in row]
            texto_fila = " ".join(row_clean)
            
            # Filtrar encabezados y totales
            if any(
                term in texto_fila.lower()
                for term in [
                    "saldo anterior",
                    "saldo final",
                    "saldo promedio",
                    "total de movimientos",
                    "total cargos",
                    "total abonos",
                    "rfc",
                    "página",
                    "estado de cuenta",
                ]
            ):
              continue

            # Buscar patrón de fecha y montos en las celdas de la tabla
            match_fecha = re.search(r"(\d{1,2}\s+[A-Za-z]{3}|\d{2}[/-]\d{2})", texto_fila)
            match_monto = re.findall(r"([0-9]{1,3}(?:,[0-9]{3})*\.[0-9]{2})", texto_fila)

            if match_fecha and match_monto:
              fecha = match_fecha.group(1)
              monto = float(match_monto[-1].replace(",", ""))
              # Concepto es el texto restante sin fecha ni montos
              concepto = re.sub(r"\d{1,2}\s+[A-Za-z]{3}|\d{2}[/-]\d{2}", "", texto_fila)
              for m in match_monto:
                concepto = concepto.replace(m, "")
              concepto = " ".join(concepto.split())

              if concepto and monto > 0:
                tipo = clasificar_concepto_bbva(concepto)
                rows.append({
                    "Origen": f"Pág.{i}",
                    "Fecha": fecha,
                    "Concepto": concepto,
                    "Monto": monto,
                    "Tipo": tipo,
                    "Estado": "Normal",
                })

      # Extracción por líneas de texto plano complementaria si no se detectó tabla estructurada
      txt = page.extract_text() or ""
      texto_total += txt
      lines = txt.split("\n")
      for line in lines:
        line_clean = line.strip()
        if not line_clean:
          continue

        line_lower = line_clean.lower()
        if any(
            term in line_lower
            for term in [
                "saldo anterior",
                "saldo final",
                "saldo promedio",
                "total de movimientos",
                "total cargos",
                "total abonos",
                "rfc",
                "página",
                "estado de cuenta",
            ]
        ):
          continue

        match = re.search(
            r"^(\d{1,2}\s+[A-Za-z]{3}|\d{2}[/-]\d{2})\s+(.*?)\s+([0-9]{1,3}(?:,[0-9]{3})*\.[0-9]{2})",
            line_clean,
        )
        if match:
          fecha = match.group(1).strip()
          concepto = match.group(2).strip()
          monto_str = match.group(3).replace(",", "")
          try:
            monto = float(monto_str)
            if monto > 0:
              tipo = clasificar_concepto_bbva(concepto)
              rows.append({
                  "Origen": f"Pág.{i}",
                  "Fecha": fecha,
                  "Concepto": concepto,
                  "Monto": monto,
                  "Tipo": tipo,
                  "Estado": "Normal",
              })
          except ValueError:
            pass

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
    df = df.drop_duplicates(
        subset=["Fecha", "Concepto", "Monto", "Tipo"]
    ).reset_index(drop=True)
    df["Estado"] = "Normal"
    p95 = df["Monto"].quantile(0.95) if len(df) > 5 else 999999
    df.loc[(df["Monto"] > p95) & (df["Tipo"] == "Egreso"), "Estado"] = (
        "⚠️ Inconsistencia"
    )

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
    lines = txt.split("\n")
    for line in lines:
      match = re.search(
          r"^(\d{1,2}\s+[A-Za-z]{3}|\d{2}[/-]\d{2})\s+(.*?)\s+([0-9]{1,3}(?:,[0-9]{3})*\.[0-9]{2})",
          line.strip(),
      )
      if match:
        fecha, concepto, monto_str = match.groups()
        try:
          monto = float(monto_str.replace(",", ""))
          tipo = clasificar_concepto_bbva(concepto)
          rows.append({
              "Origen": f"OCR Pág.{idx}",
              "Fecha": fecha.strip(),
              "Concepto": concepto.strip(),
              "Monto": monto,
              "Tipo": tipo,
              "Estado": "Normal",
          })
        except ValueError:
          pass

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
          f"Empresa: <b>{empresa}</b> &nbsp;|&nbsp; Período:"
          f" <b>{periodo}</b> &nbsp;|&nbsp; Emisión:"
          f" {date.today().strftime('%d/%m/%Y')}",
          s_subtitle,
      )
  )
  story.append(Spacer(1, 8))
  story.append(HRFlowable(width="100%", thickness=2, color=c_accent, spaceAfter=14))

  story.append(Paragraph("1. RESUMEN DE SALUD FINANCIERA", s_h2))
  kpi_data = [[
      Paragraph(
          f"<b>TOTAL INGRESOS</b><br/><font size=12"
          f" color='{c_green}'>${ingresos:,.2f}</font>",
          s_body,
      ),
      Paragraph(
          f"<b>TOTAL EGRESOS</b><br/><font size=12"
          f" color='{c_red}'>${egresos:,.2f}</font>",
          s_body,
      ),
      Paragraph(
          f"<b>UTILIDAD NETA</b><br/><font size=12"
          f" color='{c_blue}'>${utilidad:,.2f}</font>",
          s_body,
      ),
      Paragraph(
          f"<b>MARGEN NETO</b><br/><font size=12"
          f" color='{c_navy}'>{margen:.1f}%</font>",
          s_body,
      ),
  ]]
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
        t_rows, colWidths=[2 * cm, 2.2 * cm, 6.5 * cm, 2.5 * cm, 2 * cm, 2.2 * cm]
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
    story.append(Paragraph("No se registraron transacciones detalladas.", s_body))

  doc.build(story)
  buffer.seek(0)
  return buffer.getvalue()


# ─────────────────────────────────────────────
# MENU LATERAL IZQUIERDO (CONTROLES ACTIVOS)
# ─────────────────────────────────────────────
st.sidebar.markdown("### ⚙️ Parámetros de Auditoría")
empresa_input = st.sidebar.text_input(
    "Nombre de la Empresa", value="Mi PyME S.A. de C.V."
)
periodo_input = st.sidebar.text_input("Período Auditoría", value="Enero 2026")

st.sidebar.markdown("---")
st.sidebar.markdown("### 🎯 Umbrales Anti-Fraude")
umbral_egreso = st.sidebar.number_input(
    "Alerta Egreso Mayor a ($)", value=25000.0, step=5000.0
)
alertar_duplicados = st.sidebar.checkbox(
    "Detectar Montos Duplicados", value=True
)

st.sidebar.markdown("---")
st.sidebar.markdown("### 🔍 Filtro de Movimientos")
filtro_tipo = st.sidebar.selectbox(
    "Mostrar en la vista de tabla:", ["Todos", "Solo Ingresos", "Solo Egresos"]
)

NUMERO_WHATSAPP = "528121106491"
MENSAJE_WHATSAPP = "Hola, utilicé la app de Auditoría Bancaria y me gustaría solicitar una consulta personalizada."
url_whatsapp = (
    f"https://wa.me/{NUMERO_WHATSAPP}?text={MENSAJE_WHATSAPP.replace(' ', '%20')}"
)

st.sidebar.markdown("---")
st.sidebar.subheader("💬 ¿Auditoría Personalizada?")
st.sidebar.markdown(
    f"""
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
""",
    unsafe_allow_html=True,
)


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
# CARGA Y PROCESAMIENTO
# ─────────────────────────────────────────────
uploaded_file = st.file_uploader(
    "📄 Arrastra tu estado de cuenta (PDF, Excel o Imagen) para iniciar el"
    " análisis",
    type=["pdf", "xlsx", "xls", "png", "jpg", "jpeg"],
)

if uploaded_file is not None:
  ext = uploaded_file.name.split(".")[-1].lower()
  df_tx = pd.DataFrame()
  es_escaneado = False
  pdf_digital = b""
  bytes_archivo_original = uploaded_file.read()
  uploaded_file.seek(0)

  with st.spinner("🔍 Analizando datos del documento..."):
    if ext == "pdf":
      df_tx, es_escaneado = extraer_transacciones_pdf(uploaded_file)
      if es_escaneado:
        st.warning("⚠️ Documento escaneado detectado. Procesando vía OCR...")
        uploaded_file.seek(0)
        df_tx, pdf_digital = ocr_pdf_a_digital(bytes_archivo_original)

    elif ext in ["xlsx", "xls"]:
      try:
        df_tx = pd.read_excel(uploaded_file)
        if "Tipo" not in df_tx.columns and "Concepto" in df_tx.columns:
          df_tx["Tipo"] = df_tx["Concepto"].apply(clasificar_concepto_bbva)
      except Exception as e:
        st.error(f"Error al leer el archivo Excel: {e}")

  if not df_tx.empty and "Monto" in df_tx.columns:
    ingresos_calc = (
        float(df_tx[df_tx["Tipo"] == "Ingreso"]["Monto"].sum())
        if "Tipo" in df_tx.columns
        else float(df_tx["Monto"].sum())
    )
    egresos_calc = (
        float(df_tx[df_tx["Tipo"] == "Egreso"]["Monto"].sum())
        if "Tipo" in df_tx.columns
        else 0.0
    )
    util_neta = ingresos_calc - egresos_calc
    margen_calc = (
        ((util_neta / ingresos_calc) * 100) if ingresos_calc > 0 else 0.0
    )
    conteo_calc = len(df_tx)

    hallazgos = []
    if egresos_calc > ingresos_calc:
      hallazgos.append(
          f"<b>Alerta Crítica:</b> Los egresos (${egresos_calc:,.2f}) superan"
          f" a los ingresos (${ingresos_calc:,.2f}). Flujo de caja negativo."
      )
    else:
      hallazgos.append(
          f"<b>Salud Financiera Positiva:</b> Margen neto del {margen_calc:.1f}%"
          f" con una utilidad de ${util_neta:,.2f}."
      )

    egresos_altos = df_tx[
        (df_tx["Tipo"] == "Egreso") & (df_tx["Monto"] >= umbral_egreso)
    ]
    if not egresos_altos.empty:
      hallazgos.append(
          f"<b>Egresos Elevados:</b> Se identificaron"
          f" {len(egresos_altos)} movimientos superiores al umbral de"
          f" ${umbral_egreso:,.2f}."
      )

    dups = pd.DataFrame()
    if alertar_duplicados:
      dups = df_tx[df_tx.duplicated(subset=["Monto", "Tipo"], keep=False)]
      if not dups.empty:
        hallazgos.append(
            f"<b>Detección de Duplicados:</b> Se encontraron {len(dups)}"
            " transacciones con montos idénticos."
        )

    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Total Ingresos", f"${ingresos_calc:,.2f}")
    m2.metric("Total Egresos", f"${egresos_calc:,.2f}")
    m3.metric("Utilidad Neta", f"${util_neta:,.2f}")
    m4.metric("Margen Neto", f"{margen_calc:.1f}%")

    st.markdown("<br/>", unsafe_allow_html=True)

    tab_tx, tab_pdf, tab_audit, tab_export = st.tabs([
        "📋 Transacciones Extraídas",
        "📄 Reporte PDF Ejecutivo",
        "🛡️ Diagnóstico Anti-Fraude",
        "📥 Conversión & Exportar a Excel",
    ])

    df_mostrar = df_tx.copy()
    if filtro_tipo == "Solo Ingresos":
      df_mostrar = df_mostrar[df_mostrar["Tipo"] == "Ingreso"]
    elif filtro_tipo == "Solo Egresos":
      df_mostrar = df_mostrar[df_mostrar["Tipo"] == "Egreso"]

    with tab_tx:
      st.markdown(f"##### 🔍 Movimientos Registrados ({filtro_tipo})")
      st.dataframe(df_mostrar, use_container_width=True, height=380)

    with tab_pdf:
      st.markdown("##### 📄 Generar Informe Oficial")
      st.info(
          f"El reporte incluirá la carátula con la empresa:"
          f" **{empresa_input}** y período: **{periodo_input}**."
      )

      pdf_bytes_report = generar_pdf_reporte(
          empresa=empresa_input,
          periodo=periodo_input,
          ingresos=ingresos_calc,
          egresos=egresos_calc,
          utilidad=util_neta,
          margen=margen_calc,
          df_tx=df_tx,
          hallazgos=hallazgos,
      )

      st.download_button(
          "📥 Descargar Reporte Ejecutivo en PDF",
          data=pdf_bytes_report,
          file_name=(
              f"Reporte_{empresa_input.replace(' ', '_')}_{date.today().strftime('%Y%m%d')}.pdf"
          ),
          mime="application/pdf",
      )

    with tab_audit:
      st.markdown("##### 🛡️ Diagnóstico Anti-Fraude Activo")
      for h in hallazgos:
        if "Crítica" in h or "Elevados" in h:
          st.error(h)
        else:
          st.success(h)

      if not egresos_altos.empty:
        st.markdown(
            f"<h6>Movimientos superiores a ${umbral_egreso:,.2f}:</h6>",
            unsafe_allow_html=True,
        )
        st.dataframe(egresos_altos, use_container_width=True)

      if alertar_duplicados and not dups.empty:
        st.markdown(
            "<h6>Transacciones con montos duplicados:</h6>",
            unsafe_allow_html=True,
        )
        st.dataframe(dups, use_container_width=True)

    with tab_export:
      st.markdown("##### 📊 Conversión de Archivos y Exportación")

      col_ex1, col_ex2 = st.columns(2)

      with col_ex1:
        st.markdown("###### 1. Convertir Estado de Cuenta (PDF) a Excel")
        excel_buf = BytesIO()
        with pd.ExcelWriter(excel_buf, engine="openpyxl") as writer:
          df_tx.to_excel(writer, index=False, sheet_name="Transacciones")
          resumen = pd.DataFrame({
              "Indicador": [
                  "Empresa",
                  "Período",
                  "Ingresos",
                  "Egresos",
                  "Utilidad Neta",
                  "Margen Neto",
                  "Transacciones",
              ],
              "Valor": [
                  empresa_input,
                  periodo_input,
                  ingresos_calc,
                  egresos_calc,
                  util_neta,
                  f"{margen_calc:.1f}%",
                  conteo_calc,
              ],
          })
          resumen.to_excel(writer, index=False, sheet_name="Resumen")
        excel_buf.seek(0)

        st.download_button(
            "📥 Descargar PDF Convertido a Excel (.xlsx)",
            data=excel_buf,
            file_name=f"Estado_Cuenta_{empresa_input.replace(' ', '_')}.xlsx",
            mime=(
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
            ),
            use_container_width=True,
        )

      with col_ex2:
        st.markdown("###### 2. Digitalizar PDF Escaneado / Imagen")
        if pdf_digital:
          st.success("✅ PDF escaneado digitalizado con OCR.")
          st.download_button(
              "📥 Descargar PDF Digitalizado (OCR)",
              data=pdf_digital,
              file_name=(
                  f"AuditSaaS_OCR_{date.today().strftime('%Y%m%d')}.pdf"
              ),
              mime="application/pdf",
              use_container_width=True,
          )
        elif ext == "pdf" and not es_escaneado:
          st.info(
              "ℹ️ Tu PDF es nativo digital (texto seleccionable). No requiere"
              " OCR."
          )
        else:
          st.info(
              "ℹ️ Sube una imagen o PDF escaneado para procesarlo por OCR."
          )

  else:
    st.warning(
        "⚠️ No se identificaron transacciones válidas en el documento cargado."
    )

else:
  st.info(
      "👆 Carga un estado de cuenta en el panel central para iniciar el proceso"
      " de auditoría y análisis."
  )
