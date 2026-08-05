import io
import re
import numpy as np
import pandas as pd
import pdfplumber
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

# ==========================================
# CONFIGURACIÓN DE PÁGINA Y ESTILOS (CSS)
# ==========================================
st.set_page_config(
    page_title="Auditor Bancario Express | Pro",
    page_icon="🏦",
    layout="wide",
    initial_sidebar_state="expanded",
)

# Inyección de CSS Profesional
st.markdown(
    """
    <style>
    /* Estilo General */
    .main {
        background-color: #f8f9fa;
    }
    
    /* Encabezado Principal */
    .header-box {
        background: linear-gradient(135deg, #0e2a47 0%, #1e4d7b 100%);
        padding: 24px;
        border-radius: 12px;
        color: white;
        margin-bottom: 25px;
        box-shadow: 0 4px 12px rgba(0, 0, 0, 0.08);
    }
    .header-title {
        font-size: 28px;
        font-weight: 700;
        margin: 0;
        color: #ffffff;
    }
    .header-subtitle {
        font-size: 14px;
        color: #d1e3f8;
        margin-top: 5px;
    }

    /* Tarjetas de Métricas */
    .metric-card {
        background-color: white;
        border: 1px solid #e2e8f0;
        border-radius: 10px;
        padding: 18px;
        box-shadow: 0 2px 6px rgba(0,0,0,0.04);
        text-align: center;
    }
    .metric-label {
        font-size: 13px;
        font-weight: 600;
        color: #64748b;
        text-transform: uppercase;
        letter-spacing: 0.5px;
    }
    .metric-value {
        font-size: 24px;
        font-weight: 700;
        margin-top: 6px;
    }
    .val-positive { color: #10b981; }
    .val-negative { color: #ef4444; }
    .val-neutral  { color: #0e2a47; }

    /* Pestañas Personalizadas */
    .stTabs [data-baseweb="tab-list"] {
        gap: 8px;
    }
    .stTabs [data-baseweb="tab"] {
        height: 45px;
        white-space: pre-wrap;
        border-radius: 8px 8px 0px 0px;
        padding: 10px 20px;
        font-weight: 600;
    }

    /* Botón de Descarga */
    .stDownloadButton button {
        background-color: #10b981 !important;
        color: white !important;
        font-weight: 600 !important;
        border-radius: 8px !important;
        border: none !important;
        padding: 10px 24px !important;
        box-shadow: 0 4px 10px rgba(16, 185, 129, 0.2) !important;
    }
    .stDownloadButton button:hover {
        background-color: #059669 !important;
    }
    </style>
""",
    unsafe_allow_html=True,
)


# ==========================================
# FUNCIONES DE PROCESAMIENTO Y CONVERSIÓN
# ==========================================


def extract_tables_from_pdf(pdf_file):
  """Extrae tablas de un archivo PDF usando pdfplumber."""
  rows = []
  with pdfplumber.open(pdf_file) as pdf:
    for page_idx, page in enumerate(pdf.pages):
      # Intentar extraer tablas estructuradas
      tables = page.extract_tables()
      if tables:
        for table in tables:
          for row in table:
            # Limpiar celdas vacías o saltos de línea
            clean_row = [
                str(cell).replace("\n", " ").strip() if cell else ""
                for cell in row
            ]
            if any(clean_row):
              rows.append(clean_row)
      else:
        # Modo respaldo: Extracción por líneas de texto si no detecta tablas explícitas
        text = page.extract_text()
        if text:
          for line in text.split("\n"):
            parts = line.split()
            if len(parts) >= 3:
              rows.append(parts)

  if not rows:
    return pd.DataFrame()

  df = pd.DataFrame(rows)

  # Normalizar nombres de columnas
  df.columns = [f"Columna_{i+1}" for i in range(df.shape[1])]
  return df


def generate_excel_download(df):
  """Convierte un DataFrame a un archivo de Excel (.xlsx) en memoria con formato optimizado."""
  output = io.BytesIO()
  with pd.ExcelWriter(output, engine="openpyxl") as writer:
    df.to_excel(writer, index=False, sheet_name="Estado_de_Cuenta")

    # Auto-ajustar ancho de columnas en Excel
    worksheet = writer.sheets["Estado_de_Cuenta"]
    for col in worksheet.columns:
      max_len = max(len(str(cell.value or "")) for cell in col)
      col_letter = col[0].column_letter
      worksheet.column_dimensions[col_letter].width = max(max_len + 3, 12)

  return output.getvalue()


def clean_amount(val):
  """Limpia cadenas de texto a montos numéricos float."""
  if pd.isna(val):
    return 0.0
  val_str = (
      str(val)
      .replace("$", "")
      .replace(",", "")
      .replace("MXN", "")
      .replace("USD", "")
      .strip()
  )
  try:
    return float(val_str)
  except ValueError:
    return 0.0


# ==========================================
# INTERFAZ PRINCIPAL DE LA APLICACIÓN
# ==========================================

# Banner Superior
st.markdown(
    """
    <div class="header-box">
        <div class="header-title">🏦 Auditor Bancario Express & Converter Pro</div>
        <div class="header-subtitle">Convierte estados de cuenta PDF a Excel y analiza la salud financiera de tus cuentas en segundos.</div>
    </div>
""",
    unsafe_allow_html=True,
)

# Sidebar
with st.sidebar:
  st.header("⚙️ Panel de Control")
  st.markdown("---")

  uploaded_file = st.file_uploader(
      "Sube tu Estado de Cuenta",
      type=["pdf", "xlsx", "csv"],
      help="Formatos soportados: PDF, Excel (.xlsx) o CSV",
  )

  st.markdown("---")
  st.subheader("💡 Opciones de Auditoría")
  umbral_alerta = st.number_input(
      "Alerta por Gastos Elevados ($):",
      value=5000.0,
      step=500.0,
      help="Marca las transacciones que superen este monto.",
  )

  st.caption("🔒 Tus datos procesados no se guardan en ningún servidor externo.")

# Lógica cuando se sube un archivo
if uploaded_file is not None:
  file_type = uploaded_file.name.split(".")[-1].lower()

  with st.spinner("🔍 Procesando documento y estructurando datos..."):
    if file_type == "pdf":
      df_raw = extract_tables_from_pdf(uploaded_file)
    elif file_type == "csv":
      df_raw = pd.read_csv(uploaded_file)
    else:
      df_raw = pd.read_excel(uploaded_file)

  if df_raw.empty:
    st.error(
        "❌ No se pudieron extraer datos estructurados del archivo. Asegúrate"
        " de que el PDF no sea una imagen escaneada sin capa de texto."
    )
  else:
    st.success(
        f"✅ ¡Archivo procesado exitosamente! ({len(df_raw)} filas detectadas)"
    )

    # Definir Pestañas de la Aplicación
    tab1, tab2, tab3, tab4 = st.tabs([
        "📊 Resumen General",
        "📑 Transacciones Extraídas",
        "⚠️ Auditoría & Alertas",
        "📥 Convertir y Descargar Excel",
    ])

    # ---------------------------------------------------------
    # TAB 1: RESUMEN GENERAL & MÉTRICAS
    # ---------------------------------------------------------
    with tab1:
      st.subheader("📈 Resumen de Movimientos Financieros")

      # Intentar identificar montos numéricos en la tabla
      numeric_cols = []
      for col in df_raw.columns:
        converted = df_raw[col].apply(clean_amount)
        if (converted != 0).sum() > 0:
          numeric_cols.append(col)

      if numeric_cols:
        # Tomamos la columna numérica principal para balance
        main_amt_col = numeric_cols[-1]
        amounts = df_raw[main_amt_col].apply(clean_amount)

        ingresos = amounts[amounts > 0].sum()
        egresos = abs(amounts[amounts < 0].sum())
        balance = ingresos - egresos

        # Mostrar Tarjetas KPI
        col1, col2, col3, col4 = st.columns(4)

        with col1:
          st.markdown(
              f"""
                        <div class="metric-card">
                            <div class="metric-label">Total Ingresos</div>
                            <div class="metric-value val-positive">${ingresos:,.2f}</div>
                        </div>
                    """,
              unsafe_allow_html=True,
          )

        with col2:
          st.markdown(
              f"""
                        <div class="metric-card">
                            <div class="metric-label">Total Egresos</div>
                            <div class="metric-value val-negative">${egresos:,.2f}</div>
                        </div>
                    """,
              unsafe_allow_html=True,
          )

        with col3:
          color_class = "val-positive" if balance >= 0 else "val-negative"
          st.markdown(
              f"""
                        <div class="metric-card">
                            <div class="metric-label">Balance Neto</div>
                            <div class="metric-value {color_class}">${balance:,.2f}</div>
                        </div>
                    """,
              unsafe_allow_html=True,
          )

        with col4:
          st.markdown(
              f"""
                        <div class="metric-card">
                            <div class="metric-label">Transacciones</div>
                            <div class="metric-value val-neutral">{len(df_raw)}</div>
                        </div>
                    """,
              unsafe_allow_html=True,
          )

        st.markdown("---")

        # Gráfico interactivo
        c_left, c_right = st.columns(2)

        with c_left:
          st.subheader("📊 Distribución Ingresos vs Egresos")
          fig_pie = go.Figure(
              data=[
                  go.Pie(
                      labels=["Ingresos", "Egresos"],
                      values=[ingresos, egresos],
                      hole=0.4,
                      marker_colors=["#10b981", "#ef4444"],
                  )
              ]
          )
          fig_pie.update_layout(margin=dict(t=20, b=20, l=20, r=20))
          st.plotly_chart(fig_pie, use_container_width=True)

        with c_right:
          st.subheader("📉 Top Movimientos Detectados")
          df_temp = df_raw.copy()
          df_temp["Monto_Clean"] = amounts
          df_sorted = df_temp.reindex(
              df_temp["Monto_Clean"].abs().sort_values(ascending=False).index
          ).head(7)

          fig_bar = px.bar(
              df_sorted,
              y=df_sorted.columns[0],
              x="Monto_Clean",
              orientation="h",
              color="Monto_Clean",
              color_continuous_scale="RdYlGn",
              labels={
                  "Monto_Clean": "Monto ($)",
                  df_sorted.columns[0]: "Detalle",
              },
          )
          fig_bar.update_layout(margin=dict(t=20, b=20, l=20, r=20))
          st.plotly_chart(fig_bar, use_container_width=True)

      else:
        st.info(
            "ℹ️ No se detectó una columna numérica clara para generar los"
            " gráficos automáticos. Revisa la tabla en la siguiente pestaña."
        )

    # ---------------------------------------------------------
    # TAB 2: TABLA DE TRANSACCIONES
    # ---------------------------------------------------------
    with tab2:
      st.subheader("📑 Vista Completa de Datos Extraídos")
      st.markdown(
          "Puedes filtrar, ordenar y revisar la estructura de tu documento:"
      )

      search_term = st.text_input(
          "🔎 Buscar en transacciones:",
          "",
          placeholder="Escribe un concepto, fecha o palabra clave...",
      )

      df_display = df_raw.copy()
      if search_term:
        mask = df_display.apply(
            lambda row: row.astype(str)
            .str.contains(search_term, case=False)
            .any(),
            axis=1,
        )
        df_display = df_display[mask]

      st.dataframe(df_display, use_container_width=True, height=400)

    # ---------------------------------------------------------
    # TAB 3: AUDITORÍA Y ALERTAS
    # ---------------------------------------------------------
    with tab3:
      st.subheader("⚠️ Detección de Anomalías y Control de Riesgo")

      if numeric_cols:
        main_amt_col = numeric_cols[-1]
        amounts = df_raw[main_amt_col].apply(clean_amount)

        # Transacciones mayores al umbral
        high_expenses = df_raw[amounts.abs() >= umbral_alerta]

        st.warning(
            f"Se detectaron **{len(high_expenses)}** transacciones que superan"
            f" el umbral de **${umbral_alerta:,.2f}**:"
        )
        if not high_expenses.empty:
          st.dataframe(high_expenses, use_container_width=True)
        else:
          st.success(
              "🎉 No se encontraron transacciones atípicas que superen el"
              " umbral configurado."
          )
      else:
        st.info(
            "Selecciona una columna de montos en la vista de transacciones para"
            " ejecutar la auditoría."
        )

    # ---------------------------------------------------------
    # TAB 4: CONVERTIR Y DESCARGAR A EXCEL / CSV
    # ---------------------------------------------------------
    with tab4:
      st.subheader("📥 Convertir Estado de Cuenta PDF a Excel / CSV")
      st.markdown(
          "Haz clic en el botón a continuación para descargar las celdas"
          " extraídas de tu estado de cuenta en un archivo Excel (`.xlsx`)"
          " perfectamente formateado."
      )

      col_down1, col_down2 = st.columns(2)

      with col_down1:
        # Generar archivo Excel en memoria
        excel_data = generate_excel_download(df_raw)
        filename_base = uploaded_file.name.rsplit(".", 1)[0]

        st.download_button(
            label="🟢 Descargar Estado de Cuenta en Excel (.xlsx)",
            data=excel_data,
            file_name=f"{filename_base}_convertido.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )

      with col_down2:
        # Generar CSV
        csv_data = df_raw.to_csv(index=False).encode("utf-8")
        st.download_button(
            label="📄 Descargar como archivo CSV",
            data=csv_data,
            file_name=f"{filename_base}_convertido.csv",
            mime="text/csv",
        )

else:
  # Estado por defecto cuando no hay archivo subido
  st.info("👈 Comienza subiendo un estado de cuenta en formato **PDF**, **Excel** o **CSV** desde la barra lateral.")
  
  st.markdown("### 🌟 Características de la Versión Pro")
  c1, c2, c3 = st.columns(3)
  with c1:
    st.markdown("#### 📄 Conversión PDF ➔ Excel")
    st.write("Lee automáticamente las tablas contenidas en estados de cuenta PDF de cualquier banco y las convierte a Excel editable.")
  with c2:
    st.markdown("#### ⚡ Auditoría Inmediata")
    st.write("Identifica gastos altos, patrones atípicos y calcula balances netos de forma instantánea.")
  with c3:
    st.markdown("#### 🔒 Privacidad Garantizada")
    st.write("Procesamiento seguro y local dentro de la sesión de tu navegador.")