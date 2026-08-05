import re
from datetime import date
from io import BytesIO

import numpy as np
import pandas as pd
import pdfplumber
import streamlit as st
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, letter
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import cm
from reportlab.platypus import HRFlowable, PageBreak, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

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
    page_title="AuditSaaS — Auditor Financiero Express",
    page_icon="📊",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ─────────────────────────────────────────────
# ESTILOS CSS PERSONALIZADOS (DISEÑO PREMIUM)
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
    background: linear-gradient(160deg, #1e293b 0%, #0f172a 100%);
}
</style>
""",
    unsafe_allow_html=True,
)
[data-testid="stSidebar"] stMarkdown, [data-testid="stSidebar"] label, [data-testid="stSidebar"] .stText {
    color: #f8fafc !important;
}

/* Metric Cards */
.metric-card {
    background: #ffffff;
    border-radius: 12px;
    padding: 20px;
    box-shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.05), 0 2px 4px -1px rgba(0, 0, 0, 0.03);
    border: 1px solid #e2e8f0;
    text-align: center;
}
.metric-title { font-size: 0.85rem; font-weight: 600; text-transform: uppercase; letter-spacing: 0.05em; color: #64748b; margin-bottom: 6px; }
.metric-val-ingreso { font-size: 1.8rem; font-weight: 700; color: #10b981; }
.metric-val-egreso { font-size: 1.8rem; font-weight: 700; color: #ef4444; }
.metric-val-neto { font-size: 1.8rem; font-weight: 700; color: #3b82f6; }
.metric-val-count { font-size: 1.8rem; font-weight: 700; color: #8b5cf6; }

/* WhatsApp Custom Button */
.wa-btn {
    display: inline-flex;
    align-items: center;
    justify-content: center;
    width: 100%;
    background-color: #25D366;
    color: white !important;
    font-weight: 600;
    padding: 12px 16px;
    border-radius: 8px;
    text-decoration: none;
    margin-top: 15px;
    box-shadow: 0 2px 5px rgba(0,0,0,0.2);
    transition: all 0.2s ease;
}
.wa-btn:hover { background-color: #1da851; color: white !important; }
</style>
""",
    unsafe_allow_allowed=True if hasattr(st, "style") else True,
)


# ─────────────────────────────────────────────
# MOTOR DE EXTRACCIÓN AVANZADA DE MOVIMIENTOS
# ─────────────────────────────────────────────
def extraer_movimientos_pdf(file_bytes):
    """Extrae detalladamente cada movimiento con su Fecha, Concepto, Monto y Tipo (Ingreso/Egreso).

    Ignora líneas de saldos generales, totales de periodo y encabezados.
    """
    movimientos = []

    # Expresiones regulares para fechas comunes en estados de cuenta (01/JAN, 15/08/2023, 01-12-2024, etc.)
    regex_fecha = r"\b(\d{1,2}[\/\-](?:\d{1,2}|[A-Za-z]{3})(?:[\/\-]\d{2,4})?)\b"
    # Expresión para montos monetarios ($1,234.56 o 1,234.56)
    regex_monto = r"[\$]?\s*([0-9]{1,3}(?:,[0-9]{3})*\.[0-9]{2})"

    # Palabras clave a EXCLUIR (saldos, resumidos del periodo, totales generales)
    palabras_excluir = [
        "SALDO ANTERIOR",
        "SALDO FINAL",
        "SALDO PROMEDIO",
        "TOTAL DE DEPOSITOS",
        "TOTAL DE RETIROS",
        "MONTO TOTAL DEL PERIODO",
        "SALDO INICIAL",
        "TOTAL CARGOS",
        "TOTAL ABONOS",
        "RESUMEN DE CUENTA",
        "MONTO TOTAL",
    ]

    with pdfplumber.open(BytesIO(file_bytes)) as pdf:
        for num_pagina, pagina in enumerate(pdf.pages):
            texto = pagina.extract_text()
            if not texto:
                continue

            lineas = texto.split("\n")
            for linea in lineas:
                linea_upper = linea.upper()

                # 1. Ignorar si la línea contiene frases de saldos o totales del periodo
                if any(p in linea_upper for p in palabras_excluir):
                    continue

                # 2. Buscar si la línea tiene una Fecha
                match_fecha = re.search(regex_fecha, linea)
                if not match_fecha:
                    continue

                fecha_encontrada = match_fecha.group(1)

                # 3. Buscar todos los montos en la línea
                montos = re.findall(regex_monto, linea)
                if not montos:
                    continue

                # Convertir montos a flotantes
                valores_monto = []
                for m in montos:
                    try:
                        val = float(m.replace(",", ""))
                        if val > 0:
                            valores_monto.append(val)
                    except ValueError:
                        pass

                if not valores_monto:
                    continue

                # Usualmente en una línea de transacción el monto principal es el primero o el único
                # (si hay dos, el segundo suele ser el saldo posterior, nos quedamos con el primero)
                monto_tx = valores_monto[0]

                # 4. Determinar si es Ingreso o Egreso segun palabras clave en la descripción
                es_ingreso = False
                palabras_ingreso = [
                    "ABONO",
                    "DEPOSITO",
                    "TRANSFERENCIA RECIBIDA",
                    "SPEI RECIBIDO",
                    "DEPOSIT",
                    "NOMA",
                    "INTERES A FAVOR",
                    "DEVOLUCION",
                ]
                palabras_egreso = [
                    "RETIRO",
                    "CARGO",
                    "PAGO",
                    "COMPRA",
                    "COMISION",
                    "IVA",
                    "CHEQUE",
                    "SPEI ENVIADO",
                    "DISPERSION",
                ]

                if any(p in linea_upper for p in palabras_ingreso):
                    es_ingreso = True
                elif any(p in linea_upper for p in palabras_egreso):
                    es_ingreso = False
                else:
                    # Si la línea tiene signo '-' o palabra DEBIT/CREDIT
                    if "-" in linea or "CARGO" in linea_upper:
                        es_ingreso = False
                    else:
                        # Por defecto si no coincide con egreso explicito
                        es_ingreso = True

                # Limpieza de concepto / descripción
                concepto = linea
                # Remover la fecha y montos del texto para dejar un concepto limpio
                concepto = re.sub(regex_fecha, "", concepto)
                for m in montos:
                    concepto = concepto.replace(m, "")
                concepto = re.sub(r"[\$\,\-]", "", concepto).strip()
                if not concepto:
                    concepto = "Movimiento Bancario"

                # Guardar el registro completo
                movimientos.append(
                    {
                        "Fecha": fecha_encontrada,
                        "Concepto": concepto[:60],  # Limitar largo de texto
                        "Monto ($)": monto_tx,
                        "Tipo": "Ingreso" if es_ingreso else "Egreso",
                        "Categoría": "Operativo",
                    }
                )

    # Convertir a DataFrame
    if movimientos:
        df = pd.DataFrame(movimientos)
    else:
        # Fallback de estructura si no hay datos
        df = pd.DataFrame(
            columns=["Fecha", "Concepto", "Monto ($)", "Tipo", "Categoría"]
        )

    return df


# ─────────────────────────────────────────────
# GENERADOR DE REPORTE PDF EJECUTIVO
# ─────────────────────────────────────────────
def generar_pdf_reporte(df_tx, ingresos, egresos, utilidad):
    buffer = BytesIO()
    doc = SimpleDocTemplate(
        buffer, pagesize=letter, rightMargin=36, leftMargin=36, topMargin=36, bottomMargin=36
    )
    styles = getSampleStyleSheet()

    # Estilos
    title_style = ParagraphStyle(
        "TitleStyle", parent=styles["Heading1"], fontSize=20, leading=24, textColor=colors.HexColor("#1e293b")
    )
    sub_style = ParagraphStyle(
        "SubStyle", parent=styles["Normal"], fontSize=10, textColor=colors.HexColor("#64748b")
    )
    table_header = ParagraphStyle(
        "TH", fontName="Helvetica-Bold", fontSize=9, textColor=colors.white, alignment=1
    )
    table_cell = ParagraphStyle("TC", fontName="Helvetica", fontSize=8, alignment=0)

    elements = []

    # Encabezado
    elements.append(Paragraph("<b>AuditSaaS — Reporte Financiero</b>", title_style))
    elements.append(
        Paragraph(
            f"Fecha de emisión: {date.today().strftime('%d/%m/%Y')} | Auditoría de Movimientos",
            sub_style,
        )
    )
    elements.append(Spacer(1, 15))
    elements.append(
        HRFlowable(width="100%", thickness=1, color=colors.HexColor("#cbd5e1"))
    )
    elements.append(Spacer(1, 15))

    # Resumen Ejecutivo (Tabla de métricas)
    resumen_data = [
        [
            Paragraph("<b>Total Ingresos</b>", table_cell),
            Paragraph("<b>Total Egresos</b>", table_cell),
            Paragraph("<b>Margen Neto</b>", table_cell),
        ],
        [
            f"${ingresos:,.2f}",
            f"${egresos:,.2f}",
            f"${utilidad:,.2f}",
        ],
    ]
    t_resumen = Table(resumen_data, colWidths=[6 * cm, 6 * cm, 6 * cm])
    t_resumen.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#f1f5f9")),
                ("ALIGN", (0, 0), (-1, -1), "CENTER"),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.HexColor("#334155")),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
                ("TOPPADDING", (0, 0), (-1, -1), 8),
                ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#e2e8f0")),
            ]
        )
    )
    elements.append(t_resumen)
    elements.append(Spacer(1, 20))

    # Tabla de Movimientos Detallados
    elements.append(Paragraph("<b>Detalle de Movimientos Auditados</b>", title_style))
    elements.append(Spacer(1, 10))

    headers = [
        Paragraph("Fecha", table_header),
        Paragraph("Concepto", table_header),
        Paragraph("Monto ($)", table_header),
        Paragraph("Tipo", table_header),
    ]
    rows = [headers]

    for _, row in df_tx.iterrows():
        rows.append(
            [
                Paragraph(str(row["Fecha"]), table_cell),
                Paragraph(str(row["Concepto"]), table_cell),
                Paragraph(f"${float(row['Monto ($)']):,.2f}", table_cell),
                Paragraph(str(row["Tipo"]), table_cell),
            ]
        )

    t_movs = Table(rows, colWidths=[3 * cm, 9 * cm, 3.5 * cm, 3 * cm])
    t_movs.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1e293b")),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                ("ALIGN", (0, 0), (-1, -1), "LEFT"),
                ("ALIGN", (2, 1), (2, -1), "RIGHT"),
                ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#cbd5e1")),
                ("TOPPADDING", (0, 0), (-1, -1), 5),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
            ]
        )
    )
    elements.append(t_movs)

    doc.build(elements)
    buffer.seek(0)
    return buffer.getvalue()


# ─────────────────────────────────────────────
# BARRA LATERAL (SIDEBAR)
# ─────────────────────────────────────────────
with st.sidebar:
    st.image(
        "https://cdn-icons-png.flaticon.com/512/3135/3135715.png", width=60
    )
    st.title("AuditSaaS v2.5")
    st.markdown("**Plataforma Profesional de Auditoría Bancaria**")
    st.markdown("---")

    st.subheader("📁 Cargar Estado de Cuenta")
    uploaded_file = st.file_uploader(
        "Sube un PDF bancario (BBVA, Banorte, Santander, Banamex, etc.)",
        type=["pdf"],
    )

    st.markdown("---")
    st.subheader("💬 Contacto y Soporte Directo")
    st.markdown(
        "¿Necesitas adaptar esta herramienta a tu empresa o agregar funciones personalizadas?"
    )

    # Botón directo de WhatsApp
    num_wa = "528100000000"  # Reemplazar con tu número real de WhatsApp
    msj_wa = "Hola, me interesa comercializar/personalizar AuditSaaS para mis clientes."
    url_wa = f"https://wa.me/{num_wa}?text={msj_wa.replace(' ', '%20')}"

    st.markdown(
        f'<a href="{url_wa}" target="_blank" class="wa-btn">💬 Contactar por WhatsApp</a>',
        unsafe_allow_html=True,
    )


# ─────────────────────────────────────────────
# PANEL PRINCIPAL
# ─────────────────────────────────────────────
st.title("📊 Panel Ejecutivos de Auditoría Financiera")
st.markdown(
    "Analiza e identifica detalladamente **cada fecha, concepto, monto e ingreso/egreso** individual de tus estados de cuenta en segundos."
)
st.markdown("---")

if uploaded_file is not None:
    bytes_data = uploaded_file.getvalue()

    with st.spinner("Procesando documento y extrayendo movimientos..."):
        df_extraido = extraer_movimientos_pdf(bytes_data)

    if df_extraido.empty:
        st.warning(
            "⚠️ No se detectaron movimientos individuales legibles en el PDF. Si es una imagen o PDF escaneado, requiere OCR."
        )
    else:
        # Permite edición interactiva en vivo por el usuario
        st.subheader("✏️ Editor Interactivo de Transacciones")
        st.caption(
            "Puedes editar la Fecha, Concepto, Monto o cambiar entre 'Ingreso' y 'Egreso' en la tabla interactiva:"
        )

        df_editado = st.data_editor(
            df_extraido,
            num_rows="dynamic",
            use_container_width=True,
            column_config={
                "Fecha": st.column_config.TextColumn(
                    "Fecha", help="Fecha de la transacción"
                ),
                "Concepto": st.column_config.TextColumn(
                    "Concepto / Descripción", width="large"
                ),
                "Monto ($)": st.column_config.NumberColumn(
                    "Monto ($)", format="$%.2f"
                ),
                "Tipo": st.column_config.SelectboxColumn(
                    "Tipo de Movimiento",
                    options=["Ingreso", "Egreso"],
                    required=True,
                ),
                "Categoría": st.column_config.SelectboxColumn(
                    "Categoría",
                    options=[
                        "Operativo",
                        "Nómina",
                        "Impuestos",
                        "Ventas",
                        "Servicios",
                    ],
                ),
            },
        )

        # Cálculo dinámico de métricas basado en la tabla editable
        ingresos_total = df_editado[df_editado["Tipo"] == "Ingreso"][
            "Monto ($)"
        ].sum()
        egresos_total = df_editado[df_editado["Tipo"] == "Egreso"][
            "Monto ($)"
        ].sum()
        margen_neto = ingresos_total - egresos_total
        conteo_total = len(df_editado)

        # Muestrario de Métricas con CSS
        st.markdown("<br>", unsafe_allow_html=True)
        col1, col2, col3, col4 = st.columns(4)

        with col1:
            st.markdown(
                f"""
            <div class="metric-card">
                <div class="metric-title">🟢 Total Ingresos</div>
                <div class="metric-val-ingreso">${ingresos_total:,.2f}</div>
            </div>
            """,
                unsafe_allow_html=True,
            )

        with col2:
            st.markdown(
                f"""
            <div class="metric-card">
                <div class="metric-title">🔴 Total Egresos</div>
                <div class="metric-val-egreso">${egresos_total:,.2f}</div>
            </div>
            """,
                unsafe_allow_html=True,
            )

        with col3:
            st.markdown(
                f"""
            <div class="metric-card">
                <div class="metric-title">🔵 Margen Neto</div>
                <div class="metric-val-neto">${margen_neto:,.2f}</div>
            </div>
            """,
                unsafe_allow_html=True,
            )

        with col4:
            st.markdown(
                f"""
            <div class="metric-card">
                <div class="metric-title">🟣 Movimientos</div>
                <div class="metric-val-count">{conteo_total}</div>
            </div>
            """,
                unsafe_allow_html=True,
            )

        st.markdown("<br><hr>", unsafe_allow_html=True)

        # Módulo de Exportación y Descargas
        st.subheader("📥 Exportar Reportes Auditoría")
        col_exp1, col_exp2 = st.columns(2)

        with col_exp1:
            # Excel
            buffer_excel = BytesIO()
            with pd.ExcelWriter(buffer_excel, engine="openpyxl") as writer:
                df_editado.to_excel(
                    writer, index=False, sheet_name="Transacciones"
                )
                resumen_df = pd.DataFrame(
                    {
                        "Métrica": [
                            "Ingresos Totales",
                            "Egresos Totales",
                            "Margen Neto",
                            "Total Transacciones",
                        ],
                        "Monto ($)": [
                            ingresos_total,
                            egresos_total,
                            margen_neto,
                            conteo_total,
                        ],
                    }
                )
                resumen_df.to_excel(writer, index=False, sheet_name="Resumen")
            buffer_excel.seek(0)

            st.download_button(
                label="📊 Descargar Transacciones en Excel",
                data=buffer_excel,
                file_name=f"Auditoria_Transacciones_{date.today().strftime('%Y%m%d')}.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                use_container_width=True,
            )

        with col_exp2:
            # PDF
            pdf_bytes = generar_pdf_reporte(
                df_editado, ingresos_total, egresos_total, margen_neto
            )
            st.download_button(
                label="📄 Descargar Reporte PDF Ejecutivo",
                data=pdf_bytes,
                file_name=f"Reporte_Ejecutivo_{date.today().strftime('%Y%m%d')}.pdf",
                mime="application/pdf",
                use_container_width=True,
            )

else:
    st.info(
        "👈 Comienza cargando un Estado de Cuenta en formato PDF desde el menú lateral para iniciar la auditoría."
    )
