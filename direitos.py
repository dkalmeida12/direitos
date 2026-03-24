import streamlit as st
import pdfplumber
import re
from datetime import date, timedelta
import io

st.set_page_config(page_title="Calculadora de Direitos – PMMG", page_icon="🪖", layout="centered")

st.markdown("""
<style>
    .block-container { padding-top: 2rem; }
    .header-banner {
        background: linear-gradient(135deg, #1a1a2e 0%, #0f3460 100%);
        color: white; padding: 1.5rem 2rem; border-radius: 12px; margin-bottom: 1.5rem;
    }
    .header-banner h1 { margin: 0; font-size: 1.6rem; }
    .header-banner p  { margin: 0.3rem 0 0; font-size: 0.9rem; opacity: 0.8; }
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
        border-bottom: 1px solid #f0f0f0; font-size: 0.87rem;
    }
    .time-row:last-child { border-bottom: none; }
    .t-label { color: #555; }
    .t-value { font-weight: 600; color: #1a1a2e; }
    .warn-box {
        border-radius: 6px; padding: 0.75rem 1rem;
        font-size: 0.82rem; margin-bottom: 0.8rem;
    }
    .warn-box.orange { background: #fff3e0; border-left: 4px solid #e65100; color: #4e342e; }
    .warn-box.blue   { background: #e8eaf6; border-left: 4px solid #3949ab; color: #1a237e; }
    .disclaimer {
        background: #fff8e1; border-left: 4px solid #f9a825; border-radius: 6px;
        padding: 0.8rem 1rem; font-size: 0.81rem; color: #5d4037; margin-top: 1.5rem;
    }
</style>
""", unsafe_allow_html=True)

# ─── EC 57/2003 corte ─────────────────────────────────────────────────────────
EC57_CORTE = date(2003, 7, 15)   # publicação EC 57, de 15/07/2003


# ─── helpers ──────────────────────────────────────────────────────────────────

def parse_anos_dias(keyword: str, text: str) -> tuple[int, int]:
    for line in text.split("\n"):
        if keyword.upper() in line.upper():
            m = re.search(r":\s*(\d+)\s+(\d+)\s*$", line)
            if m:
                return int(m.group(1)), int(m.group(2))
    return 0, 0


def parse_nao_gozadas_dias(text: str) -> int:
    """
    Extrai o total de dias de FÉRIAS ANUAIS NÃO GOZADAS listadas no PDF.
    Essas férias ainda podem ser usufruídas → não devem entrar no cálculo.
    Procura a seção 'FÉRIAS ANUAIS – NÃO GOZADAS' e soma os dias listados.
    """
    # Localiza o bloco entre NÃO GOZADAS e a próxima seção
    m = re.search(
        r"FÉRIAS ANUAIS\s*[–-]\s*NÃO GOZADAS.*?(?=RESUMO|FÉRIAS\s+PRÊMIO\s+NÃO|$)",
        text, re.IGNORECASE | re.DOTALL
    )
    if not m:
        return 0
    bloco = m.group(0)
    # Cada linha de dado tem: ANO  NUMERO_DE_DIAS  Dobro
    total = 0
    for dias in re.findall(r"^\d{4}\s+(\d+)\s+Dobro", bloco, re.MULTILINE | re.IGNORECASE):
        total += int(dias)
    return total


def parse_pdf(f) -> dict | None:
    try:
        with pdfplumber.open(io.BytesIO(f.read())) as pdf:
            text = "\n".join(p.extract_text() or "" for p in pdf.pages)
    except Exception as e:
        st.error(f"Erro ao ler o PDF: {e}")
        return None

    if "CONTAGEM DE TEMPO" not in text.upper():
        st.error("O arquivo não parece ser um relatório de Contagem de Tempo da PMMG.")
        return None

    data: dict = {}

    m = re.search(r"NOME:\s*(.+)", text, re.IGNORECASE)
    data["nome"] = m.group(1).strip() if m else "Não identificado"

    m = re.search(r"POSTO\s+OU\s+GRADUA[ÇC][ÃA]O:\s*(.+?)\s+N[ÚU]MERO\s+PM", text, re.IGNORECASE)
    data["posto"] = m.group(1).strip() if m else "—"

    m = re.search(r"N[ÚU]MERO\s+PM:\s*([\d.\-]+)", text, re.IGNORECASE)
    data["numero_pm"] = m.group(1).strip() if m else "—"

    m = re.search(r"PERTENCE\s+AO\s+QUADRO:\s*(\S+)", text, re.IGNORECASE)
    data["quadro"] = m.group(1).strip() if m else "—"

    m = re.search(r"UNIDADE:\s*(.+)", text, re.IGNORECASE)
    data["unidade"] = m.group(1).strip() if m else "—"

    # Data de referência do relatório
    m = re.search(r"DATA DE (\d{2}/\d{2}/\d{4})", text, re.IGNORECASE)
    if m:
        try:
            d, mo, y = m.group(1).split("/")
            data["data_referencia"] = date(int(y), int(mo), int(d))
        except Exception:
            data["data_referencia"] = date.today()
    else:
        data["data_referencia"] = date.today()

    # Tempos
    ef_a,  ef_d  = parse_anos_dias("TOTAL DO TEMPO DE EFETIVO SERVI", text)
    ac_a,  ac_d  = parse_anos_dias("TOTAL DE ACR", text)
    tot_a, tot_d = parse_anos_dias("TOTAL DE ANOS DE SERVI", text)

    # Férias anuais NÃO GOZADAS (ainda podem ser usufruídas → excluir do cálculo)
    nao_gozadas_simples = parse_nao_gozadas_dias(text)

    # O SIRH conta as não-gozadas em dobro no total → subtraímos o dobro delas
    # para obter o total que reflete apenas direitos já cristalizados
    nao_gozadas_dobro = nao_gozadas_simples * 2
    total_corrigido   = (tot_a * 365 + tot_d) - nao_gozadas_dobro

    # Data de ingresso: ref - efetivo serviço
    ref = data["data_referencia"]
    ef_total_dias = ef_a * 365 + ef_d
    data["ingresso_estimado"] = ref - timedelta(days=ef_total_dias)

    data.update({
        "efetivo_anos":         ef_a,
        "efetivo_dias":         ef_d,
        "acrescimo_anos":       ac_a,
        "acrescimo_dias":       ac_d,
        "total_anos":           tot_a,
        "total_dias":           tot_d,
        "nao_gozadas_simples":  nao_gozadas_simples,
        "nao_gozadas_dobro":    nao_gozadas_dobro,
        "total_corrigido":      total_corrigido,   # base de cálculo para quinquênio/trintenário
    })
    return data


def td(anos, dias): return anos * 365 + dias
def add_days(ref, n): return ref + timedelta(days=n)

def fmt_date(d: date) -> str:
    months = ["janeiro","fevereiro","março","abril","maio","junho",
              "julho","agosto","setembro","outubro","novembro","dezembro"]
    return f"{d.day} de {months[d.month-1]} de {d.year}"

def days_label(n: int) -> str:
    a, d = abs(n) // 365, abs(n) % 365
    return f"{a}a {d}d" if a else f"{abs(n)}d"

def kind(target: date, ref: date) -> str:
    if target <= ref: return "acquired"
    return "future" if (target - ref).days <= 1825 else "far"

def card(title, sub, badge, k):
    return (f'<div class="right-card {k}">'
            f'<div class="rc-title">{title}</div>'
            f'<div class="rc-date">{sub}</div>'
            f'<span class="rc-badge badge-{k}">{badge}</span></div>')


# ─── calculation ──────────────────────────────────────────────────────────────

def compute_rights(data: dict) -> list[dict]:
    ref      = data["data_referencia"]
    tot      = data["total_corrigido"]   # ← já sem férias não-gozadas
    ef       = td(data["efetivo_anos"], data["efetivo_dias"])
    ingresso = data["ingresso_estimado"]
    out      = []

    # ── Quinquênios (art. 63)
    # Só se aplica a militares ingressos ATÉ 14/07/2003 (antes da EC 57/2003)
    # Militares pós-EC 57 fazem jus ao ADE, não ao quinquênio
    direito_quiq = ingresso <= EC57_CORTE

    if direito_quiq:
        future_count = 0
        for q in range(1, 20):
            miss   = q * 5 * 365 - tot
            target = add_days(ref, miss)
            k      = kind(target, ref)
            if miss <= 0:
                sub   = f"Adquirido em {fmt_date(target)}"
                badge = "✅ Já adquirido"
            else:
                sub   = f"Previsão: {fmt_date(target)}  (faltam {days_label(miss)})"
                badge = f"⏳ {days_label(miss)}"
                future_count += 1
            out.append(dict(
                title  = f"{q}º Quinquênio — +10% sobre remuneração base",
                sub    = sub, badge = badge, kind = k,
                target = target, group = "quinquenio", order = q,
            ))
            if future_count >= 3:
                break
    else:
        # Militar pós-EC 57 → não tem quinquênio
        out.append(dict(
            title  = "Quinquênio — não aplicável",
            sub    = (f"Militar ingressou após 15/07/2003 (EC 57/2003). "
                      f"Faz jus ao <strong>ADE</strong> (Adicional de Desempenho) no lugar do quinquênio."),
            badge  = "ℹ️ Ver seção ADE abaixo",
            kind   = "far",
            target = ref,
            group  = "quinquenio",
            order  = 0,
        ))

    # ── ADE (arts. 59-A a 59-C)
    # Militares pós-EC 57 têm ADE obrigatório.
    # Militares pré-EC 57 podem OPTAR pelo ADE (art. 59-A, caput).
    # Marcos: número de ADIs satisfatórias (≥ 70%) a partir do ingresso (ou da opção).
    marcos_ade = [
        (3,  "6%",  "até 6% (3 ADIs)"),
        (5,  "10%", "até 10% (5 ADIs)"),
        (10, "20%", "até 20% (10 ADIs)"),
        (15, "30%", "até 30% (15 ADIs)"),
        (20, "40%", "até 40% (20 ADIs)"),
        (25, "50%", "até 50% (25 ADIs)"),
        (30, "60%", "até 60% na ativa / até 70% na inatividade (30 ADIs)"),
    ]
    for adis, pct_curto, pct_label in marcos_ade:
        target = add_days(ingresso, adis * 365)
        miss   = (target - ref).days
        k      = kind(target, ref)
        if miss <= 0:
            sub   = (f"Marco temporal atingido em {fmt_date(target)}<br>"
                     f"<em>Requer {adis} ADIs com resultado ≥ 70%</em>")
            badge = "✅ Marco temporal atingido"
        else:
            sub   = (f"Previsão: {fmt_date(target)}  (faltam {days_label(miss)})<br>"
                     f"<em>Requer {adis} ADIs com resultado ≥ 70%</em>")
            badge = f"⏳ {days_label(miss)}"
        out.append(dict(
            title  = f"ADE — {pct_label}",
            sub    = sub, badge = badge, kind = k,
            target = target, group = "ade", order = adis,
        ))

    # ── Adicional Trintenário (art. 64) – 30 anos de serviço (total corrigido)
    miss30  = 30 * 365 - tot
    t30     = add_days(ref, miss30)
    k30     = kind(t30, ref)
    if miss30 <= 0:
        sub30, badge30 = f"Adquirido em {fmt_date(t30)}", "✅ Já adquirido"
    else:
        sub30  = f"Previsão: {fmt_date(t30)}  (faltam {days_label(miss30)})"
        badge30 = f"⏳ {days_label(miss30)}"
    out.append(dict(
        title  = "Adicional Trintenário — +10% sobre remuneração base",
        sub    = sub30, badge = badge30, kind = k30,
        target = t30, group = "trintenario", order = 0,
    ))

    # ── Abono de Permanência / Reserva Voluntária (art. 136 II / art. 204 §2º)
    # Requisito: 35 anos de serviço (total corrigido) E 30 anos de efetivo exercício
    miss35    = 35 * 365 - tot
    miss_ef30 = 30 * 365 - ef
    days_ab   = max(miss35, miss_ef30, 0)
    tab       = add_days(ref, days_ab)
    kab       = kind(tab, ref)
    limiting  = ("35 anos de serviço total" if miss35 >= miss_ef30
                 else "30 anos de efetivo exercício militar")
    if days_ab == 0 and miss35 <= 0 and miss_ef30 <= 0:
        sub_ab   = f"Adquirido em {fmt_date(tab)}"
        badge_ab = "✅ Já adquirido"
    else:
        sub_ab   = (f"Previsão: {fmt_date(tab)}  (faltam {days_label(days_ab)})<br>"
                    f"<em>Fator limitante: {limiting}</em>")
        badge_ab = f"⏳ {days_label(days_ab)}"

    for grp in ("abono", "reserva"):
        title = ("Abono de Permanência — 1/3 dos vencimentos" if grp == "abono"
                 else "Elegibilidade para Transferência Voluntária à Reserva")
        out.append(dict(title=title, sub=sub_ab, badge=badge_ab, kind=kab,
                        target=tab, group=grp, order=0))
    return out


# ─── UI ───────────────────────────────────────────────────────────────────────

st.markdown("""
<div class="header-banner">
    <h1>🪖 Calculadora de Direitos – PMMG</h1>
    <p>Quinquênio · ADE · Adicional Trintenário · Abono de Permanência · Reserva Voluntária</p>
    <p style="opacity:0.55;font-size:0.77rem">Base legal: Lei n.º 5.301/1969 e atualizações (até LC 168/2022) · EC 57/2003</p>
</div>
""", unsafe_allow_html=True)

uploaded = st.file_uploader("📄 Faça upload do relatório de Contagem de Tempo (PDF – PMMG)", type=["pdf"])

if not uploaded:
    st.info("👆 Faça upload do relatório PDF de Contagem de Tempo para calcular seus direitos.")
    st.markdown("""
| Direito | Art. | Quem tem direito | Critério |
|---|---|---|---|
| Quinquênios | 63 | Ingressos **até 14/07/2003** | +10% a cada 5 **anos de serviço** |
| ADE | 59-A a 59-C | Ingressos **após EC 57/2003** (ou optantes) | % crescente por ADIs ≥ 70%, de 6% a 60% na ativa |
| Adicional Trintenário | 64 | Todos | +10% com 30 **anos de serviço** |
| Abono de Permanência | 204 §2º / 220 §único | Todos | 1/3 dos vencimentos ao atingir requisitos para reserva voluntária |
| Reserva Voluntária | 136, II | Todos | 35 anos de serviço **e** 30 anos de atividade militar |

> ⚠️ **Férias anuais não gozadas** listadas no relatório são excluídas do cálculo pois ainda podem ser usufruídas pelo militar.
""")
    st.stop()

data = parse_pdf(uploaded)
if data is None:
    st.stop()

ref      = data["data_referencia"]
ingresso = data["ingresso_estimado"]
pos_ec57 = ingresso > EC57_CORTE

st.markdown(f"""
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
""", unsafe_allow_html=True)

# Aviso sobre regime (quinquênio vs ADE)
if pos_ec57:
    st.markdown("""
<div class="warn-box blue">
    📋 <strong>Regime ADE:</strong> Militar ingressou após a EC 57/2003 — faz jus ao
    <strong>ADE (Adicional de Desempenho)</strong> no lugar do quinquênio (art. 59-A, Lei 5.301/69).
</div>
""", unsafe_allow_html=True)
else:
    st.markdown("""
<div class="warn-box blue">
    📋 <strong>Regime Quinquênio:</strong> Militar ingressou antes da EC 57/2003 — faz jus aos
    <strong>quinquênios</strong>. Pode optar pelo ADE (art. 59-A, §2º), caso ainda não o tenha feito.
</div>
""", unsafe_allow_html=True)

# Resumo do tempo
st.markdown('<div class="section-title">📊 Resumo do Tempo de Serviço</div>', unsafe_allow_html=True)

aviso_ng = ""
if data["nao_gozadas_simples"] > 0:
    aviso_ng = (f'<div class="time-row" style="color:#e65100">'
                f'<span class="t-label">⚠️ Férias anuais não gozadas (excluídas do cálculo)</span>'
                f'<span class="t-value">−{data["nao_gozadas_dobro"]} dias (dobro de {data["nao_gozadas_simples"]}d)</span></div>')

st.markdown(f"""
<div class="time-table">
    <div class="time-row">
        <span class="t-label">Efetivo Serviço na PMMG</span>
        <span class="t-value">{data['efetivo_anos']} anos e {data['efetivo_dias']} dias</span>
    </div>
    <div class="time-row">
        <span class="t-label">Acréscimos Legais (conforme SIRH)</span>
        <span class="t-value">{data['acrescimo_anos']} anos e {data['acrescimo_dias']} dias</span>
    </div>
    <div class="time-row">
        <span class="t-label">Total de Anos de Serviço (SIRH)</span>
        <span class="t-value">{data['total_anos']} anos e {data['total_dias']} dias</span>
    </div>
    {aviso_ng}
    <div class="time-row" style="background:#f0f4ff;border-radius:4px;padding:0.4rem 0.2rem">
        <span class="t-label"><strong>Total corrigido (base dos cálculos)</strong></span>
        <span class="t-value"><strong>{data['total_corrigido']//365} anos e {data['total_corrigido']%365} dias</strong></span>
    </div>
</div>
""", unsafe_allow_html=True)

rights = compute_rights(data)

# ── Quinquênios ────────────────────────────────────────────────────────────────
st.markdown(
    '<div class="section-title">📅 Quinquênios &nbsp;'
    '<small style="font-weight:400;font-size:0.8rem">(art. 63 – Lei 5.301/69 · ingressos até 14/07/2003)</small></div>',
    unsafe_allow_html=True
)
quins = [r for r in rights if r["group"] == "quinquenio"]
if not pos_ec57:
    acq_q = [r for r in quins if r["kind"] == "acquired"]
    fut_q = [r for r in quins if r["kind"] != "acquired"]
    label = (f"✅ {len(acq_q)} adquirido(s)" if acq_q else "") + \
            (f"   ⏳ próximos {len(fut_q)}" if fut_q else "")
    with st.expander(label, expanded=True):
        for r in acq_q + fut_q:
            st.markdown(card(r["title"], r["sub"], r["badge"], r["kind"]), unsafe_allow_html=True)
else:
    for r in quins:
        st.markdown(card(r["title"], r["sub"], r["badge"], r["kind"]), unsafe_allow_html=True)

# ── ADE ────────────────────────────────────────────────────────────────────────
st.markdown(
    '<div class="section-title">📈 ADE – Adicional de Desempenho &nbsp;'
    '<small style="font-weight:400;font-size:0.8rem">(arts. 59-A a 59-C – Lei 5.301/69)</small></div>',
    unsafe_allow_html=True
)
st.markdown("""
<div class="warn-box orange">
    ⚠️ <strong>Atenção:</strong> As datas indicam quando o militar atinge o <strong>marco temporal</strong>
    de cada nível. O percentual só é concedido se o número de <strong>ADIs com resultado ≥ 70%</strong>
    também for cumprido. Militares pré-EC 57/2003 precisam ter feito a <strong>opção pelo ADE</strong>
    (art. 59-A). O somatório de quinquênios + ADE não pode exceder 90% da remuneração base (art. 59-A, §5º).
</div>
""", unsafe_allow_html=True)
ades  = [r for r in rights if r["group"] == "ade"]
acq_a = [r for r in ades if r["kind"] == "acquired"]
fut_a = [r for r in ades if r["kind"] != "acquired"]
label_a = (f"✅ {len(acq_a)} marco(s) atingido(s)" if acq_a else "") + \
          (f"   ⏳ próximos {len(fut_a)}" if fut_a else "")
with st.expander(label_a, expanded=True):
    for r in acq_a + fut_a:
        st.markdown(card(r["title"], r["sub"], r["badge"], r["kind"]), unsafe_allow_html=True)

# ── Trintenário ────────────────────────────────────────────────────────────────
st.markdown(
    '<div class="section-title">🏅 Adicional Trintenário &nbsp;'
    '<small style="font-weight:400;font-size:0.8rem">(art. 64 – Lei 5.301/69)</small></div>',
    unsafe_allow_html=True
)
for r in rights:
    if r["group"] == "trintenario":
        st.markdown(card(r["title"], r["sub"], r["badge"], r["kind"]), unsafe_allow_html=True)

# ── Abono de Permanência ───────────────────────────────────────────────────────
st.markdown(
    '<div class="section-title">💰 Abono de Permanência &nbsp;'
    '<small style="font-weight:400;font-size:0.8rem">(art. 204 §2º / art. 220 §único)</small></div>',
    unsafe_allow_html=True
)
for r in rights:
    if r["group"] == "abono":
        st.markdown(card(r["title"], r["sub"], r["badge"], r["kind"]), unsafe_allow_html=True)

# ── Reserva Voluntária ─────────────────────────────────────────────────────────
st.markdown(
    '<div class="section-title">🎖️ Transferência Voluntária à Reserva &nbsp;'
    '<small style="font-weight:400;font-size:0.8rem">(art. 136, II – Lei 5.301/69)</small></div>',
    unsafe_allow_html=True
)
for r in rights:
    if r["group"] == "reserva":
        st.markdown(card(r["title"], r["sub"], r["badge"], r["kind"]), unsafe_allow_html=True)

# ── Disclaimer ─────────────────────────────────────────────────────────────────
st.markdown("""
<div class="disclaimer">
    ⚠️ <strong>Aviso Legal:</strong> Estimativas baseadas nos dados do relatório e na Lei n.º 5.301/1969
    (atualizada até LC 168/2022). Não substituem análise oficial da DAL/PMMG. Afastamentos, licenças,
    processos administrativos e outros fatores individuais podem alterar as datas calculadas.
    A data de ingresso é <em>estimada</em> a partir do tempo de efetivo serviço — pequenas variações
    (±dias) em relação ao ingresso real podem ocorrer.
</div>
""", unsafe_allow_html=True)
