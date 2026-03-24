import re
from io import BytesIO
from datetime import datetime, timedelta

import pandas as pd
import pdfplumber
import streamlit as st
from openpyxl import load_workbook

st.set_page_config(page_title="Cálculo PMMG", layout="wide")


# =========================================================
# EXTRAÇÃO DO PDF
# =========================================================

def extrair_texto_pdf(pdf_file) -> str:
    texto = ""
    with pdfplumber.open(pdf_file) as pdf:
        for page in pdf.pages:
            page_text = page.extract_text() or ""
            texto += page_text + "\n"
    return texto


def buscar_primeiro(texto: str, padroes: list[str]) -> str | None:
    for padrao in padroes:
        m = re.search(padrao, texto, re.IGNORECASE | re.DOTALL)
        if m:
            return m.group(1).strip()
    return None


def extrair_data_referencia(texto: str) -> datetime | None:
    valor = buscar_primeiro(
        texto,
        [
            r"Data de referência[:\s]+(\d{2}/\d{2}/\d{4})",
            r"DATA DE REFER[ÊE]NCIA[:\s]+(\d{2}/\d{2}/\d{4})",
        ],
    )
    if valor:
        return datetime.strptime(valor, "%d/%m/%Y")
    return None


def extrair_anos_dias_label(texto: str, label_regex: str) -> tuple[int, int]:
    m = re.search(
        rf"{label_regex}.*?(\d+)\s+anos.*?(\d+)\s+dias",
        texto,
        re.IGNORECASE | re.DOTALL,
    )
    if m:
        return int(m.group(1)), int(m.group(2))
    return 0, 0


def anos_dias_para_dias(anos: int, dias: int) -> int:
    return anos * 365 + dias


# =========================================================
# CÁLCULO
# =========================================================

def calcular_data_marco(data_ref: datetime, total_dias: int, marco_dias: int) -> datetime:
    excesso = total_dias - marco_dias
    return data_ref - timedelta(days=excesso)


def calcular_data_quinquenio(data_ref: datetime, total_dias: int, numero: int) -> datetime:
    marco = numero * 1825
    return calcular_data_marco(data_ref, total_dias, marco)


def calcular_data_trintenario(data_ref: datetime, total_dias: int) -> datetime:
    return calcular_data_marco(data_ref, total_dias, 10950)


def diff_ymd(data_inicial: datetime, data_final: datetime) -> tuple[int, int, int]:
    dias = (data_final.date() - data_inicial.date()).days
    anos = dias // 365
    resto = dias % 365
    meses = resto // 30
    dias_restantes = resto % 30
    return anos, meses, dias_restantes


# =========================================================
# EXPORTAÇÃO EXCEL
# =========================================================

def preencher_modelo_excel(
    caminho_modelo: str,
    nome: str,
    posto: str,
    data_ref: datetime,
    efetivo_dias: int,
    acrescimos_dias: int,
    ferias_anuais_simples: int,
    ferias_premio_simples: int,
    arredondamento: int,
    descontos: int,
    total_final: int,
    data_6qq: datetime,
    data_trint: datetime,
) -> BytesIO:
    wb = load_workbook(caminho_modelo)
    ws = wb.active

    ws["B2"] = nome
    ws["B3"] = posto
    ws["B4"] = data_ref.strftime("%d/%m/%Y")

    ws["B6"] = efetivo_dias
    ws["B7"] = acrescimos_dias
    ws["B8"] = ferias_anuais_simples
    ws["B9"] = ferias_premio_simples
    ws["B10"] = arredondamento
    ws["B11"] = descontos
    ws["B12"] = total_final

    ws["B14"] = data_6qq.strftime("%d/%m/%Y")
    ws["B15"] = data_trint.strftime("%d/%m/%Y")

    output = BytesIO()
    wb.save(output)
    output.seek(0)
    return output


# =========================================================
# INTERFACE
# =========================================================

st.title("Cálculo de Quinquênio / Trintenário - PMMG")

st.write("Envie o PDF do SIRH e informe os campos necessários para reproduzir a lógica da planilha manual.")

pdf_file = st.file_uploader("PDF do SIRH", type=["pdf"])

st.subheader("Campos editáveis da planilha")
col1, col2 = st.columns(2)

with col1:
    nome_manual = st.text_input("Nome")
    posto_manual = st.text_input("Posto / Graduação")
    ferias_anuais_simples = st.number_input("Férias anuais não gozadas (dias simples)", min_value=0, value=0, step=1)
    ferias_premio_simples = st.number_input("Férias-prêmio não gozadas (dias simples)", min_value=0, value=0, step=1)

with col2:
    arredondamento = st.number_input("Arredondamento (dias)", min_value=0, value=0, step=1)
    descontos = st.number_input("Descontos (dias)", min_value=0, value=0, step=1)

modelo_excel = "/mnt/data/modelo_planilha_oficial.xlsx"

if pdf_file is not None:
    texto = extrair_texto_pdf(pdf_file)

    data_ref = extrair_data_referencia(texto)

    efetivo_anos, efetivo_dias_rest = extrair_anos_dias_label(
        texto,
        r"Tempo de Efetivo Serviço"
    )
    acresc_anos, acresc_dias_rest = extrair_anos_dias_label(
        texto,
        r"TOTAL DE ACR[ÉE]SCIMOS LEGAIS"
    )

    efetivo_dias = anos_dias_para_dias(efetivo_anos, efetivo_dias_rest)
    acrescimos_dias = anos_dias_para_dias(acresc_anos, acresc_dias_rest)

    total_sirh = efetivo_dias + acrescimos_dias

    total_final = (
        total_sirh
        + (ferias_anuais_simples * 2)
        + (ferias_premio_simples * 2)
        + arredondamento
        - descontos
    )

    if data_ref is None:
        st.error("Não foi possível localizar a data de referência no PDF.")
        st.stop()

    data_6qq = calcular_data_quinquenio(data_ref, total_final, 6)
    data_trint = calcular_data_trintenario(data_ref, total_final)

    st.subheader("Auditoria")
    auditoria = pd.DataFrame(
        [
            ["Data de referência", data_ref.strftime("%d/%m/%Y")],
            ["Efetivo (dias)", efetivo_dias],
            ["Acréscimos legais (dias)", acrescimos_dias],
            ["Total SIRH (dias)", total_sirh],
            ["Férias anuais em dobro", ferias_anuais_simples * 2],
            ["Férias-prêmio em dobro", ferias_premio_simples * 2],
            ["Arredondamento", arredondamento],
            ["Descontos", descontos],
            ["Total final computável", total_final],
        ],
        columns=["Campo", "Valor"]
    )
    st.dataframe(auditoria, use_container_width=True)

    st.subheader("Resultado")
    st.write(f"**6º Quinquênio:** {data_6qq.strftime('%d/%m/%Y')}")
    st.write(f"**Adicional Trintenário:** {data_trint.strftime('%d/%m/%Y')}")

    st.subheader("Demais quinquênios")
    resultados = []
    for i in range(1, 10):
        dt = calcular_data_quinquenio(data_ref, total_final, i)
        status = "Adquirido" if dt.date() <= data_ref.date() else "Futuro"
        anos, meses, dias = diff_ymd(data_ref, dt) if dt > data_ref else (0, 0, 0)
        resultados.append(
            {
                "Quinquênio": f"{i}º",
                "Data": dt.strftime("%d/%m/%Y"),
                "Status": status,
                "Faltam": f"{anos}a {meses}m {dias}d" if status == "Futuro" else "-"
            }
        )

    st.dataframe(pd.DataFrame(resultados), use_container_width=True)

    nome_export = nome_manual.strip() if nome_manual.strip() else "Sem nome"
    posto_export = posto_manual.strip() if posto_manual.strip() else "Não informado"

    try:
        excel_bytes = preencher_modelo_excel(
            caminho_modelo=modelo_excel,
            nome=nome_export,
            posto=posto_export,
            data_ref=data_ref,
            efetivo_dias=efetivo_dias,
            acrescimos_dias=acrescimos_dias,
            ferias_anuais_simples=ferias_anuais_simples,
            ferias_premio_simples=ferias_premio_simples,
            arredondamento=arredondamento,
            descontos=descontos,
            total_final=total_final,
            data_6qq=data_6qq,
            data_trint=data_trint,
        )

        st.download_button(
            label="Baixar planilha preenchida",
            data=excel_bytes,
            file_name="planilha_preenchida.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )
    except FileNotFoundError:
        st.warning("Modelo Excel não encontrado em /mnt/data/modelo_planilha_oficial.xlsx")
