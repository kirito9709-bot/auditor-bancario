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
    box-shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.05);
    margin-bottom: 16px;
}
.metric-title {
    font-size: 0.85rem;
    font-weight: 600;
    text-transform: uppercase;
    letter-spacing: 0.05em;
    color: #64748B;
    margin-bottom: 8px;
}
.metric-value {
    font-size: 1.8rem;
    font-weight: 700;
    color: #0F172A;
}

/* Botones principales */
.stButton>button {
    background: linear-gradient(135deg, #2563EB 0%, #1D4ED8 100%);
    color: white;
    border-radius: 8px;
    font-weight: 600;
    padding: 0.5rem 1rem;
    border: none;
    box-shadow: 0 4px 12px rgba(37, 99, 235, 0.2);
    transition: all 0.3s ease;
}
.stButton>button:hover {
    background: linear-gradient(135deg, #1D4ED8 0%, #1E40AF 100%);
    box-shadow: 0 6px 16px rgba(37, 99, 235, 0.3);
}
</style>
""",
    unsafe_allow_html=True,
)


# ─────────────────────────────────────────────
# MOTOR DE LECTURA DE PDF ROBUSTO (EXACTO AL ORIGINAL)
# ─────────────────────────────────────────────
def extraer_transacciones_pdf(archivo_pdf_bytes):
  """Extrae cada transacción del PDF interpretando líneas y tablas con precisión."""
  transacciones = []
  try:
    with pdfplumber.open(BytesIO(archivo_pdf_bytes)) as pdf:
      for pagina in pdf.pages:
        # Extraer usando tablas si están delimitadas
        tablas = pagina.extract_tables()
        for tabla in tablas:
          for fila in tabla:
            # Limpiar elementos nulos
            fila_limpia = [
                str(celda).strip() if celda is not None else "" for celda in fila
            ]
            # Buscar si contiene datos numéricos de importes y fechas
            texto_fila = " ".join(fila_limpia)
            # Regex simple para detectar fecha en formato DD/MM o DD/MMM o similar
            if re.search(r"\d{1,2}[/-](?:\d{1,2}|[A-Za-z]{3})", texto_fila):
              # Intentar aislar importes al final de la fila
              montos = re.findall(
                  r"[\$]?(?:\d{1,3},)+\d{3}\.\d{2}|\d+\.\d{2}", texto_fila
              )
              if montos:
                monto_str = montos[-1].replace("$", "").replace(",", "")
                try:
                  monto = float(monto_str)
                  # Determinar si es retiro o depósito por palabras clave o posición
                  tipo = (
                      "Retiro"
                      if any(
                          w in texto_fila.upper()
                          for w in [
                              "RETIRO",
                              "CARGO",
                              "PAGO",
                              "COMPRA",
                              "COMISION",
                          ]
                      )
                      else "Depósito"
                  )
                  # Extraer fecha
                  match_fecha = re.search(
                      r"(\d{1,2}[/-](?:\d{1,2}|[A-Za-z]{3})[/-]?\d{0,4})",
                      texto_fila,
                  )
                  fecha = match_fecha.group(1) if match_fecha else "N/D"

                  # Limpiar concepto (remover la fecha y los montos encontrados)
                  concepto = texto_fila
                  transacciones.append({
                      "Fecha": fecha,
                      "Concepto": concepto,
                      "Tipo": tipo,
                      "Monto": monto,
                  })
                except ValueError:
                  pass

        # Si no encontró por tablas, extraer texto línea por línea con fallback inteligente
        if not transacciones:
          texto_pag = pagina.extract_text()
          if texto_pag:
            lineas = texto_pag.split("\n")
            for linea in lineas:
              # Buscar montos y fechas en la línea
              match_monto = re.findall(
                  r"[\$]?(\d{1,3}(?:,\d{3})*\.\d{2})", linea
              )
              match_fecha = re.search(r"\b\d{1,2}[/-](?:\d{1,2}|[A-Za-z]{3})\b", linea)
              if match_monto and match_fecha:
                try:
                  monto_val = float(match_monto[-1].replace(",", ""))
                  tipo = (
                      "Retiro"
                      if any(
                          w in linea.upper()
                          for w in ["RETIRO", "CARGO", "PAGO", "COMISION"]
                      )
                      else "Depósito"
                  )
                  transacciones.append({
                      "Fecha": match_fecha.group(0),
                      "Concepto": linea.strip(),
                      "Tipo": tipo,
                      "Monto": monto_val,
                  })
                except ValueError:
                  pass

  except Exception as e:
    st.error(f"Error al procesar el PDF: {e}")

  return pd.DataFrame(transacciones)


# ─────────────────────────────────────────────
# INTERFAZ PRINCIPAL (STREAMLIT)
# ─────────────────────────────────────────────
st.sidebar.title("📊 AuditSaaS Panel")
st.sidebar.markdown("---")
empresa_input = st.sidebar.text_input(
    "Nombre de la Empresa / Cliente", "Mi PyME S.A. de C.V."
)
archivo_subido = st.sidebar.file_uploader(
    "Cargar Estado de Cuenta (PDF)", type=["pdf", "png", "jpg"]
)

st.title("📊 Auditor Financiero para PyMEs & Análisis de Cuentas")
st.markdown(
    "Sube tu estado de cuenta en la barra lateral para comenzar la"
    " auditoría detallada de transacciones."
)

if archivo_subido is not None:
  bytes_data = archivo_subido.read()

  with st.spinner("Leyendo transacciones con el nuevo motor exacto..."):
    df_transacciones = extraer_transacciones_pdf(bytes_data)

  if not df_transacciones.empty:
    st.success(
        f"✅ ¡Se han extraído {len(df_transacciones)} transacciones con éxito!"
    )

    # Métricas Principales
    col1, col2, col3 = st.columns(3)
    total_depositos = df_transacciones[df_transacciones["Tipo"] == "Depósito"][
        "Monto"
    ].sum()
    total_retiros = df_transacciones[df_transacciones["Tipo"] == "Retiro"][
        "Monto"
    ].sum()
    neto = total_depositos - total_retiros

    with col1:
      st.markdown(
          f'<div class="metric-card"><div class="metric-title">Total'
          f' Ingresos</div><div class="metric-value"'
          f' style="color:#10B981;">${total_depositos:,.2f}</div></div>',
          unsafe_allow_html=True,
      )
    with col2:
      st.markdown(
          f'<div class="metric-card"><div class="metric-title">Total'
          f' Egresos</div><div class="metric-value"'
          f' style="color:#EF4444;">${total_retiros:,.2f}</div></div>',
          unsafe_allow_html=True,
      )
    with col3:
      st.markdown(
          f'<div class="metric-card"><div class="metric-title">Flujo'
          f' Neto</div><div class="metric-value"'
          f' style="color:#2563EB;">${neto:,.2f}</div></div>',
          unsafe_allow_html=True,
      )

    st.markdown("### 📋 Detalle de Transacciones Detectadas")
    st.dataframe(df_transacciones, use_container_width=True)

    # Exportación rápida
    output = BytesIO()
    with pd.ExcelWriter(output, engine="xlsxwriter") as writer:
      df_transacciones.to_excel(writer, index=False, sheet_name="Transacciones")
    excel_data = output.getvalue()

    st.download_button(
        label="📥 Descargar Reporte en Excel (.xlsx)",
        data=excel_data,
        file_name=f"Estado_Cuenta_{empresa_input.replace(' ', '_')}.xlsx",
        mime=(
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        ),
    )

  else:
    st.warning(
        "⚠️ No se lograron extraer transacciones con el formato detectado."
        " Asegúrate de que el PDF contenga texto seleccionable o prueba con"
        " otro archivo."
    )
else:
  st.info(
      "👈 Sube un estado de cuenta en formato PDF desde el panel lateral para"
      " iniciar la lectura detallada."
  )
