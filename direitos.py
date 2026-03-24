from __future__ import annotations

import re
from dataclasses import dataclass, asdict
from datetime import date, timedelta
from typing import Optional, List, Dict, Tuple

import pdfplumber
import streamlit as st

EC57_CORTE = date(2003, 7, 15)

# =============================
# Helpers
# =============================

def fmt_date(d: date) -> str:
    meses = [
        "janeiro", "fevereiro", "março", "abril", "maio", "junho",
        "julho", "agosto", "setembro", "outubro", "novembro", "dezembro"
    ]
    return f"{d.day} de {meses[d.month - 1]} de {d.year}"


def fmt_ddmmyyyy(d: date) -> str:
    return d.strftime("%d/%m/%Y")


def legal_days(anos: int, dias: int) -> int:
    """Converte a fração anual jurídica (365) para dias.
    Mantido porque o próprio SIRH resume os tempos como anos + dias nessa base.
    """
    return anos * 365 + dias


def parse_date_br(s: str) -> date:
    d, m, y = s.split("/")
    return date(int(y), int(m), int(d))


def inclusive_days(start: date, end: date) -> int:
    return (end - start).days + 1


def days_to_anos_dias(n: int) -> Tuple[int, int]:
    return n // 365, n % 365


def days_label(n: int) -> str:
    n = abs(n)
    a, d = divmod(n, 365)
    return f"{a}a {d}d" if a else f"{d}d"


def normalize_text(text: str) -> str:
    text = text.replace("\r", "")
    text = re.sub(r"[\t\xa0]+", " ", text)
    text = re.sub(r" +", " ", text)
    return text


def extract_text_from_pdf(file) -> str:
    texts: List[str] = []
    with pdfplumber.open(file) as pdf:
        for page in pdf.pages:
            txt = page.extract_text() or ""
            texts.append(txt)
    return normalize_text("\n".join(texts))


def section_between(text: str, start_pat: str, end_pat: str) -> str:
    pattern = rf"{start_pat}(.*?){end_pat}"
    m = re.search(pattern, text, re.IGNORECASE | re.DOTALL)
    return m.group(1) if m else ""


def sum_numbers_before_keyword(block: str, keyword: str) -> int:
    total = 0
    for line in block.splitlines():
        if keyword.lower() in line.lower():
            nums = re.findall(r"\b\d+\b", line)
            if nums:
                total += int(nums[-1])
    return total


def parse_anos_dias_after(label_regex: str, text: str) -> Tuple[int, int]:
    patterns = [
        rf"{label_regex}\s*:?\s*(\d+)\s+(\d+)",
        rf"{label_regex}.*?\n\s*(\d+)\s+(\d+)",
    ]
    for pat in patterns:
        m = re.search(pat, text, re.IGNORECASE | re.DOTALL)
        if m:
            return int(m.group(1)), int(m.group(2))
    return 0, 0


@dataclass
class ParsedData:
    nome: str
    posto: str
    numero_pm: str
    quadro: str
    unidade: str
    data_referencia: date

    efetivo_anos: int
    efetivo_dias: int
    tempo_deduzir_anos: int
    tempo_deduzir_dias: int
    total_anos_servico: int
    total_dias_servico: int
    acrescimos_anos: int
    acrescimos_dias: int
    arredondamento_dias: int

    ferias_anuais_vantagem_simples: int
    ferias_anuais_nao_gozadas_simples: int
    ferias_premio_contadas_simples: int
    ferias_premio_nao_gozadas_simples: int
    servico_publico_averbado_dias: int
    servico_inss_averbado_dias: int

    @property
    def efetivo_total_dias(self) -> int:
        return legal_days(self.efetivo_anos, self.efetivo_dias)

    @property
    def tempo_deduzir_total_dias(self) -> int:
        return legal_days(self.tempo_deduzir_anos, self.tempo_deduzir_dias)

    @property
    def total_servico_total_dias(self) -> int:
        return legal_days(self.total_anos_servico, self.total_dias_servico)

    @property
    def acrescimos_total_dias(self) -> int:
        return legal_days(self.acrescimos_anos, self.acrescimos_dias)

    @property
    def ingresso_estimado(self) -> date:
        # contagem inclusiva: de start até ref = efetivo_total_dias
        return self.data_referencia - timedelta(days=self.efetivo_total_dias - 1)


def parse_sirh_pdf(text: str) -> ParsedData:
    nome = re.search(r"NOME:\s*(.+)", text, re.IGNORECASE)
    posto = re.search(r"POSTO\s+OU\s+GRADUA[ÇC][ÃA]O:\s*(.+?)\s+N[ÚU]MERO\s+PM", text, re.IGNORECASE)
    numero_pm = re.search(r"N[ÚU]MERO\s+PM:\s*([\d.\-]+)", text, re.IGNORECASE)
    quadro = re.search(r"PERTENCE\s+AO\s+QUADRO:\s*(\S+)", text, re.IGNORECASE)
    unidade = re.search(r"UNIDADE:\s*(.+)", text, re.IGNORECASE)

    ref_m = re.search(r"AT[ÉE]\s+A\s+DATA\s+DE\s+(\d{2}/\d{2}/\d{4})", text, re.IGNORECASE)
    if not ref_m:
        ref_m = re.search(r"DATA DE\s+(\d{2}/\d{2}/\d{4})", text, re.IGNORECASE)
    ref = parse_date_br(ref_m.group(1)) if ref_m else date.today()

    efetivo_anos, efetivo_dias = parse_anos_dias_after(r"TOTAL DO TEMPO DE EFETIVO SERVI[ÇC]O NA PMMG", text)
    ded_anos, ded_dias = parse_anos_dias_after(r"Tempo a deduzir", text)
    acres_anos, acres_dias = parse_anos_dias_after(r"TOTAL DE ACR[ÉE]SCIMOS LEGAIS", text)
    total_anos, total_dias = parse_anos_dias_after(r"TOTAL DE ANOS DE SERVI[ÇC]O", text)
    arred_anos, arred_dias = parse_anos_dias_after(r"Arredondamento \(at[ée] 182 dias\)", text)
    arredondamento_dias = legal_days(arred_anos, arred_dias)

    # Férias anuais – VANTAGEM
    bloco_fa_vant = section_between(
        text,
        r"F[ÉE]RIAS\s+ANUAIS\s*[–-]\s*VANTAGEM",
        r"F[ÉE]RIAS\s+ANUAIS\s*[–-]\s*N[ÃA]O\s+GOZADAS",
    )
    ferias_anuais_vantagem_simples = sum_numbers_before_keyword(bloco_fa_vant, "Dobro")

    # Férias anuais – NÃO GOZADAS
    bloco_fa_ng = section_between(
        text,
        r"F[ÉE]RIAS\s+ANUAIS\s*[–-]\s*N[ÃA]O\s+GOZADAS",
        r"RESUMO\s+DO\s+TEMPO\s+DE\s+SERVI[ÇC]O",
    )
    ferias_anuais_nao_gozadas_simples = sum_numbers_before_keyword(bloco_fa_ng, "Dobro")

    # Férias-prêmio contadas como tempo
    bloco_fp_cont = section_between(
        text,
        r"F[ÉE]RIAS\s+PR[ÊE]MIO\s*[-–]\s*CONTADAS\s+COMO\s+TEMPO\s+DE\s+SERVI[ÇC]O\s*/\s*VANTAGEM",
        r"F[ÉE]RIAS\s+PR[ÊE]MIO\s+N[ÃA]O\s+GOZADAS",
    )
    # nesse bloco, normalmente cada linha do quinquênio traz 90 dias
    premio_contadas = []
    for line in bloco_fp_cont.splitlines():
        if re.search(r"\bDobro\b", line, re.IGNORECASE):
            nums = re.findall(r"\b\d+\b", line)
            if nums:
                premio_contadas.append(int(nums[-2] if len(nums) >= 2 else nums[-1]))
    ferias_premio_contadas_simples = sum(premio_contadas)

    # Férias-prêmio não gozadas (se houver listagem)
    bloco_fp_ng = section_between(
        text,
        r"F[ÉE]RIAS\s+PR[ÊE]MIO\s+N[ÃA]O\s+GOZADAS",
        r"F[ÉE]RIAS\s+ANUAIS\s*[–-]\s*VANTAGEM|RESUMO\s+DO\s+TEMPO\s+DE\s+SERVI[ÇC]O",
    )
    ferias_premio_nao_gozadas_simples = sum_numbers_before_keyword(bloco_fp_ng, "Dobro")

    spub_anos, spub_dias = parse_anos_dias_after(r"Tempo de servi[çc]o p[úu]blico averbado", text)
    inss_anos, inss_dias = parse_anos_dias_after(r"Tempo averbado vinculado ao INSS", text)

    return ParsedData(
        nome=nome.group(1).strip() if nome else "Não identificado",
        posto=posto.group(1).strip() if posto else "—",
        numero_pm=numero_pm.group(1).strip() if numero_pm else "—",
        quadro=quadro.group(1).strip() if quadro else "—",
        unidade=unidade.group(1).strip() if unidade else "—",
        data_referencia=ref,
        efetivo_anos=efetivo_anos,
        efetivo_dias=efetivo_dias,
        tempo_deduzir_anos=ded_anos,
        tempo_deduzir_dias=ded_dias,
        total_anos_servico=total_anos,
        total_dias_servico=total_dias,
        acrescimos_anos=acres_anos,
        acrescimos_dias=acres_dias,
        arredondamento_dias=arredondamento_dias,
        ferias_anuais_vantagem_simples=ferias_anuais_vantagem_simples,
        ferias_anuais_nao_gozadas_simples=ferias_anuais_nao_gozadas_simples,
        ferias_premio_contadas_simples=ferias_premio_contadas_simples,
        ferias_premio_nao_gozadas_simples=ferias_premio_nao_gozadas_simples,
        servico_publico_averbado_dias=legal_days(spub_anos, spub_dias),
        servico_inss_averbado_dias=legal_days(inss_anos, inss_dias),
    )


@dataclass
class AuditModel:
    ingresso_estimado: date
    incluir_anuais_nao_gozadas: bool
    bonus_fixo_dias: int
    total_modelo_na_data_base: int
    diferenca_vs_sirh_total: int
    detalhes: Dict[str, int]


def build_audit_model(
    data: ParsedData,
    incluir_anuais_nao_gozadas: bool,
    ajuste_manual_dias: int,
) -> AuditModel:
    detalhes = {
        "Efetivo serviço (dias)": data.efetivo_total_dias,
        "Férias anuais – vantagem (simples)": data.ferias_anuais_vantagem_simples,
        "Férias anuais – vantagem (dobro)": data.ferias_anuais_vantagem_simples * 2,
        "Férias anuais – não gozadas (simples)": data.ferias_anuais_nao_gozadas_simples,
        "Férias anuais – não gozadas (dobro)": data.ferias_anuais_nao_gozadas_simples * 2,
        "Férias-prêmio contadas (simples)": data.ferias_premio_contadas_simples,
        "Férias-prêmio contadas (dobro)": data.ferias_premio_contadas_simples * 2,
        "Férias-prêmio não gozadas (simples)": data.ferias_premio_nao_gozadas_simples,
        "Férias-prêmio não gozadas (dobro)": data.ferias_premio_nao_gozadas_simples * 2,
        "Serviço público averbado": data.servico_publico_averbado_dias,
        "Tempo vinculado ao INSS": data.servico_inss_averbado_dias,
        "Arredondamento": data.arredondamento_dias,
        "Tempo a deduzir": data.tempo_deduzir_total_dias,
        "Ajuste manual": ajuste_manual_dias,
    }

    bonus_fixo = (
        data.ferias_anuais_vantagem_simples * 2
        + data.ferias_premio_contadas_simples * 2
        + data.ferias_premio_nao_gozadas_simples * 2
        + data.servico_publico_averbado_dias
        + data.servico_inss_averbado_dias
        + data.arredondamento_dias
        - data.tempo_deduzir_total_dias
        + ajuste_manual_dias
    )

    if incluir_anuais_nao_gozadas:
        bonus_fixo += data.ferias_anuais_nao_gozadas_simples * 2

    total_modelo = data.efetivo_total_dias + bonus_fixo

    return AuditModel(
        ingresso_estimado=data.ingresso_estimado,
        incluir_anuais_nao_gozadas=incluir_anuais_nao_gozadas,
        bonus_fixo_dias=bonus_fixo,
        total_modelo_na_data_base=total_modelo,
        diferenca_vs_sirh_total=total_modelo - data.total_servico_total_dias,
        detalhes=detalhes,
    )


def acquisition_date(ref: date, total_na_data_base: int, marco_dias: int) -> date:
    """Data aquisitiva a partir da data-base do relatório.
    Se a modelagem estiver correta, a data resultante é invariável em relação à data-base.
    """
    excesso = total_na_data_base - marco_dias
    return ref - timedelta(days=excesso)


def acquisition_date_from_start(start: date, bonus_fixo_dias: int, marco_dias: int) -> date:
    """Mesma data aquisitiva, mas por busca a partir do ingresso estimado.
    Mantida como auditoria cruzada de invariância.
    """
    # data d tal que dias inclusivos(start, d) + bonus_fixo = marco
    # logo: dias inclusivos(start, d) = marco - bonus_fixo
    efetivo_necessario = marco_dias - bonus_fixo_dias
    return start + timedelta(days=efetivo_necessario - 1)


def quinquenio_items(data: ParsedData, audit: AuditModel, max_future: int = 3) -> List[Dict]:
    items = []
    ref = data.data_referencia
    future_count = 0
    for q in range(1, 20):
        marco = q * 5 * 365
        d1 = acquisition_date(ref, audit.total_modelo_na_data_base, marco)
        d2 = acquisition_date_from_start(audit.ingresso_estimado, audit.bonus_fixo_dias, marco)
        miss = marco - audit.total_modelo_na_data_base
        acquired = miss <= 0
        items.append(
            {
                "marco": f"{q}º quinquênio",
                "percentual": "+10%",
                "data_direito": d1,
                "data_direito_auditoria": d2,
                "consistente": d1 == d2,
                "status": "✅ Já adquirido" if acquired else f"⏳ Faltam {days_label(miss)}",
                "faltam_dias": max(miss, 0),
            }
        )
        if not acquired:
            future_count += 1
            if future_count >= max_future:
                break
    return items


def ade_items(ingresso: date, ref: date) -> List[Dict]:
    marcos = [
        (3, "até 6%"),
        (5, "até 10%"),
        (10, "até 20%"),
        (15, "até 30%"),
        (20, "até 40%"),
        (25, "até 50%"),
        (30, "até 60% na ativa / até 70% na inatividade"),
    ]
    out = []
    for anos, pct in marcos:
        alvo = date(ingresso.year + anos, ingresso.month, ingresso.day)
        miss = (alvo - ref).days
        out.append(
            {
                "marco": f"{anos} ADIs",
                "percentual": pct,
                "data": alvo,
                "status": "✅ Marco temporal atingido" if miss <= 0 else f"⏳ Faltam {days_label(miss)}",
            }
        )
    return out


def trintenario_item(data: ParsedData, audit: AuditModel) -> Dict:
    marco = 30 * 365
    d1 = acquisition_date(data.data_referencia, audit.total_modelo_na_data_base, marco)
    d2 = acquisition_date_from_start(audit.ingresso_estimado, audit.bonus_fixo_dias, marco)
    miss = marco - audit.total_modelo_na_data_base
    return {
        "marco": "Adicional trintenário",
        "percentual": "+10%",
        "data_direito": d1,
        "data_direito_auditoria": d2,
        "consistente": d1 == d2,
        "status": "✅ Já adquirido" if miss <= 0 else f"⏳ Faltam {days_label(miss)}",
        "faltam_dias": max(miss, 0),
    }


# =============================
# UI
# =============================

st.set_page_config(page_title="Direitos PMMG — Auditoria", layout="wide")
st.title("Cálculo de quinquênio, trintenário e ADE — com auditoria")
st.caption(
    "Entrada: certidão/relatório do SIRH. Saída: cálculo auditável, com trilha dos dias usados e dupla validação da data aquisitiva."
)

with st.expander("O que esta versão corrige", expanded=False):
    st.markdown(
        """
- A data aquisitiva não depende da data-base do relatório: o app calcula por duas rotas e compara o resultado.
- A base de cálculo deixa de usar o `total_corrigido` antigo e passa a montar um **modelo auditável**.
- O modelo oficial, por padrão, **inclui** férias anuais de vantagem, férias-prêmio, averbações e arredondamento.
- Por padrão, **exclui** férias anuais não gozadas, porque esse foi o ponto que gerou divergência no caso analisado.
- Há um ajuste manual em dias para calibrar o modelo em situações excepcionais.
        """
    )

uploaded = st.file_uploader("Anexe o PDF do SIRH", type=["pdf"])

if uploaded:
    text = extract_text_from_pdf(uploaded)
    data = parse_sirh_pdf(text)

    with st.sidebar:
        st.header("Parâmetros de auditoria")
        incluir_anuais_nao_gozadas = st.checkbox(
            "Incluir férias anuais não gozadas na base de quinquênio/trintenário",
            value=False,
            help="Desative para reproduzir a metodologia manual observada no caso do 6º quinquênio analisado.",
        )
        ajuste_manual_dias = st.number_input(
            "Ajuste manual adicional (dias)",
            value=0,
            step=1,
            help="Use apenas se a unidade adotar algum tratamento específico não capturado pelo PDF.",
        )
        max_future = st.slider("Quantidade de marcos futuros exibidos", 1, 6, 3)

    audit = build_audit_model(data, incluir_anuais_nao_gozadas, int(ajuste_manual_dias))

    col1, col2, col3 = st.columns(3)
    col1.metric("Militar", data.nome)
    col2.metric("Data-base do relatório", fmt_ddmmyyyy(data.data_referencia))
    col3.metric("Ingresso estimado (contagem inclusiva)", fmt_ddmmyyyy(audit.ingresso_estimado))

    st.subheader("Auditoria da base de cálculo")
    a1, a2, a3, a4 = st.columns(4)
    a1.metric("Efetivo (dias)", data.efetivo_total_dias)
    a2.metric("Bônus fixo do modelo (dias)", audit.bonus_fixo_dias)
    a3.metric("Total do modelo na data-base", audit.total_modelo_na_data_base)
    a4.metric("Total do SIRH na data-base", data.total_servico_total_dias)

    if audit.diferenca_vs_sirh_total != 0:
        st.warning(
            f"Diferença entre modelo auditado e total bruto do SIRH: {audit.diferenca_vs_sirh_total:+d} dias. "
            "É exatamente essa diferença de base que desloca a data do direito."
        )
    else:
        st.success("O total do modelo auditado coincide com o total bruto do SIRH.")

    detalhes_tabela = []
    for k, v in audit.detalhes.items():
        detalhes_tabela.append({"Componente": k, "Dias": v})
    st.dataframe(detalhes_tabela, use_container_width=True, hide_index=True)

    st.subheader("Validação de invariância da data aquisitiva")
    st.markdown(
        "A data aquisitiva é calculada por duas rotas independentes: "
        "(1) retroação a partir da data-base; (2) projeção a partir do ingresso estimado. "
        "As duas precisam bater."
    )

    direito_quinquenio = audit.ingresso_estimado <= EC57_CORTE

    if direito_quinquenio:
        st.subheader("📅 Quinquênios (art. 63)")
        for item in quinquenio_items(data, audit, max_future=max_future):
            st.markdown(f"**{item['marco'].title()} — {item['percentual']} sobre remuneração base**")
            st.write(f"Data do direito: **{fmt_date(item['data_direito'])}**")
            st.write(f"Auditoria cruzada: {fmt_date(item['data_direito_auditoria'])}")
            st.write(item["status"])
            if not item["consistente"]:
                st.error("Inconsistência entre as duas rotas de cálculo. Revise a base em dias.")
            st.divider()
    else:
        st.info(
            "Militar com ingresso estimado após 15/07/2003. Nesta modelagem, não se exibe quinquênio; exibe-se ADE."
        )

    st.subheader("📅 Adicional trintenário (art. 64)")
    tri = trintenario_item(data, audit)
    st.markdown(f"**{tri['marco']} — {tri['percentual']} sobre remuneração base**")
    st.write(f"Data do direito: **{fmt_date(tri['data_direito'])}**")
    st.write(f"Auditoria cruzada: {fmt_date(tri['data_direito_auditoria'])}")
    st.write(tri["status"])
    if not tri["consistente"]:
        st.error("Inconsistência entre as duas rotas de cálculo. Revise a base em dias.")

    st.subheader("📅 ADE (marcos temporais)")
    st.caption("O ADE continua condicionado ao cumprimento dos demais requisitos legais e ao resultado das ADIs.")
    ade_rows = []
    for row in ade_items(audit.ingresso_estimado, data.data_referencia):
        ade_rows.append(
            {
                "Marco": row["marco"],
                "% máximo": row["percentual"],
                "Data": fmt_ddmmyyyy(row["data"]),
                "Status": row["status"],
            }
        )
    st.dataframe(ade_rows, use_container_width=True, hide_index=True)

    with st.expander("Dados extraídos do PDF", expanded=False):
        st.json(
            {
                **asdict(data),
                "data_referencia": fmt_ddmmyyyy(data.data_referencia),
                "ingresso_estimado": fmt_ddmmyyyy(data.ingresso_estimado),
            }
        )

    with st.expander("Texto bruto extraído do PDF", expanded=False):
        st.text(text)
else:
    st.info("Anexe um PDF do SIRH para iniciar a análise.")
