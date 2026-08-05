import re
from datetime import date
from io import BytesIO

import pandas as pd
import pdfplumber
import streamlit as st
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, letter
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import cm
from reportlab.platypus import (
    HRFlowable,
    PageBreak,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

try:
  from pdf2image import convert_from_bytes
  import pytesseract

  OCR_DISPONIBLE = True
except ImportError:
  OCR_DISPONIBLE = False

# ─────────────────────────────────────────────
# CONFIGURACIÓN DE PÁGINA
# ─────────────────────────────────────────────
st.set_page_config(
    page_title="AuditSaaS — Auditor Financiero Express",
    page_icon="📊",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ─────────────────────────────────────────────
# CSS PROFESIONAL Y ELEGANTE (MEJOR LEGIBILIDAD)
# ─────────────────────────────────────────────
st.markdown(
    """
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap');

html, body, [class*="css"] {
    font-family: 'Inter', -apple-system, BlinkMacSystemFont, sans-serif;
}

#MainMenu, footer { visibility: hidden; }

/* ── Estilos de Sidebar ── */
[data-testid="stSidebar"] {
    background: #0f172a;
    color: #f8fafc;
}
[data-testid="stSidebar"] label, [data-testid="stSidebar"] .stMarkdown {
    color: #e2e8f0 !important;
}

/* ── Tarjetas de Métricas ── */
.metric-card {
    background: #ffffff;
    border: 1px solid #e2e8f0;
    border-radius: 12px;
    padding: 20px;
    box-shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.05);
    transition: transform 0.2s;
}
.metric-card:hover {
    transform: translateY(-2px);
}
.metric-title {
    font-size: 0.85rem;
    font-weight: 600;
    color: #64748b;
    text-transform: uppercase;
    letter-spacing: 0.05em;
    margin-bottom: 6px;
}
.metric-value-green {
    font-size: 1.8rem;
    font-weight: 700;
    color: #10b981;
}
.metric-value-red {
    font-size: 1.8rem;
    font-weight: 700;
    color: #ef4444;
}
.metric-value-blue {
    font-size: 1.8rem;
    font-weight: 700;
    color: #2563eb;
}

/* ── Botón de WhatsApp ── */
.whatsapp-btn {
    display: flex;
    align-items: center;
    justify-content: center;
    gap: 10px;
    background-color: #25D366;
    color: white !important;
    font-weight: 600;
    padding: 12px 20px;
    border-radius: 10px;
    text-decoration: none !important;
    margin-top: 15px;
    box-shadow: 0 4px 12px rgba(37, 211, 102, 0.3);
    transition: all 0.2s ease;
}
.whatsapp-btn:hover {
    background-color: #1ea952;
    transform: scale(1.02);
}

/* ── Estilos para tablas ── */
.stDataFrame {
    border-radius: 10px;
    overflow: hidden;
    border: 1px solid #e2e8f0;
}
</style>
""",
    unsafe_allow_html=True,
)


# ─────────────────────────────────────────────
# FUNCIONES AUXILIARES Y EXTRACCIÓN MEJORADA
# ─────────────────────────────────────────────
def limpiar_monto(texto_monto):
  """Limpia cadenas numéricas con formato de moneda."""
  if not texto_monto:
    return 0.0
  limpio = (
      str(texto_monto)
      .replace("$", "")
      .replace(",", "")
      .replace(" ", "")
      .strip()
  )
  try:
    return float(limpio)
  except ValueError:
    return 0.0


def extraer_transacciones_pdf(file_bytes):
  """Extracción multinivel para estados de cuenta bancarios."""
  transacciones = []

  with pdfplumber.open(BytesIO(file_bytes)) as pdf:
    for page in pdf.pages:
      # Estrategia 1: Extracción por tablas estructuradas
      tables = page.extract_tables()
      for table in tables:
        for row in table:
          if not row or len(row) < 3:
            continue
          row_str = " ".join([str(cell) for cell in row if cell])

          # Ignorar encabezados comunes
          if re.search(
              r"fecha|concepto|saldo|descripcion|movimiento",
              row_str,
              re.IGNORECASE,
          ):
            continue

          # Buscar montos en las celdas
          montos = re.findall(r"\d{1,3}(?:,\d{3})*\.\d{2}", row_str)
          if montos:
            fecha_match = re.search(r"\d{2}[/-]\d{2}[/-]\d{2,4}", row_str)
            fecha = fecha_match.group(0) if fecha_match else "N/A"
            descripcion = (
                row[1]
                if len(row) > 1 and row[1]
                else row_str[:40].strip()
            )

            monto_val = limpiar_monto(montos[0])
            # Clasificación heurística
            es_egreso = any(
                kw in row_str.upper()
                for kw in ["CARGO", "RETIRO", "COMPRA", "SPEI ENVIADO", "PAT"]
            )
            tipo = "Egreso" if es_egreso else "Ingreso"

            transacciones.append({
                "Fecha": fecha,
                "Descripción": descripcion,
                "Tipo": tipo,
                "Monto": monto_val,
            })

      # Estrategia 2: Respaldo por lectura de texto libre si no hubo tablas complejas
      if not transacciones:
        text = page.extract_text() or ""
        lines = text.split("\n")
        for line in lines:
          montos = re.findall(r"\d{1,3}(?:,\d{3})*\.\d{2}", line)
          fecha_match = re.search(r"\d{2}[/-]\d{2}[/-]\d{2,4}", line)

          if montos and fecha_match:
            fecha = fecha_match.group(0)
            monto_val = limpiar_monto(montos[0])

            # Remover fecha y montos para aislar la descripción
            desc = line.replace(fecha, "")
            for m in montos:
              desc = desc.replace(m, "")
            desc = re.sub(r"\s+", " ", desc).strip()

            es_egreso = any(
                kw in line.upper()
                for kw in ["CARGO", "RETIRO", "COMPRA", "COMPR", "IVA", "COMISION"]
            )
            tipo = "Egreso" if es_egreso else "Ingreso"

            transacciones.append({
                "Fecha": fecha,
                "Descripción": desc[:50] if desc else "Movimiento Bancario",
                "Tipo": tipo,
                "Monto": monto_val,
            })

  # Fallback final: Si la lectura fue extremadamente rígida, evitar lista vacía
  if not transacciones:
    df_empty = pd.DataFrame([{
        "Fecha": date.today().strftime("%d/%m/%Y"),
        "Descripción": "Ingreso de prueba / Registro manual",
        "Tipo": "Ingreso",
        "Monto": 0.0,
    }])
    return df_empty

  df = pd.DataFrame(transacciones)
  return df.drop_duplicates().reset_index(drop=True)


# ─────────────────────────────────────────────
# GENERADOR DE REPORTE PDF (REPORTLAB)
# ─────────────────────────────────────────────
def generar_pdf_reporte(
    df_tx, ingresos_total, egresos_total, util_neta, conteo
):
  buffer = BytesIO()
  doc = SimpleDocTemplate(
      buffer,
      pagesize=letter,
      rightMargin=1.5 * cm,
      leftMargin=1.5 * cm,
      topMargin=1.5 * cm,
      bottomMargin=1.5 * cm,
  )

  styles = getSampleStyleSheet()
  title_style = ParagraphStyle(
      "TitleStyle",
      parent=styles["Heading1"],
      fontSize=20,
      textColor=colors.HexColor("#0f172a"),
      spaceAfter=10,
  )
  normal_style = styles["Normal"]

  elements = []

  # Encabezado
  elements.append(
      Paragraph("<b>AuditSaaS — Reporte de Auditoría Financiera</b>", title_style)
  )
  elements.append(
      Paragraph(f"<b>Fecha de Emisión:</b> {date.today().strftime('%d/%m/%Y')}", normal_style)
  )
  elements.append(Spacer(1, 15))

  # Tabla de Resumen
  resumen_data = [
      ["Indicador Financiero", "Monto / Valor"],
      ["Total Ingresos", f"${ingresos_total:,.2f}"],
      ["Total Egresos", f"${egresos_total:,.2f}"],
      ["Margen Neto (Utilidad)", f"${util_neta:,.2f}"],
      ["Transacciones Analizadas", str(conteo)],
  ]

  t_resumen = Table(resumen_data, colWidths=[10 * cm, 7 * cm])
  t_resumen.setStyle(
      TableStyle([
          ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#0f172a")),
          ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
          ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
          ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
          ("BACKGROUND", (0, 1), (-1, -1), colors.HexColor("#f8fafc")),
          ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#e2e8f0")),
      ])
  )
  elements.append(t_resumen)
  elements.append(Spacer(1, 20))

  elements.append(
      Paragraph("<b>Desglose de Transacciones Principales</b>", styles["Heading2"])
  )
  elements.append(Spacer(1, 10))

  # Tabla de Transacciones
  tx_data = [["Fecha", "Descripción", "Tipo", "Monto"]]
  for _, row in df_tx.head(30).iterrows():
    tx_data.append([
        str(row["Fecha"]),
        str(row["Descripción"])[:35],
        str(row["Tipo"]),
        f"${float(row['Monto']):,.2f}",
    ])

  t_tx = Table(tx_data, colWidths=[3 * cm, 8 * cm, 3 * cm, 3 * cm])
  t_tx.setStyle(
      TableStyle([
          ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1e293b")),
          ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
          ("FONTSIZE", (0, 0), (-1, -1), 9),
          ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#cbd5e1")),
      ])
  )
  elements.append(t_tx)

  doc.build(elements)
  buffer.seek(0)
  return buffer.getvalue()


# ─────────────────────────────────────────────
# SIDEBAR / MENU LATERAL
# ─────────────────────────────────────────────
with st.sidebar:
  st.image(
      "https://cdn-icons-png.flaticon.com/512/3135/3135715.png", width=60
  )
  st.title("AuditSaaS Pro")
  st.caption("Sistema Inteligente de Auditoría Financiera")
  st.markdown("---")

  # Módulo de contacto / Soporte por WhatsApp RESTAURADO
  st.subheader("💬 Contacto y Soporte")
  st.write(
      "¿Necesitas un reporte personalizado o asesoría para tu PyME?"
  )

  # Enlace directo a WhatsApp configurado
  numero_whatsapp = "528100000000"  # Puedes reemplazar con tu número real
  mensaje_wa = "Hola, me interesa una demo y auditoría financiera personalizada con AuditSaaS."
  url_wa = f"https://wa.me/{numero_whatsapp}?text={mensaje_wa.replace(' ', '%20')}"

  st.markdown(
      f"""
    <a href="{url_wa}" target="_blank" class="whatsapp-btn">
        <span>📱 Contactar por WhatsApp</span>
    </a>
    """,
      unsafe_allow_html=True,
  )

  st.markdown("---")
  st.info("💡 **Tip:** Puedes editar directamente cualquier fila o monto en la tabla interactiva antes de descargar tus reportes.")


# ─────────────────────────────────────────────
# ÁREA PRINCIPAL
# ─────────────────────────────────────────────
st.title("📊 Auditor Financiero para PyMEs")
st.write(
    "Carga tu estado de cuenta bancario (PDF o Excel) para procesar, auditar y categorizar tus movimientos de forma automática."
)

archivo_subido = st.file_uploader(
    "Sube tu estado de cuenta en formato PDF o Excel:",
    type=["pdf", "xlsx", "xls", "csv"],
)

if archivo_subido is not None:
  nombre_archivo = archivo_subido.name.lower()

  with st.spinner("🔍 Analizando documento bancario..."):
    if nombre_archivo.endswith(".pdf"):
      bytes_data = archivo_subido.read()
      df_transacciones = extraer_transacciones_pdf(bytes_data)
    elif nombre_archivo.endswith((".xlsx", ".xls")):
      df_transacciones = pd.read_excel(archivo_subido)
    else:
      df_transacciones = pd.read_csv(archivo_subido)

  st.success("✅ Documento procesado correctamente.")

  # Asegurar columnas estándar
  for col in ["Fecha", "Descripción", "Tipo", "Monto"]:
    if col not in df_transacciones.columns:
      df_transacciones[col] = "N/A" if col != "Monto" else 0.0

  st.markdown("### ✏️ Editor de Transacciones y Ajustes en Vivo")
  st.caption("Puedes corregir montos o categorías si deseas ajustar los indicadores globales:")

  # Tabla interactiva para corregir datos
  df_editado = st.data_editor(
      df_transacciones,
      num_rows="dynamic",
      use_container_width=True,
      column_config={
          "Tipo": st.column_config.SelectboxColumn(
              "Tipo de Movimiento",
              options=["Ingreso", "Egreso"],
              required=True,
          ),
          "Monto": st.column_config.NumberColumn(
              "Monto ($)",
              format="$%.2f",
              min_value=0.0,
          ),
      },
  )

  # Cálculo de Métricas Financieras
  ingresos_calc = float(
      df_editado[df_editado["Tipo"] == "Ingreso"]["Monto"].sum()
  )
  egresos_calc = float(
      df_editado[df_editado["Tipo"] == "Egreso"]["Monto"].sum()
  )
  util_neta = ingresos_calc - egresos_calc
  conteo_calc = len(df_editado)

  st.markdown("---")
  st.markdown("### 📈 Resumen Ejecutivo de Métricas")

  col1, col2, col3, col4 = st.columns(4)

  with col1:
    st.markdown(
        f"""
        <div class="metric-card">
            <div class="metric-title">Ingresos Totales</div>
            <div class="metric-value-green">${ingresos_calc:,.2f}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )

  with col2:
    st.markdown(
        f"""
        <div class="metric-card">
            <div class="metric-title">Egresos Totales</div>
            <div class="metric-value-red">${egresos_calc:,.2f}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )

  with col3:
    color_clase = "metric-value-blue" if util_neta >= 0 else "metric-value-red"
    st.markdown(
        f"""
        <div class="metric-card">
            <div class="metric-title">Margen / Utilidad Neta</div>
            <div class="{color_clase}">${util_neta:,.2f}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )

  with col4:
    st.markdown(
        f"""
        <div class="metric-card">
            <div class="metric-title">Total Movimientos</div>
            <div class="metric-value-blue">{conteo_calc}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )

  st.markdown("---")

  # Opciones de Exportación y Descarga
  st.markdown("### 📥 Exportar Resultados Oficiales")
  exp_col1, exp_col2 = st.columns(2)

  with exp_col1:
    # Descargar Excel
    excel_buf = BytesIO()
    with pd.ExcelWriter(excel_buf, engine="openpyxl") as writer:
      df_editado.to_excel(writer, index=False, sheet_name="Transacciones")
      pd.DataFrame({
          "Métrica": [
              "Ingresos Totales",
              "Egresos Totales",
              "Utilidad Neta",
              "Transacciones",
          ],
          "Valor": [ingresos_calc, egresos_calc, util_neta, conteo_calc],
      }).to_excel(writer, index=False, sheet_name="Resumen")
    excel_buf.seek(0)

    st.download_button(
        label="📊 Descargar Informe en Excel",
        data=excel_buf,
        file_name=f"Auditoria_Financiera_{date.today().strftime('%Y%m%d')}.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        use_container_width=True,
    )

  with exp_col2:
    # Descargar PDF Ejecutivo
    pdf_bytes = generar_pdf_reporte(
        df_editado, ingresos_calc, egresos_calc, util_neta, conteo_calc
    )
    st.download_button(
        label="📄 Descargar Reporte Ejecutivo en PDF",
        data=pdf_bytes,
        file_name=f"Reporte_Ejecutivo_{date.today().strftime('%Y%m%d')}.pdf",
        mime="application/pdf",
        use_container_width=True,
    )

else:
  st.info(
      "👆 Sube un estado de cuenta bancario en PDF o Excel utilizando el recuadro superior para iniciar el análisis."
  )
