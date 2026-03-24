import io
import re
from datetime import date, timedelta

import pdfplumber
import streamlit as st


st.set_page_config(page_title="Calculadora de Direitos – PMMG", page_icon="🪖", layout="centered")


# ──────────────────────────────────────────────────────────────────────────────
# ESTILO
# ──────────────────────────────────────────────────────────────────────────────
st.markdown(
    """
<style>
    .block-container { padding-top: 2rem; }
    .header-banner {
        background: linear-gradient(135deg, #1a1a2e 0%, #0f3460 100%);
        color: white; padding: 1.5rem 2rem; border-radius: 12px; margin-bottom: 1.5rem;
    }
    .header-banner h1 { margin: 0; font-size: 1.6rem; }
    .header-banner p  { margin: 0.3rem 0 0; font-size: 0.9rem; opacity: 0.82; }
    .militar-card {
        background: white; border-left: 5px solid #0f3460; border-radius: 8px;
        padding: 1rem 1.5rem; margin-bottom: 1.2rem; box-shadow: 0 2px 6px rgba(0,0,0,0.08);
    }
    .militar-card h3 { margin: 0 0 0.5rem; color: #0f3460; }
    .info-row { display: flex; gap: 2rem; flex-wrap: wrap; }
    .info-item { font-size: 0.9rem; color: #444; }
    .info-item span { font-weight: 600; color: #1a1a2e; }
    .section-title {
        font-size: 1.05rem; font-weight: 700; color: #0f3460;
        border-bottom: 2px solid #0f3460; padding-bottom: 0.3rem; margin: 1.5rem 0 0.8rem;
    }
    .right-card {
        border-radius: 10px; padding: 0.9rem 1.2rem; margin-bottom: 0.7rem;
        box-shadow: 0 2px 5px rgba(0,0,0,0.07);
    }
    .right-card.acquired { background: #e8f5e9; border-left: 5px solid #2e7d32; }
    .right-card.future   { background: #e3f2fd; border-left: 5px solid #1565c0; }
    .right-card.far      { background: #fafafa;  border-left: 5px solid #9e9e9e; }
    .rc-title { font-size: 0.98rem; font-weight: 700; margin-bottom: 0.15rem; }
    .right-card.acquired .rc-title { color: #2e7d32; }
    .right-card.future   .rc-title { color: #1565c0; }
    .right-card.far      .rc-title { color: #555; }
    .rc-date { font-size: 0.88rem; color: #333; line-height: 1.5; }
    .rc-badge {
        display: inline-block; font-size: 0.72rem; font-weight: 600;
        padding: 0.12rem 0.55rem; border-radius: 20px; margin-top: 0.4rem;
    }
    .badge-acquired { background: #2e7d32; color: white; }
    .badge-future   { background: #1565c0; color: white; }
    .badge-far      { background: #757575; color: white; }
    .time-table {
        background: white; border-radius: 8px; padding: 0.9rem 1.4rem;
        box-shadow: 0 2px 5px rgba(0,0,0,0.07); margin-bottom: 0.8rem;
    }
    .time-row {
        display: flex; justify-content: space-between; padding: 0.3rem 0;
        border-bottom: 1px solid #f0f0f0; font-size: 0.87rem; gap: 1rem;
    }
    .time-row:last-child { border-bottom: none; }
    .t-label { color: #555; }
    .t-value { font-weight: 600; color: #1a1a2e; text-align: right; }
    .warn-box {
        border-radius: 6px; padding: 0.75rem 1rem;
        font-size: 0.82rem; margin-bottom: 0.8rem;
    }
    .warn-box.orange { background: #fff3e0; border-left: 4px solid #e65100; color: #4e342e; }
    .warn-box.blue   { background: #e8eaf6; border-left: 4px solid #3949ab; color: #1a237e; }
    .warn-box.green  { background: #e8f5e9; border-left: 4px solid #2e7d32; color: #1b5e20; }
    .disclaimer {
        background: #fff8e1; border-left: 4px solid #f9a825; border-radius: 6px;
        padding: 0.8rem 1rem; font-size: 0.81rem; color: #5d4037; margin-top: 1.5rem;
    }
</style>
""",
    unsafe_allow_html=True,
)


# ──────────────────────────────────────────────────────────────────────────────
# CONSTANTES / REGRAS
# ──────────────────────────────────────────────────────────────────────────────
EC57_CORTE = date(2003, 7, 15)
DIAS_POR_ANO_LEGAL = 365
QUINQUENIO_DIAS = 5 * DIAS_POR_ANO_LEGAL
TRINTENARIO_DIAS = 30 * DIAS_POR_ANO_LEGAL
RESERVA_TOTAL_DIAS = 35 * DIAS_POR_ANO_LEGAL
RESERVA_EFETIVO_DIAS = 30 * DIAS_POR_ANO_LEGAL


# ──────────────────────────────────────────────────────────────────────────────
# HELPERS DE DATA / FORMATAÇÃO
# ──────────────────────────────────────────────────────────────────────────────
def td(anos: int, dias: int) -> int:
    return anos * DIAS_POR_ANO_LEGAL + dias


def fmt_date(d: date) -> str:
    months = [
        "janeiro", "fevereiro", "março", "abril", "maio", "junho",
        "julho", "agosto", "setembro", "outubro", "novembro", "dezembro",
    ]
    return f"{d.day} de {months[d.month - 1]} de {d.year}"


def fmt_anos_dias(total_dias: int) -> str:
    anos = total_dias // DIAS_POR_ANO_LEGAL
    dias = total_dias % DIAS_POR_ANO_LEGAL
    return f"{anos} anos e {dias} dias"


def days_label(n: int) -> str:
    a, d = abs(n) // DIAS_POR_ANO_LEGAL, abs(n) % DIAS_POR_ANO_LEGAL
    return f"{a}a {d}d" if a else f"{abs(n)}d"


def kind(target: date, ref: date) -> str:
    if target <= ref:
        return "acquired"
    return "future" if (target - ref).days <= QUINQUENIO_DIAS else "far"


def card(title: str, sub: str, badge: str, kind_name: str) -> str:
    return (
        f'<div class="right-card {kind_name}">'
        f'<div class="rc-title">{title}</div>'
        f'<div class="rc-date">{sub}</div>'
        f'<span class="rc-badge badge-{kind_name}">{badge}</span></div>'
    )


def add_calendar_years_safe(d: date, years: int) -> date:
    """Soma anos civis, tratando 29/02 em anos não bissextos."""
    try:
        return d.replace(year=d.year + years)
    except ValueError:
        # 29/02 -> 28/02 em ano não bissexto
        return d.replace(month=2, day=28, year=d.year + years)


def estimated_start_from_elapsed(end_date: date, elapsed_days: int) -> date:
    """
    Reconstrói a data inicial com contagem inclusiva.
    Ex.: 31/01/2000 até 06/03/2026 = 9532 dias  ->  start = end - (9532 - 1)
    """
    if elapsed_days <= 0:
        return end_date
    return end_date - timedelta(days=elapsed_days - 1)


def attained_date_from_total(ref: date, total_days: int, marco_days: int) -> date:
    """
    Data histórica em que o marco foi atingido.
    Mantém a coerência com a metodologia da planilha: marco legal em dias de 365,
    e projeção/reconstrução por diferença em dias corridos no calendário.
    """
    return ref - timedelta(days=(total_days - marco_days))


# ──────────────────────────────────────────────────────────────────────────────
# PARSERS
# ──────────────────────────────────────────────────────────────────────────────
def normalize_spaces(text: str) -> str:
    text = text.replace("\r", "\n")
    text = re.sub(r"[ \t]+", " ", text)
    return text


def extract_text_from_pdf(file_obj) -> str:
    with pdfplumber.open(io.BytesIO(file_obj.read())) as pdf:
        pages = [(p.extract_text() or "") for p in pdf.pages]
    return normalize_spaces("\n".join(pages))


def parse_anos_dias(keyword: str, text: str) -> tuple[int, int]:
    for line in text.split("\n"):
        if keyword.upper() in line.upper():
            m = re.search(r":\s*(\d+)\s+(\d+)\s*$", line)
            if m:
                return int(m.group(1)), int(m.group(2))
    return 0, 0


def parse_single_int(pattern: str, text: str, flags: int = re.IGNORECASE) -> int:
    m = re.search(pattern, text, flags)
    return int(m.group(1)) if m else 0


def parse_section_sum(text: str, section_title_pattern: str, row_pattern: str) -> int:
    m = re.search(section_title_pattern, text, re.IGNORECASE | re.DOTALL)
    if not m:
        return 0
    block = m.group(0)
    total = 0
    for v in re.findall(row_pattern, block, re.IGNORECASE | re.MULTILINE):
        total += int(v)
    return total


def parse_nome(text: str) -> str:
    m = re.search(r"NOME:\s*(.+)", text, re.IGNORECASE)
    return m.group(1).strip() if m else "Não identificado"


def parse_posto(text: str) -> str:
    m = re.search(r"POSTO\s+OU\s+GRADUA[ÇC][ÃA]O:\s*(.+?)\s+N[ÚU]MERO\s+PM", text, re.IGNORECASE)
    return m.group(1).strip() if m else "—"


def parse_numero_pm(text: str) -> str:
    m = re.search(r"N[ÚU]MERO\s+PM:\s*([\d.\-]+)", text, re.IGNORECASE)
    return m.group(1).strip() if m else "—"


def parse_quadro(text: str) -> str:
    m = re.search(r"PERTENCE\s+AO\s+QUADRO:\s*(\S+)", text, re.IGNORECASE)
    return m.group(1).strip() if m else "—"


def parse_unidade(text: str) -> str:
    m = re.search(r"UNIDADE:\s*(.+)", text, re.IGNORECASE)
    return m.group(1).strip() if m else "—"


def parse_data_referencia(text: str) -> date:
    m = re.search(r"ATÉ A DATA DE\s*(\d{2}/\d{2}/\d{4})", text, re.IGNORECASE)
    if not m:
        m = re.search(r"DATA DE\s*(\d{2}/\d{2}/\d{4})", text, re.IGNORECASE)
    if not m:
        return date.today()
    d, mo, y = m.group(1).split("/")
    return date(int(y), int(mo), int(d))


def parse_pdf(file_obj) -> dict | None:
    try:
        text = extract_text_from_pdf(file_obj)
    except Exception as exc:
        st.error(f"Erro ao ler o PDF: {exc}")
        return None

    if "CONTAGEM DE TEMPO" not in text.upper():
        st.error("O arquivo não parece ser um relatório de Contagem de Tempo da PMMG.")
        return None

    nome = parse_nome(text)
    posto = parse_posto(text)
    numero_pm = parse_numero_pm(text)
    quadro = parse_quadro(text)
    unidade = parse_unidade(text)
    data_referencia = parse_data_referencia(text)

    efetivo_anos, efetivo_dias = parse_anos_dias("TOTAL DO TEMPO DE EFETIVO SERVI", text)
    acrescimo_anos, acrescimo_dias = parse_anos_dias("TOTAL DE ACR", text)
    total_anos, total_dias = parse_anos_dias("TOTAL DE ANOS DE SERVI", text)

    efetivo_total_dias = td(efetivo_anos, efetivo_dias)
    acrescimo_total_dias = td(acrescimo_anos, acrescimo_dias)
    total_servico_dias = td(total_anos, total_dias)

    # Componentes informativos extraídos do SIRH
    ferias_anuais_simples = parse_single_int(r"Férias anuais contadas de forma simples:\s*(\d+)\s+(\d+)", text)
    ferias_anuais_dobro = 0
    m_fad = re.search(r"Férias anuais contadas em dobro:\s*(\d+)\s+(\d+)", text, re.IGNORECASE)
    if m_fad:
        ferias_anuais_dobro = td(int(m_fad.group(1)), int(m_fad.group(2)))

    m_fps = re.search(r"Férias-prêmio contadas de forma simples:\s*(\d+)\s+(\d+)", text, re.IGNORECASE)
    ferias_premio_simples = td(int(m_fps.group(1)), int(m_fps.group(2))) if m_fps else 0

    m_fpd = re.search(r"Férias-prêmio contadas em dobro:\s*(\d+)\s+(\d+)", text, re.IGNORECASE)
    ferias_premio_dobro = td(int(m_fpd.group(1)), int(m_fpd.group(2))) if m_fpd else 0

    m_avb = re.search(r"Tempo de serviço público averbado:\s*(\d+)\s+(\d+)", text, re.IGNORECASE)
    averbado_publico = td(int(m_avb.group(1)), int(m_avb.group(2))) if m_avb else 0

    m_inss = re.search(r"Tempo averbado vinculado ao INSS:\s*(\d+)\s+(\d+)", text, re.IGNORECASE)
    averbado_inss = td(int(m_inss.group(1)), int(m_inss.group(2))) if m_inss else 0

    m_arred = re.search(r"Arredondamento \(até 182 dias\):\s*(\d+)\s+(\d+)", text, re.IGNORECASE)
    arredondamento_dias = td(int(m_arred.group(1)), int(m_arred.group(2))) if m_arred else 0

    # Entrada auxiliar: apenas para transparência. Não é usado para subtrair nada.
    bloco_nao_gozadas = re.search(
        r"FÉRIAS ANUAIS\s*[–-]\s*NÃO GOZADAS.*?(?=RESUMO|FÉRIAS\s+PRÊMIO\s+NÃO|$)",
        text,
        re.IGNORECASE | re.DOTALL,
    )
    ferias_anuais_nao_gozadas_simples = 0
    if bloco_nao_gozadas:
        for dias in re.findall(r"^\d{4}\s+(\d+)\s+Dobro", bloco_nao_gozadas.group(0), re.MULTILINE | re.IGNORECASE):
            ferias_anuais_nao_gozadas_simples += int(dias)

    ingresso_estimado = estimated_start_from_elapsed(data_referencia, efetivo_total_dias)

    return {
        "nome": nome,
        "posto": posto,
        "numero_pm": numero_pm,
        "quadro": quadro,
        "unidade": unidade,
        "data_referencia": data_referencia,
        "efetivo_anos": efetivo_anos,
        "efetivo_dias": efetivo_dias,
        "efetivo_total_dias": efetivo_total_dias,
        "acrescimo_anos": acrescimo_anos,
        "acrescimo_dias": acrescimo_dias,
        "acrescimo_total_dias": acrescimo_total_dias,
        "total_anos": total_anos,
        "total_dias": total_dias,
        "total_servico_dias": total_servico_dias,
        "ingresso_estimado": ingresso_estimado,
        "ferias_anuais_simples": ferias_anuais_simples,
        "ferias_anuais_dobro": ferias_anuais_dobro,
        "ferias_premio_simples": ferias_premio_simples,
        "ferias_premio_dobro": ferias_premio_dobro,
        "averbado_publico": averbado_publico,
        "averbado_inss": averbado_inss,
        "arredondamento_dias": arredondamento_dias,
        "ferias_anuais_nao_gozadas_simples": ferias_anuais_nao_gozadas_simples,
        "texto_extraido": text,
    }


# ──────────────────────────────────────────────────────────────────────────────
# CÁLCULO DOS DIREITOS
# ──────────────────────────────────────────────────────────────────────────────
def quinquenio_applicable(ingresso_estimado: date) -> bool:
    return ingresso_estimado <= EC57_CORTE


def compute_rights(data: dict) -> list[dict]:
    ref = data["data_referencia"]
    total_servico = data["total_servico_dias"]
    efetivo = data["efetivo_total_dias"]
    ingresso = data["ingresso_estimado"]

    out: list[dict] = []

    # Quinquênios
    if quinquenio_applicable(ingresso):
        future_count = 0
        for q in range(1, 20):
            marco = q * QUINQUENIO_DIAS
            if total_servico >= marco:
                target = attained_date_from_total(ref, total_servico, marco)
                sub = f"Adquirido em {fmt_date(target)}"
                badge = "✅ Já adquirido"
                k = "acquired"
            else:
                faltam = marco - total_servico
                target = ref + timedelta(days=faltam)
                sub = f"Previsão: {fmt_date(target)} (faltam {days_label(faltam)})"
                badge = f"⏳ {days_label(faltam)}"
                k = kind(target, ref)
                future_count += 1

            out.append(
                {
                    "title": f"{q}º Quinquênio — +10% sobre remuneração base",
                    "sub": sub,
                    "badge": badge,
                    "kind": k,
                    "target": target,
                    "group": "quinquenio",
                    "order": q,
                }
            )
            if future_count >= 3:
                break
    else:
        out.append(
            {
                "title": "Quinquênio — não aplicável",
                "sub": (
                    "Militar enquadrado no regime posterior à EC 57/2003. "
                    "Para esses casos, a referência principal passa a ser o ADE."
                ),
                "badge": "ℹ️ Ver seção ADE",
                "kind": "far",
                "target": ref,
                "group": "quinquenio",
                "order": 0,
            }
        )

    # ADE — marco anual em calendário civil
    # Observação: a concessão depende também das ADIs ≥ 70%.
    marcos_ade = [
        (3, "6%", "até 6% (3 ADIs)"),
        (5, "10%", "até 10% (5 ADIs)"),
        (10, "20%", "até 20% (10 ADIs)"),
        (15, "30%", "até 30% (15 ADIs)"),
        (20, "40%", "até 40% (20 ADIs)"),
        (25, "50%", "até 50% (25 ADIs)"),
        (30, "60%", "até 60% na ativa / até 70% na inatividade (30 ADIs)"),
    ]
    for anos_adi, _pct_curto, pct_label in marcos_ade:
        target = add_calendar_years_safe(ingresso, anos_adi)
        miss = (target - ref).days
        if miss <= 0:
            sub = (
                f"Marco temporal atingido em {fmt_date(target)}<br>"
                f"<em>Requer {anos_adi} ADIs com resultado ≥ 70%</em>"
            )
            badge = "✅ Marco temporal atingido"
            k = "acquired"
        else:
            sub = (
                f"Previsão: {fmt_date(target)} (faltam {days_label(miss)})<br>"
                f"<em>Requer {anos_adi} ADIs com resultado ≥ 70%</em>"
            )
            badge = f"⏳ {days_label(miss)}"
            k = kind(target, ref)

        out.append(
            {
                "title": f"ADE — {pct_label}",
                "sub": sub,
                "badge": badge,
                "kind": k,
                "target": target,
                "group": "ade",
                "order": anos_adi,
            }
        )

    # Trintenário
    if total_servico >= TRINTENARIO_DIAS:
        t30 = attained_date_from_total(ref, total_servico, TRINTENARIO_DIAS)
        sub30 = f"Adquirido em {fmt_date(t30)}"
        badge30 = "✅ Já adquirido"
        k30 = "acquired"
    else:
        faltam30 = TRINTENARIO_DIAS - total_servico
        t30 = ref + timedelta(days=faltam30)
        sub30 = f"Previsão: {fmt_date(t30)} (faltam {days_label(faltam30)})"
        badge30 = f"⏳ {days_label(faltam30)}"
        k30 = kind(t30, ref)

    out.append(
        {
            "title": "Adicional Trintenário — +10% sobre remuneração base",
            "sub": sub30,
            "badge": badge30,
            "kind": k30,
            "target": t30,
            "group": "trintenario",
            "order": 0,
        }
    )

    # Abono / Reserva
    faltam_total_35 = max(0, RESERVA_TOTAL_DIAS - total_servico)
    faltam_ef_30 = max(0, RESERVA_EFETIVO_DIAS - efetivo)
    days_ab = max(faltam_total_35, faltam_ef_30)
    target_ab = ref + timedelta(days=days_ab)
    limiting = (
        "35 anos de serviço total"
        if faltam_total_35 >= faltam_ef_30
        else "30 anos de efetivo exercício militar"
    )

    if days_ab == 0:
        sub_ab = f"Adquirido em {fmt_date(target_ab)}"
        badge_ab = "✅ Já adquirido"
        kab = "acquired"
    else:
        sub_ab = (
            f"Previsão: {fmt_date(target_ab)} (faltam {days_label(days_ab)})<br>"
            f"<em>Fator limitante: {limiting}</em>"
        )
        badge_ab = f"⏳ {days_label(days_ab)}"
        kab = kind(target_ab, ref)

    out.append(
        {
            "title": "Abono de Permanência — 1/3 dos vencimentos",
            "sub": sub_ab,
            "badge": badge_ab,
            "kind": kab,
            "target": target_ab,
            "group": "abono",
            "order": 0,
        }
    )
    out.append(
        {
            "title": "Elegibilidade para Transferência Voluntária à Reserva",
            "sub": sub_ab,
            "badge": badge_ab,
            "kind": kab,
            "target": target_ab,
            "group": "reserva",
            "order": 0,
        }
    )

    return out


# ──────────────────────────────────────────────────────────────────────────────
# UI
# ──────────────────────────────────────────────────────────────────────────────
st.markdown(
    """
<div class="header-banner">
    <h1>🪖 Calculadora de Direitos – PMMG</h1>
    <p>Quinquênio · ADE · Adicional Trintenário · Abono de Permanência · Reserva Voluntária</p>
    <p style="opacity:0.55;font-size:0.77rem">
        Lógica ajustada para reproduzir a metodologia da planilha manual: marcos jurídicos em dias de 365,
        sem subtrair automaticamente férias anuais não gozadas do total informado pelo SIRH.
    </p>
</div>
""",
    unsafe_allow_html=True,
)

uploaded = st.file_uploader("📄 Faça upload do relatório de Contagem de Tempo (PDF – PMMG)", type=["pdf"])

if not uploaded:
    st.info("👆 Faça upload do relatório PDF de Contagem de Tempo para calcular os direitos.")
    st.markdown(
        """
| Direito | Quem tem direito | Critério usado no app |
|---|---|---|
| Quinquênio | Ingressos até 14/07/2003 | 5 anos de serviço = 1.825 dias |
| ADE | Regime pós-EC 57/2003 ou optantes | Marcos anuais por ADIs |
| Adicional Trintenário | Conforme a regra aplicável | 30 anos de serviço = 10.950 dias |
| Abono / Reserva | Conforme a regra aplicável | 35 anos total + 30 anos de efetivo |

> O PDF do SIRH é a entrada. A metodologia de cálculo foi alinhada para reproduzir a contagem manual oficial, inclusive no tratamento dos marcos em dias e no cuidado com datas em anos bissextos.
"""
    )
    st.stop()


data = parse_pdf(uploaded)
if data is None:
    st.stop()

rights = compute_rights(data)
ref = data["data_referencia"]
ingresso = data["ingresso_estimado"]
pos_ec57 = ingresso > EC57_CORTE

st.markdown(
    f"""
<div class="militar-card">
    <h3>👤 {data['nome']}</h3>
    <div class="info-row">
        <div class="info-item">Posto/Grad.: <span>{data['posto']}</span></div>
        <div class="info-item">N.º PM: <span>{data['numero_pm']}</span></div>
        <div class="info-item">Quadro: <span>{data['quadro']}</span></div>
        <div class="info-item">Unidade: <span>{data['unidade']}</span></div>
        <div class="info-item">Data-base: <span>{fmt_date(ref)}</span></div>
        <div class="info-item">Ingresso estimado: <span>{fmt_date(ingresso)}</span></div>
    </div>
</div>
""",
    unsafe_allow_html=True,
)

if pos_ec57:
    st.markdown(
        """
<div class="warn-box blue">
    📋 <strong>Regime predominante: ADE.</strong> O militar ficou enquadrado, pela data estimada de ingresso,
    no regime posterior à EC 57/2003. Por isso, a seção de quinquênio é apenas informativa.
</div>
""",
        unsafe_allow_html=True,
    )
else:
    st.markdown(
        """
<div class="warn-box green">
    📋 <strong>Regime predominante: quinquênio.</strong> Pela data estimada de ingresso, o militar se enquadra
    no regime anterior à EC 57/2003. O ADE continua exibido porque pode existir opção em alguns casos.
</div>
""",
        unsafe_allow_html=True,
    )

st.markdown('<div class="section-title">📊 Resumo do Tempo de Serviço</div>', unsafe_allow_html=True)

st.markdown(
    f"""
<div class="time-table">
    <div class="time-row">
        <span class="t-label">Efetivo Serviço na PMMG</span>
        <span class="t-value">{data['efetivo_anos']} anos e {data['efetivo_dias']} dias</span>
    </div>
    <div class="time-row">
        <span class="t-label">Acréscimos legais (SIRH)</span>
        <span class="t-value">{data['acrescimo_anos']} anos e {data['acrescimo_dias']} dias</span>
    </div>
    <div class="time-row">
        <span class="t-label">Total de anos de serviço (base dos cálculos)</span>
        <span class="t-value">{data['total_anos']} anos e {data['total_dias']} dias</span>
    </div>
    <div class="time-row">
        <span class="t-label">Férias anuais em dobro (informativo)</span>
        <span class="t-value">{fmt_anos_dias(data['ferias_anuais_dobro'])}</span>
    </div>
    <div class="time-row">
        <span class="t-label">Férias-prêmio em dobro (informativo)</span>
        <span class="t-value">{fmt_anos_dias(data['ferias_premio_dobro'])}</span>
    </div>
    <div class="time-row">
        <span class="t-label">Arredondamento (informativo)</span>
        <span class="t-value">{fmt_anos_dias(data['arredondamento_dias'])}</span>
    </div>
    <div class="time-row">
        <span class="t-label">Férias anuais não gozadas listadas no PDF</span>
        <span class="t-value">{data['ferias_anuais_nao_gozadas_simples']} dias simples</span>
    </div>
</div>
""",
    unsafe_allow_html=True,
)

st.markdown(
    """
<div class="warn-box orange">
    ⚠️ <strong>Ponto metodológico adotado:</strong> o app usa como base principal o <strong>Total de anos de serviço</strong>
    já consolidado no SIRH para os marcos de quinquênio e trintenário. As férias anuais não gozadas são mostradas
    apenas de forma informativa e <strong>não são subtraídas automaticamente</strong>.
</div>
""",
    unsafe_allow_html=True,
)

# Quinquênio
st.markdown(
    '<div class="section-title">📅 Quinquênios <small style="font-weight:400;font-size:0.8rem">(art. 63)</small></div>',
    unsafe_allow_html=True,
)
quins = [r for r in rights if r["group"] == "quinquenio"]
for r in quins:
    st.markdown(card(r["title"], r["sub"], r["badge"], r["kind"]), unsafe_allow_html=True)

# ADE
st.markdown(
    '<div class="section-title">📈 ADE <small style="font-weight:400;font-size:0.8rem">(arts. 59-A a 59-C)</small></div>',
    unsafe_allow_html=True,
)
st.markdown(
    """
<div class="warn-box blue">
    ℹ️ Para o ADE, o app projeta os marcos anuais em <strong>calendário civil</strong>, com tratamento explícito para anos bissextos.
    A data exibida é o marco temporal; a concessão depende também das ADIs satisfatórias.
</div>
""",
    unsafe_allow_html=True,
)
for r in [x for x in rights if x["group"] == "ade"]:
    st.markdown(card(r["title"], r["sub"], r["badge"], r["kind"]), unsafe_allow_html=True)

# Trintenário
st.markdown(
    '<div class="section-title">🏅 Adicional Trintenário <small style="font-weight:400;font-size:0.8rem">(art. 64)</small></div>',
    unsafe_allow_html=True,
)
for r in [x for x in rights if x["group"] == "trintenario"]:
    st.markdown(card(r["title"], r["sub"], r["badge"], r["kind"]), unsafe_allow_html=True)

# Abono
st.markdown(
    '<div class="section-title">💰 Abono de Permanência <small style="font-weight:400;font-size:0.8rem">(art. 204 §2º / art. 220)</small></div>',
    unsafe_allow_html=True,
)
for r in [x for x in rights if x["group"] == "abono"]:
    st.markdown(card(r["title"], r["sub"], r["badge"], r["kind"]), unsafe_allow_html=True)

# Reserva
st.markdown(
    '<div class="section-title">🎖️ Transferência Voluntária à Reserva <small style="font-weight:400;font-size:0.8rem">(art. 136, II)</small></div>',
    unsafe_allow_html=True,
)
for r in [x for x in rights if x["group"] == "reserva"]:
    st.markdown(card(r["title"], r["sub"], r["badge"], r["kind"]), unsafe_allow_html=True)

st.markdown(
    """
<div class="disclaimer">
    ⚠️ <strong>Aviso:</strong> esta versão foi corrigida para eliminar o principal desvio do script anterior:
    a subtração automática de férias anuais não gozadas e a mistura indevida entre marcos jurídicos em dias
    e projeções civis sem tratamento claro de anos bissextos. Ainda assim, casos concretos podem exigir ajuste
    fino conforme a metodologia interna oficialmente adotada pela DAL/PMMG.
</div>
""",
    unsafe_allow_html=True,
)
