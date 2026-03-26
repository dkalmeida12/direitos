"""
Calculadora de Direitos – PMMG
Versão corrigida com:
  1. Tempo averbado para quinquênio (somente serviço público anterior a 2002)
  2. Férias-prêmio contadas sempre somadas (em dobro)
  3. Férias-prêmio não gozadas: pergunta ao usuário
  4. Férias anuais vantagem: sempre em dobro
  5. Férias anuais não gozadas: pergunta ao usuário
  6. Checagem da tabela Resumo do SIRH
  7. Data do benefício pelo total de anos de serviço
  8. Prospecção futura de férias-prêmio e quinquênios
"""

import re
import zipfile
import io
import json
from datetime import date, timedelta

import streamlit as st

# ─── Constantes ───────────────────────────────────────────────────────────────
EC57_CORTE = date(2003, 7, 15)
ANO_CORTE_SPUB = 2002          # Serviço público averbado só conta se anterior a 2002


# ─── helpers de data / tempo ──────────────────────────────────────────────────

def fmt_date(d: date) -> str:
    meses = ["janeiro","fevereiro","março","abril","maio","junho",
             "julho","agosto","setembro","outubro","novembro","dezembro"]
    return f"{d.day} de {meses[d.month-1]} de {d.year}"


def days_label(n: int) -> str:
    n = abs(n)
    a, d = divmod(n, 365)
    return f"{a}a {d}d" if a else f"{d}d"


def add_days(ref: date, n: int) -> date:
    return ref + timedelta(days=n)


def kind(target: date, ref: date) -> str:
    if target <= ref:
        return "acquired"
    return "future" if (target - ref).days <= 1825 else "far"


def card(title: str, sub: str, badge: str, k: str) -> str:
    return (f'<div class="right-card {k}">'
            f'<div class="rc-title">{title}</div>'
            f'<div class="rc-date">{sub}</div>'
            f'<span class="rc-badge badge-{k}">{badge}</span></div>')


# ─── Leitura do PDF (formato ZIP do SIRH) ─────────────────────────────────────

def read_sirh_zip(uploaded_file) -> str | None:
    """
    Lê o relatório SIRH/PMMG em dois formatos possíveis:
      1. PDF real (formato atual do SIRH) — usa pdfplumber
      2. ZIP disfarçado de .pdf (formato antigo) — extrai os .txt internos

    Retorna o texto concatenado de todas as páginas, ou None em caso de erro.
    """
    import pdfplumber

    raw = uploaded_file.read()

    # ── Tenta PDF real primeiro (verifica assinatura %PDF)
    if raw[:4] == b"%PDF":
        try:
            parts = []
            with pdfplumber.open(io.BytesIO(raw)) as pdf:
                for page in pdf.pages:
                    txt = page.extract_text() or ""
                    parts.append(txt)
            return "\n".join(parts)
        except Exception as e:
            st.error(f"Erro ao ler o PDF: {e}")
            return None

    # ── Tenta formato ZIP (assinatura PK — formato antigo do SIRH)
    if raw[:2] == b"PK":
        try:
            with zipfile.ZipFile(io.BytesIO(raw)) as zf:
                names = zf.namelist()
                manifest_names = [n for n in names if n.endswith("manifest.json")]
                txt_names_ordered = []
                if manifest_names:
                    manifest = json.loads(zf.read(manifest_names[0]))
                    for pg in sorted(manifest.get("pages", []), key=lambda p: p["page_number"]):
                        txt_path = pg.get("text", {}).get("path", "")
                        if txt_path and txt_path in names:
                            txt_names_ordered.append(txt_path)
                if not txt_names_ordered:
                    txt_names_ordered = sorted([n for n in names if n.endswith(".txt")])
                parts = []
                for name in txt_names_ordered:
                    parts.append(zf.read(name).decode("utf-8", errors="replace"))
                return "\n".join(parts)
        except Exception as e:
            st.error(f"Erro ao ler o arquivo ZIP interno: {e}")
            return None

    st.error("Formato de arquivo não reconhecido. Envie o PDF de Contagem de Tempo gerado pelo SIRH/PMMG.")
    return None


def normalize(text: str) -> str:
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = re.sub(r"[\t\xa0]+", " ", text)
    text = re.sub(r" +", " ", text)
    return text


# ─── Parsing do texto extraído ────────────────────────────────────────────────

def parse_anos_dias(label_regex: str, text: str):
    """Localiza 'label ... ANO  DIAS' e retorna (anos, dias)."""
    patterns = [
        rf"{label_regex}\s*:?\s*(\d+)\s+(\d+)",
        rf"{label_regex}.*?\n\s*(\d+)\s+(\d+)",
    ]
    for pat in patterns:
        m = re.search(pat, text, re.IGNORECASE | re.DOTALL)
        if m:
            return int(m.group(1)), int(m.group(2))
    return 0, 0


def section_between(text: str, start_pat: str, end_pat: str) -> str:
    m = re.search(rf"{start_pat}(.*?){end_pat}", text, re.IGNORECASE | re.DOTALL)
    return m.group(1) if m else ""


def sum_dobro_lines(block: str, bonus_cada_5: bool = False) -> int:
    """Soma o número de dias de todas as linhas que terminam com 'Dobro'.
    O último número em cada linha é sempre a quantidade de dias —
    seja para FP ('1 90 Dobro'), FP_NG ('5 60 Dobro') ou
    FA_NG ('2020 5 Dobro', '2024 13 Dobro').

    bonus_cada_5 (bool): quando True, aplica a regra de férias anuais não gozadas:
      a cada 5 dias de férias utilizados para vantagem, o servidor recebe +1 dia extra
      (calculado por linha/ano, antes do dobro).
      Ex.: 5d → 5 + 5//5 = 6d; 13d → 13 + 13//5 = 15d; 4d → 4 + 4//5 = 4d.
    """
    total = 0
    for line in block.splitlines():
        if re.search(r"\bDobro\b", line, re.IGNORECASE):
            nums = re.findall(r"\b(\d+)\b", line)
            if nums:
                dias = int(nums[-1])
                if bonus_cada_5:
                    dias = dias + dias // 5   # +1 dia a cada 5 dias de férias
                total += dias
    return total


def parse_tempo_averbado(text: str):
    """
    Extrai o bloco TEMPO AVERBADO e retorna lista de dicts:
      {'tipo', 'contar_vantagem', 'periodo', 'num_dias', 'tempo_servico'}
    """
    bloco = section_between(
        text,
        r"TEMPO\s+AVERBADO",
        r"FÉ?RIAS\s+PR[ÊE]MIO\s*[-–]\s*CONTADAS|FÉ?RIAS\s+ANUAIS",
    )
    items = []
    for line in bloco.splitlines():
        line = line.strip()
        if not line:
            continue
        # Cada linha tem: TIPO | CONTAR_VANTAGEM | PERIODO | NUM_DIAS | TEMPO_SERVICO
        parts = re.split(r"\s{2,}|\t", line)
        if len(parts) >= 4:
            try:
                num_dias = int(re.search(r"\d+", parts[-2]).group())
            except Exception:
                num_dias = 0
            # tenta extrair o período (ano inicial)
            ano_m = re.search(r"\b(\d{4})\b", " ".join(parts[:3]))
            periodo = int(ano_m.group(1)) if ano_m else None
            items.append({
                "tipo": parts[0],
                "contar_vantagem": "sim" in parts[1].lower() if len(parts) > 1 else False,
                "periodo": periodo,
                "num_dias": num_dias,
                "tempo_servico": parts[-1].strip().lower(),
            })
    return items


def parse_pdf(text: str) -> dict | None:
    if "CONTAGEM DE TEMPO" not in text.upper():
        st.error("O arquivo não parece ser um relatório de Contagem de Tempo da PMMG.")
        return None

    data: dict = {}

    # ── identificação
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

    # ── data de referência
    ref_m = re.search(r"AT[ÉE]\s+A\s+DATA\s+DE\s+(\d{2}/\d{2}/\d{4})", text, re.IGNORECASE)
    if not ref_m:
        ref_m = re.search(r"DATA\s+DE\s+(\d{2}/\d{2}/\d{4})", text, re.IGNORECASE)
    if ref_m:
        d, mo, y = ref_m.group(1).split("/")
        data["data_referencia"] = date(int(y), int(mo), int(d))
    else:
        data["data_referencia"] = date.today()

    # ── tempos do resumo SIRH
    # "Tempo de Efetivo Serviço na PMMG" = BRUTO (antes de deduzir licenças)
    # "TOTAL DO TEMPO DE EFETIVO SERVIÇO NA PMMG" = LÍQUIDO (bruto − deduzir)
    # O ingresso usa o BRUTO; os cálculos de benefício usam o LÍQUIDO.
    bruto_a, bruto_d = parse_anos_dias(r"Tempo de Efetivo Servi[çc]o na PMMG", text)
    ef_a,    ef_d    = parse_anos_dias(r"TOTAL DO TEMPO DE EFETIVO SERVI[ÇC]O NA PMMG", text)
    ded_a,   ded_d   = parse_anos_dias(r"Tempo a deduzir", text)
    ac_a,    ac_d    = parse_anos_dias(r"TOTAL DE ACR[ÉE]SCIMOS LEGAIS", text)
    tot_a,   tot_d   = parse_anos_dias(r"TOTAL DE ANOS DE SERVI[ÇC]O", text)
    ard_a,   ard_d   = parse_anos_dias(r"Arredondamento\s*\(at[ée]\s*182\s*dias\)", text)

    # Fallback: se bruto não foi capturado, usa o líquido + deduzir
    if bruto_a == 0 and bruto_d == 0:
        bruto_a = ef_a + ded_a
        bruto_d = ef_d + ded_d
        if bruto_d >= 365:
            bruto_a += bruto_d // 365
            bruto_d  = bruto_d  % 365

    data.update({
        "efetivo_bruto_anos": bruto_a, "efetivo_bruto_dias": bruto_d,
        "efetivo_anos": ef_a, "efetivo_dias": ef_d,
        "deduzir_anos": ded_a, "deduzir_dias": ded_d,
        "acrescimos_anos": ac_a, "acrescimos_dias": ac_d,
        "total_anos": tot_a, "total_dias": tot_d,
        "arredondamento_dias": ard_a * 365 + ard_d,
    })

    # Ingresso usa o tempo BRUTO (não deduz licenças — a data de posse é fixa)
    efetivo_bruto = bruto_a * 365 + bruto_d
    data["ingresso_estimado"] = data["data_referencia"] - timedelta(days=efetivo_bruto - 1)

    # ── Férias-prêmio contadas como tempo de serviço/vantagem (SEMPRE em dobro)
    bloco_fp_cont = section_between(
        text,
        r"FÉ?RIAS\s+PR[ÊE]MIO\s*[-–]\s*CONTADAS\s+COMO\s+TEMPO\s+DE\s+SERVI[ÇC]O",
        r"FÉ?RIAS\s+PR[ÊE]MIO\s+N[ÃA]O\s+GOZADAS",
    )
    fp_contadas_simples = sum_dobro_lines(bloco_fp_cont)
    data["fp_contadas_simples"] = fp_contadas_simples

    # ── Férias-prêmio não gozadas (pergunta ao usuário)
    bloco_fp_ng = section_between(
        text,
        r"FÉ?RIAS\s+PR[ÊE]MIO\s+N[ÃA]O\s+GOZADAS",
        r"FÉ?RIAS\s+ANUAIS\s*[-–]",
    )
    fp_ng_simples = sum_dobro_lines(bloco_fp_ng)
    data["fp_ng_simples"] = fp_ng_simples

    # ── Férias anuais vantagem (SEMPRE em dobro)
    bloco_fa_vant = section_between(
        text,
        r"FÉ?RIAS\s+ANUAIS\s*[-–]\s*VANTAGEM",
        r"FÉ?RIAS\s+ANUAIS\s*[-–]\s*N[ÃA]O\s+GOZADAS",
    )
    fa_vant_simples = sum_dobro_lines(bloco_fa_vant, bonus_cada_5=False)
    # Regra de +1/5 NÃO se aplica a férias anuais vantagem (somente às não gozadas)
    data["fa_vant_simples"]    = fa_vant_simples
    data["fa_vant_com_bonus"]  = fa_vant_simples   # sem bônus
    data["fa_vant_bonus_dias"] = 0

    # ── Férias anuais não gozadas (pergunta ao usuário)
    bloco_fa_ng = section_between(
        text,
        r"FÉ?RIAS\s+ANUAIS\s*[-–]\s*N[ÃA]O\s+GOZADAS",
        r"RESUMO\s+DO\s+TEMPO|RESUMO\s+ANOS",
    )
    # Extrai FA_NG linha a linha: {ano: dias}
    fa_ng_por_ano: dict[int, int] = {}
    for line in bloco_fa_ng.splitlines():
        if re.search(r"\bDobro\b", line, re.IGNORECASE):
            nums = re.findall(r"\b(\d+)\b", line)
            if len(nums) >= 2:
                ano_ref = int(nums[0])
                dias    = int(nums[-1])
                fa_ng_por_ano[ano_ref] = fa_ng_por_ano.get(ano_ref, 0) + dias
    data["fa_ng_por_ano"] = fa_ng_por_ano  # {ano: dias_literais}

    # Totais agregados (para compatibilidade com o resto do código)
    fa_ng_simples = sum(fa_ng_por_ano.values())
    # Bônus +1/5 por linha (antes do dobro)
    fa_ng_com_bonus = sum(d + d // 5 for d in fa_ng_por_ano.values())
    data["fa_ng_simples"]    = fa_ng_simples
    data["fa_ng_com_bonus"]  = fa_ng_com_bonus
    data["fa_ng_bonus_dias"] = fa_ng_com_bonus - fa_ng_simples

    # ── Tempo de serviço público averbado (somente pré-2002)
    # Primeiro: total bruto do SIRH
    spub_a, spub_d = parse_anos_dias(r"Tempo de servi[çc]o p[úu]blico averbado", text)
    inss_a,  inss_d  = parse_anos_dias(r"Tempo averbado vinculado ao INSS", text)
    data["spub_total_dias"] = spub_a * 365 + spub_d
    data["inss_total_dias"] = inss_a * 365 + inss_d

    # Extrai detalhes do bloco TEMPO AVERBADO para filtrar pelo período
    data["tempo_averbado_items"] = parse_tempo_averbado(text)

    return data


# ─── Construção da base de cálculo ────────────────────────────────────────────

def build_base(data: dict,
               incluir_fp_ng: bool,
               fa_ng_anos_selecionados: set[int],
               spub_pre2002_dias: int) -> dict:
    """
    Monta o total de dias que serve de base para os quinquênios / trintenário.

    Regras:
      • Efetivo serviço: sempre
      • FP contadas (vantagem): SEMPRE em dobro
      • FP não gozadas: em dobro se o usuário marcar
      • FA vantagem: SEMPRE em dobro (sem bônus +1/5)
      • FA não gozadas PRESCRITAS selecionadas pelo usuário:
          - Aplica bônus +1 a cada 5 dias (por exercício, antes do dobro)
          - Depois dobra o resultado
      • FA não gozadas DENTRO DO PRAZO: não entram (militar pode ainda usufruir)
      • Serviço público averbado: somente se período anterior a 2002
      • INSS averbado: não entra no quinquênio
      • Arredondamento: conforme SIRH (até 182 dias)
      • Tempo a deduzir: JÁ DESCONTADO pelo SIRH no campo "TOTAL DO TEMPO DE EFETIVO
        SERVIÇO NA PMMG" — NÃO subtrair novamente aqui (evita dupla dedução).
    """
    ef = data["efetivo_anos"] * 365 + data["efetivo_dias"]   # já é o líquido (SIRH descontou)
    ded = data["deduzir_anos"] * 365 + data["deduzir_dias"]  # guardado apenas para exibição

    fp_cont_dobro = data["fp_contadas_simples"] * 2
    fp_ng_dobro   = data["fp_ng_simples"] * 2 if incluir_fp_ng else 0
    fa_vant_dobro = data["fa_vant_simples"] * 2

    # FA não gozadas: calcula apenas os anos selecionados pelo usuário
    # Bônus +1/5 aplicado por exercício (antes do dobro)
    fa_ng_dobro       = 0
    fa_ng_bonus_total = 0
    fa_ng_sel_simples = 0
    for ano, dias in data["fa_ng_por_ano"].items():
        if ano in fa_ng_anos_selecionados:
            bonus     = dias // 5
            com_bonus = dias + bonus
            fa_ng_dobro       += com_bonus * 2
            fa_ng_bonus_total += bonus
            fa_ng_sel_simples += dias
    arred = data["arredondamento_dias"]

    total = (ef               # líquido — dedução já feita pelo SIRH
             + fp_cont_dobro
             + fp_ng_dobro
             + fa_vant_dobro
             + fa_ng_dobro
             + spub_pre2002_dias
             + arred)

    sirh_total = data["total_anos"] * 365 + data["total_dias"]

    return {
        "efetivo": ef,
        "deduzir": ded,
        "fp_cont_dobro": fp_cont_dobro,
        "fp_ng_dobro": fp_ng_dobro,
        "fa_vant_dobro": fa_vant_dobro,
        "fa_ng_dobro": fa_ng_dobro,
        "fa_ng_sel_simples": fa_ng_sel_simples,
        "fa_ng_bonus_total": fa_ng_bonus_total,
        "fa_ng_anos_selecionados": fa_ng_anos_selecionados,
        "spub_pre2002": spub_pre2002_dias,
        "arredondamento": arred,
        "total_calculado": total,
        "sirh_total": sirh_total,
        "diferenca": total - sirh_total,
    }


# ─── Prospecção futura de férias-prêmio ───────────────────────────────────────

def projetar_ferias_premio(data: dict, incluir_fp_ng: bool) -> list[dict]:
    """
    Projeta as férias-prêmio futuras a partir da data de ingresso estimada.
    Férias-prêmio são concedidas a cada 5 anos corridos (quinquênio de efetivo serviço).
    Cada período gera 90 dias (3 meses) de férias-prêmio.
    O número de quinquênios já concedidos é estimado pelo total de fp_contadas + fp_ng.
    """
    ingresso = data["ingresso_estimado"]
    ref = data["data_referencia"]
    ef_total = data["efetivo_anos"] * 365 + data["efetivo_dias"]

    # Quinquênios de FP já existentes no relatório
    fp_cont_simples = data["fp_contadas_simples"]
    fp_ng_simples   = data["fp_ng_simples"]
    # 1 quinquênio = 90 dias de FP (padrão); pode ser menos se parcial
    # Estimamos o nº de quinquênios já contabilizados no relatório
    qq_ja_contados = (fp_cont_simples // 90) + (1 if fp_ng_simples > 0 else 0)

    projecoes = []
    for n in range(1, 8):  # até 7 quinquênios de FP (35 anos)
        data_concessao = ingresso + timedelta(days=n * 5 * 365)
        dias_efetivo_necessario = n * 5 * 365

        if dias_efetivo_necessario <= ef_total:
            # Já adquirida — aparece no relatório
            status_rel = "contada" if n <= (fp_cont_simples // 90) else "não_gozada"
            status = "acquired"
        else:
            # Futura
            status_rel = "futura"
            miss_ef = dias_efetivo_necessario - ef_total
            status = "future" if miss_ef <= 1825 else "far"

        # Impacto no total ao converter em dobro (90d simples → +90d extra)
        impacto_dobro = 90  # dias adicionais ao incluir em dobro

        projecoes.append({
            "quinquenio": n,
            "data_concessao": data_concessao,
            "status": status,
            "status_rel": status_rel,
            "impacto_dobro": impacto_dobro,
        })
    return projecoes


# ─── Cálculo dos direitos ─────────────────────────────────────────────────────

def compute_rights(data: dict, base: dict) -> list[dict]:
    ref      = data["data_referencia"]
    tot      = base["total_calculado"]
    ef       = base["efetivo"]
    ingresso = data["ingresso_estimado"]
    out      = []

    direito_quinquenio = ingresso <= EC57_CORTE

    # ── Quinquênios (art. 63) — apenas ingressos até 14/07/2003
    if direito_quinquenio:
        future_count = 0
        for q in range(1, 20):
            marco  = q * 5 * 365
            miss   = marco - tot
            target = add_days(ref, miss)
            k      = kind(target, ref)
            if miss <= 0:
                sub   = f"Adquirido em {fmt_date(target)}"
                badge = "✅ Já adquirido"
            else:
                sub   = f"Previsão: {fmt_date(target)}  (faltam {days_label(miss)})"
                badge = f"⏳ {days_label(miss)}"
                future_count += 1
            out.append(dict(title=f"{q}º Quinquênio — +{q*5}% sobre remuneração base",
                            sub=sub, badge=badge, kind=k,
                            target=target, group="quinquenio", order=q))
            if future_count >= 3:
                break
    else:
        out.append(dict(
            title="Quinquênio — não aplicável",
            sub=(f"Militar ingressou após 15/07/2003 (EC 57/2003). "
                 f"Faz jus ao <strong>ADE</strong> (Adicional de Desempenho)."),
            badge="ℹ️ Regime ADE", kind="far",
            target=ref, group="quinquenio", order=0))

    # ── ADE (arts. 59-A a 59-C)
    for adis, pct in [(3,"6%"),(5,"10%"),(10,"20%"),(15,"30%"),(20,"40%"),(25,"50%"),(30,"60%/70%")]:
        target = add_days(ingresso, adis * 365)
        miss   = (target - ref).days
        k      = kind(target, ref)
        if miss <= 0:
            sub   = f"Marco temporal atingido em {fmt_date(target)}<br><em>Requer {adis} ADIs ≥ 70%</em>"
            badge = "✅ Marco atingido"
        else:
            sub   = f"Previsão: {fmt_date(target)}  (faltam {days_label(miss)})<br><em>Requer {adis} ADIs ≥ 70%</em>"
            badge = f"⏳ {days_label(miss)}"
        out.append(dict(title=f"ADE — {pct}", sub=sub, badge=badge, kind=k,
                        target=target, group="ade", order=adis))

    # ── Adicional Trintenário (art. 64)
    miss30 = 30 * 365 - tot
    t30    = add_days(ref, miss30)
    k30    = kind(t30, ref)
    sub30  = (f"Adquirido em {fmt_date(t30)}" if miss30 <= 0
              else f"Previsão: {fmt_date(t30)}  (faltam {days_label(miss30)})")
    badge30 = "✅ Já adquirido" if miss30 <= 0 else f"⏳ {days_label(miss30)}"
    out.append(dict(title="Adicional Trintenário — +10% sobre remuneração base",
                    sub=sub30, badge=badge30, kind=k30,
                    target=t30, group="trintenario", order=0))

    # ── Abono de Permanência / Reserva Voluntária (art. 136 II / art. 204 §2º)
    miss35    = 35 * 365 - tot
    miss_ef30 = 30 * 365 - ef
    days_ab   = max(miss35, miss_ef30, 0)
    tab       = add_days(ref, days_ab)
    kab       = kind(tab, ref)
    limiting  = ("35 anos de serviço total" if miss35 >= miss_ef30 else "30 anos de efetivo exercício")
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


# ─── CSS ──────────────────────────────────────────────────────────────────────

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
    .warn-box.green  { background: #e8f5e9; border-left: 4px solid #2e7d32; color: #1b5e20; }
    .warn-box.red    { background: #ffebee; border-left: 4px solid #c62828; color: #b71c1c; }
    .fp-proj-card {
        background: #f3e5f5; border-left: 4px solid #7b1fa2; border-radius: 8px;
        padding: 0.7rem 1rem; margin-bottom: 0.5rem; font-size: 0.86rem;
    }
    .fp-proj-card.fp-future { background: #e8eaf6; border-left-color: #3949ab; }
    .fp-proj-card.fp-far    { background: #fafafa; border-left-color: #9e9e9e; }
    .disclaimer {
        background: #fff8e1; border-left: 4px solid #f9a825; border-radius: 6px;
        padding: 0.8rem 1rem; font-size: 0.81rem; color: #5d4037; margin-top: 1.5rem;
    }
</style>
""", unsafe_allow_html=True)

# ─── Cabeçalho ────────────────────────────────────────────────────────────────

st.markdown("""
<div class="header-banner">
    <h1>🪖 Calculadora de Direitos – PMMG</h1>
    <p>Quinquênio · ADE · Adicional Trintenário · Abono de Permanência · Reserva Voluntária</p>
    <p style="opacity:0.55;font-size:0.77rem">
        Base legal: Lei n.º 5.301/1969 e atualizações (até LC 168/2022) · EC 57/2003
    </p>
</div>
""", unsafe_allow_html=True)

uploaded = st.file_uploader(
    "📄 Faça upload do relatório de Contagem de Tempo (PDF – PMMG)",
    type=["pdf"],
)

if not uploaded:
    st.info("👆 Faça upload do relatório PDF de Contagem de Tempo para calcular seus direitos.")
    st.markdown("""
| Direito | Art. | Quem tem direito | Critério |
|---|---|---|---|
| Quinquênios | 63 | Ingressos **até 14/07/2003** | +5% a cada 5 **anos de serviço** |
| ADE | 59-A a 59-C | Ingressos **após EC 57/2003** (ou optantes) | % crescente por ADIs ≥ 70% |
| Adicional Trintenário | 64 | Todos | +10% com 30 **anos de serviço** |
| Abono de Permanência | 204 §2º / 220 §único | Todos | 1/3 dos vencimentos ao atingir requisitos para reserva voluntária |
| Reserva Voluntária | 136, II | Todos | 35 anos de serviço **e** 30 anos de atividade militar |

**Base de cálculo para quinquênio inclui:**
- Férias-prêmio contadas como tempo de serviço/vantagem → **sempre em dobro**
- Férias anuais vantagem → **sempre em dobro**
- Férias-prêmio não gozadas → **dobro a pedido** (pergunta ao usuário)
- Férias anuais não gozadas → **dobro a pedido** (pergunta ao usuário)
- Serviço público averbado **anterior a 2002** → soma simples
""")
    st.stop()

# ── Leitura e parse
raw_text = read_sirh_zip(uploaded)
if raw_text is None:
    st.stop()

text = normalize(raw_text)
data = parse_pdf(text)
if data is None:
    st.stop()

ref      = data["data_referencia"]
ingresso = data["ingresso_estimado"]
pos_ec57 = ingresso > EC57_CORTE

# ─── Painel de identificação ──────────────────────────────────────────────────

_ded_dias = data["deduzir_anos"] * 365 + data["deduzir_dias"]
_ded_nota = (f'<div class="info-item" style="color:#b71c1c;font-size:0.8rem">'
             f'⚠️ {_ded_dias}d deduzidos (licença/afastamento) — '
             f'efetivo líquido: {data["efetivo_anos"]}a {data["efetivo_dias"]}d</div>'
             if _ded_dias > 0 else "")

st.markdown(f"""
<div class="militar-card">
    <h3>👤 {data['nome']}</h3>
    <div class="info-row">
        <div class="info-item">Posto/Grad.: <span>{data['posto']}</span></div>
        <div class="info-item">N.º PM: <span>{data['numero_pm']}</span></div>
        <div class="info-item">Quadro: <span>{data['quadro']}</span></div>
        <div class="info-item">Unidade: <span>{data['unidade']}</span></div>
        <div class="info-item">Data-base: <span>{ref.strftime('%d/%m/%Y')}</span></div>
        <div class="info-item">Ingresso estimado: <span>{ingresso.strftime('%d/%m/%Y')}</span>
            <small style="color:#555"> (baseado em {data['efetivo_bruto_anos']}a {data['efetivo_bruto_dias']}d de serviço bruto)</small>
        </div>
    </div>
    {_ded_nota}
</div>
""", unsafe_allow_html=True)

# ─── Perguntas ao usuário ─────────────────────────────────────────────────────

st.markdown('<div class="section-title">⚙️ Opções de Contabilização</div>', unsafe_allow_html=True)

col_a = st.container()
with col_a:
    fp_ng_label = (f"Incluir férias-prêmio **não gozadas** em dobro "
                   f"({data['fp_ng_simples']}d simples → +{data['fp_ng_simples']} dias extras)")
    incluir_fp_ng = st.checkbox(fp_ng_label,
                                 value=False,
                                 help="Férias-prêmio não gozadas podem ser contadas em dobro para fins "
                                      "de quinquênio e trintenário (art. 108 da Lei 5.301/69).",
                                 disabled=data["fp_ng_simples"] == 0)

# FA não gozadas — checkboxes individuais por exercício com classificação por prazo
# Regra: férias do ano corrente e do ano anterior ainda podem ser usufruídas
# (prazo máximo: até o final do exercício seguinte). Exercícios anteriores = prescritos.
_ano_ref = data["data_referencia"].year
_ano_limite_fruicao = _ano_ref - 1   # militar ainda pode usufruir: ano_ref e ano_ref-1

fa_ng_anos_selecionados = set()
if data["fa_ng_por_ano"]:
    st.markdown('''
<div class="warn-box blue">
    📋 <strong>Férias anuais não gozadas — seleção por exercício</strong><br>
    Férias dos exercícios <strong>prescritos</strong> (antes de {ano_limite}) já não podem
    mais ser usufruídas e podem ser convertidas em vantagem (tempo em dobro + bônus de +1 dia
    a cada 5 dias). Férias de {ano_limite} e {ano_ref} ainda estão dentro do prazo de fruição.
</div>'''.format(ano_limite=_ano_limite_fruicao, ano_ref=_ano_ref), unsafe_allow_html=True)

    prescrito_cols = [a for a in sorted(data["fa_ng_por_ano"]) if a < _ano_limite_fruicao]
    dentro_prazo   = [a for a in sorted(data["fa_ng_por_ano"]) if a >= _ano_limite_fruicao]

    if prescrito_cols:
        st.markdown("**Exercícios prescritos** *(podem ser convertidos em vantagem):*")
        _cols = st.columns(min(len(prescrito_cols), 4))
        for i, ano in enumerate(prescrito_cols):
            dias = data["fa_ng_por_ano"][ano]
            bonus = dias // 5
            com_bonus = dias + bonus
            with _cols[i % 4]:
                selecionado = st.checkbox(
                    f"**{ano}**",
                    value=True,
                    key=f"fa_ng_{ano}",
                    help=f"{ano}: {dias}d + {bonus}d bônus (1/5) = {com_bonus}d simples → {com_bonus*2}d em dobro"
                )
                st.caption(f"{dias}d + {bonus}bônus → **+{com_bonus*2}d**")
                if selecionado:
                    fa_ng_anos_selecionados.add(ano)

    if dentro_prazo:
        st.markdown("**Dentro do prazo de fruição** *(o militar ainda pode gozar estas férias):*")
        _cols2 = st.columns(min(len(dentro_prazo), 4))
        for i, ano in enumerate(dentro_prazo):
            dias = data["fa_ng_por_ano"][ano]
            bonus = dias // 5
            com_bonus = dias + bonus
            with _cols2[i % 4]:
                selecionado = st.checkbox(
                    f"**{ano}** ⏰",
                    value=False,
                    key=f"fa_ng_{ano}",
                    help=f"{ano}: ainda dentro do prazo de fruição. "
                         f"Se optar por vantagem: {dias}d + {bonus}d bônus = {com_bonus}d → {com_bonus*2}d em dobro"
                )
                st.caption(f"{dias}d *(prazo vigente)*")
                if selecionado:
                    fa_ng_anos_selecionados.add(ano)

# ── Serviço público averbado pré-2002
spub_total = data["spub_total_dias"]
spub_pre2002 = 0
if spub_total > 0:
    st.markdown("""
<div class="warn-box orange">
    ⚠️ <strong>Serviço público averbado detectado.</strong>
    Para fins de quinquênio, <strong>somente</strong> o tempo averbado de serviço público
    prestado <strong>antes de 2002</strong> é computado.
    Informe abaixo o número de dias anterior a 2002.
</div>
""", unsafe_allow_html=True)
    spub_pre2002 = st.number_input(
        f"Dias de serviço público averbado **anteriores a 2002** (total averbado: {spub_total}d)",
        min_value=0, max_value=spub_total, value=0, step=1,
    )
else:
    spub_pre2002 = 0

# ─── Base de cálculo ──────────────────────────────────────────────────────────

base = build_base(data, incluir_fp_ng, fa_ng_anos_selecionados, spub_pre2002)

# ─── Checagem em relação ao SIRH ─────────────────────────────────────────────

st.markdown('<div class="section-title">📊 Resumo do Tempo de Serviço</div>', unsafe_allow_html=True)

# Tabela detalhada
sirh_total = base["sirh_total"]
calc_total  = base["total_calculado"]
dif         = base["diferenca"]

ef_a, ef_d = data["efetivo_anos"], data["efetivo_dias"]
tot_sirh_a, tot_sirh_d = data["total_anos"], data["total_dias"]

st.markdown(f"""
<div class="time-table">
    <div class="time-row">
        <span class="t-label">Efetivo Serviço na PMMG
        {'<small style="color:#b71c1c"> (bruto ' + str(data["efetivo_bruto_anos"]) + "a " + str(data["efetivo_bruto_dias"]) + "d − " + str(base["deduzir"]) + "d deduzidos)</small>" if base["deduzir"] > 0 else ""}</span>
        <span class="t-value">{ef_a}a {ef_d}d ({base['efetivo']} dias)</span>
    </div>
    <div class="time-row">
        <span class="t-label">Férias-prêmio contadas (sempre dobro)</span>
        <span class="t-value">+{base['fp_cont_dobro']} dias ({data['fp_contadas_simples']}d × 2)</span>
    </div>
    <div class="time-row">
        <span class="t-label">Férias-prêmio não gozadas (dobro {'✅ incluído' if incluir_fp_ng else '⬜ não incluído'})</span>
        <span class="t-value">{'+' if base['fp_ng_dobro']>0 else ''}{base['fp_ng_dobro']} dias</span>
    </div>
    <div class="time-row">
        <span class="t-label">Férias anuais vantagem (sempre dobro)</span>
        <span class="t-value">+{base['fa_vant_dobro']} dias <small style="color:#777">({data['fa_vant_simples']}d × 2)</small></span>
    </div>
    <div class="time-row">
        <span class="t-label">Férias anuais não gozadas selecionadas
        {('<small style="color:#555"> — exerc. ' + ', '.join(str(a) for a in sorted(base['fa_ng_anos_selecionados'])) + '</small>') if base['fa_ng_anos_selecionados'] else '<small style="color:#999"> — nenhum exercício selecionado</small>'}</span>
        <span class="t-value">{'+' if base['fa_ng_dobro']>0 else ''}{base['fa_ng_dobro']} dias
        {'<small style="color:#777"> (' + str(base["fa_ng_sel_simples"]) + 'd + ' + str(base["fa_ng_bonus_total"]) + 'd bônus) × 2</small>' if base['fa_ng_dobro']>0 else ''}</span>
    </div>
    <div class="time-row">
        <span class="t-label">Serviço público averbado pré-2002</span>
        <span class="t-value">+{base['spub_pre2002']} dias</span>
    </div>
    <div class="time-row">
        <span class="t-label">Arredondamento (até 182 dias)</span>
        <span class="t-value">+{base['arredondamento']} dias</span>
    </div>
    {'<div class="time-row" style="color:#888;font-size:0.82rem"><span class="t-label">⚠️ Tempo a deduzir (' + str(base["deduzir"]) + 'd) — já descontado pelo SIRH no efetivo líquido acima</span></div>' if base["deduzir"] > 0 else ""}
    <div class="time-row" style="background:#e8f5e9;border-radius:4px;padding:0.4rem 0.2rem">
        <span class="t-label"><strong>Total calculado (base dos quinquênios)</strong></span>
        <span class="t-value"><strong>{calc_total//365}a {calc_total%365}d ({calc_total} dias)</strong></span>
    </div>
    <div class="time-row" style="background:#e8eaf6;border-radius:4px;padding:0.4rem 0.2rem">
        <span class="t-label"><strong>Total de Anos de Serviço (SIRH)</strong></span>
        <span class="t-value"><strong>{tot_sirh_a}a {tot_sirh_d}d ({sirh_total} dias)</strong></span>
    </div>
</div>
""", unsafe_allow_html=True)

# Checagem vs SIRH
# O SIRH SEMPRE inclui fp_ng e todas as fa_ng no seu total (com bônus).
# A diferença esperada = itens não selecionados pelo usuário.
_fa_ng_todos_com_bonus = sum(d + d // 5 for d in data["fa_ng_por_ano"].values())
_fa_ng_sel_com_bonus   = sum(
    (d + d // 5) for ano, d in data["fa_ng_por_ano"].items()
    if ano in fa_ng_anos_selecionados
)
dif_esperada_negativa = -(data["fp_ng_simples"] * 2 * (0 if incluir_fp_ng else 1)
                         + (_fa_ng_todos_com_bonus - _fa_ng_sel_com_bonus) * 2)

if dif == 0:
    st.markdown("""
<div class="warn-box green">
    ✅ <strong>Verificação OK:</strong> O total calculado coincide exatamente com o total do SIRH.
</div>
""", unsafe_allow_html=True)
elif abs(dif - dif_esperada_negativa) <= 20:
    # Diferença explicada pelas opções não marcadas (+ margem de 20d para parse de fa_ng)
    explicacao = []
    if not incluir_fp_ng and data["fp_ng_simples"] > 0:
        explicacao.append(f"férias-prêmio não gozadas ({data['fp_ng_simples']*2}d) não incluídas")
    _anos_nao_sel = sorted(a for a in data["fa_ng_por_ano"] if a not in fa_ng_anos_selecionados)
    if _anos_nao_sel:
        _d_nao_sel = sum((d + d//5)*2 for a,d in data["fa_ng_por_ano"].items() if a in _anos_nao_sel)
        explicacao.append(f"exerc. FA não gozadas não selecionados ({', '.join(str(a) for a in _anos_nao_sel)}: ~{_d_nao_sel}d)")
    motivo = " e ".join(explicacao) if explicacao else "opções de contabilização"
    st.markdown(f"""
<div class="warn-box blue">
    ℹ️ <strong>Diferença esperada ({dif:+d} dias):</strong> Decorre de {motivo}.
    O SIRH sempre computa esses itens; o cálculo acima respeita as opções que você escolheu.
    Para reproduzir exatamente o total SIRH, marque as opções correspondentes acima.
</div>
""", unsafe_allow_html=True)
elif abs(dif) <= 182:
    st.markdown(f"""
<div class="warn-box orange">
    ⚠️ <strong>Pequena divergência ({dif:+d} dias):</strong>
    Dentro da margem de arredondamento (≤ 182 dias).
    Pode decorrer das opções de contabilização ou de diferença de arredondamento de dias úteis.
</div>
""", unsafe_allow_html=True)
else:
    st.markdown(f"""
<div class="warn-box red">
    ❌ <strong>Divergência significativa ({dif:+d} dias):</strong>
    Verifique as opções de contabilização ou consulte a DAL/PMMG.
</div>
""", unsafe_allow_html=True)

# ─── Regime de adicional ──────────────────────────────────────────────────────

if pos_ec57:
    st.markdown("""
<div class="warn-box blue">
    📋 <strong>Regime ADE:</strong> Militar ingressou após a EC 57/2003 — faz jus ao
    <strong>ADE (Adicional de Desempenho)</strong> no lugar do quinquênio (art. 59-A).
</div>
""", unsafe_allow_html=True)
else:
    st.markdown("""
<div class="warn-box blue">
    📋 <strong>Regime Quinquênio:</strong> Militar ingressou antes da EC 57/2003 —
    faz jus aos <strong>quinquênios</strong> (art. 63). Pode optar pelo ADE (art. 59-A, §2º).
</div>
""", unsafe_allow_html=True)

# ─── Cálculo dos direitos ─────────────────────────────────────────────────────

rights = compute_rights(data, base)

# ── Quinquênios
st.markdown(
    '<div class="section-title">📅 Quinquênios &nbsp;'
    '<small style="font-weight:400;font-size:0.8rem">(art. 63 – Lei 5.301/69 · ingressos até 14/07/2003)</small></div>',
    unsafe_allow_html=True)

quins   = [r for r in rights if r["group"] == "quinquenio"]
acq_q   = [r for r in quins  if r["kind"] == "acquired"]
fut_q   = [r for r in quins  if r["kind"] != "acquired"]
label_q = (f"✅ {len(acq_q)} adquirido(s)" if acq_q else "") + (f"   ⏳ próximos {len(fut_q)}" if fut_q else "")

with st.expander(label_q or "Quinquênios", expanded=True):
    for r in acq_q + fut_q:
        st.markdown(card(r["title"], r["sub"], r["badge"], r["kind"]), unsafe_allow_html=True)

# ── ADE
st.markdown(
    '<div class="section-title">📈 ADE – Adicional de Desempenho &nbsp;'
    '<small style="font-weight:400;font-size:0.8rem">(arts. 59-A a 59-C – Lei 5.301/69)</small></div>',
    unsafe_allow_html=True)

st.markdown("""
<div class="warn-box orange">
    ⚠️ <strong>Atenção:</strong> As datas indicam o <strong>marco temporal</strong> de cada nível.
    O percentual só é concedido se o número de <strong>ADIs com resultado ≥ 70%</strong>
    também for cumprido. O somatório de quinquênios + ADE não pode exceder 90% da remuneração base.
</div>
""", unsafe_allow_html=True)

ades    = [r for r in rights if r["group"] == "ade"]
acq_a   = [r for r in ades   if r["kind"] == "acquired"]
fut_a   = [r for r in ades   if r["kind"] != "acquired"]
label_a = (f"✅ {len(acq_a)} marco(s) atingido(s)" if acq_a else "") + (f"   ⏳ próximos {len(fut_a)}" if fut_a else "")

with st.expander(label_a or "ADE", expanded=False):
    for r in acq_a + fut_a:
        st.markdown(card(r["title"], r["sub"], r["badge"], r["kind"]), unsafe_allow_html=True)

# ── Trintenário
st.markdown(
    '<div class="section-title">🏅 Adicional Trintenário &nbsp;'
    '<small style="font-weight:400;font-size:0.8rem">(art. 64 – Lei 5.301/69)</small></div>',
    unsafe_allow_html=True)

for r in rights:
    if r["group"] == "trintenario":
        st.markdown(card(r["title"], r["sub"], r["badge"], r["kind"]), unsafe_allow_html=True)

# ── Abono de Permanência
st.markdown(
    '<div class="section-title">💰 Abono de Permanência &nbsp;'
    '<small style="font-weight:400;font-size:0.8rem">(art. 204 §2º / art. 220 §único)</small></div>',
    unsafe_allow_html=True)

for r in rights:
    if r["group"] == "abono":
        st.markdown(card(r["title"], r["sub"], r["badge"], r["kind"]), unsafe_allow_html=True)

# ── Reserva Voluntária
st.markdown(
    '<div class="section-title">🎖️ Transferência Voluntária à Reserva &nbsp;'
    '<small style="font-weight:400;font-size:0.8rem">(art. 136, II – Lei 5.301/69)</small></div>',
    unsafe_allow_html=True)

for r in rights:
    if r["group"] == "reserva":
        st.markdown(card(r["title"], r["sub"], r["badge"], r["kind"]), unsafe_allow_html=True)

# ─── Prospecção futura de férias-prêmio ───────────────────────────────────────

st.markdown(
    '<div class="section-title">🗓️ Prospecção de Férias-Prêmio Futuras &nbsp;'
    '<small style="font-weight:400;font-size:0.8rem">(art. 107/108 – Lei 5.301/69)</small></div>',
    unsafe_allow_html=True)

st.markdown("""
<div class="warn-box blue">
    ℹ️ Férias-prêmio são concedidas a cada <strong>5 anos corridos</strong> de efetivo serviço (art. 107).
    Quando não puderem ser gozadas, acrescem o tempo de serviço <strong>em dobro</strong> para fins
    de quinquênio, trintenário e incorporação de gratificações (art. 108).
    A prospecção abaixo projeta as concessões futuras a partir da data de ingresso estimada.
</div>
""", unsafe_allow_html=True)

projecoes = projetar_ferias_premio(data, incluir_fp_ng)
ef_total  = data["efetivo_anos"] * 365 + data["efetivo_dias"]

for p in projecoes:
    q        = p["quinquenio"]
    dt       = p["data_concessao"]
    k        = p["status"]
    s_rel    = p["status_rel"]
    miss_ef  = max(0, q * 5 * 365 - ef_total)

    if s_rel == "contada":
        label = f"✅ {q}º FP — Já contada como tempo de serviço"
        sub   = f"Concedida em ~{fmt_date(dt)} · {q*90}d simples já incluídos em dobro no SIRH"
        css   = "fp-proj-card"
    elif s_rel == "não_gozada":
        label = f"⏸️ {q}º FP — Concedida, não gozada (consta no relatório)"
        sub   = (f"Concedida em ~{fmt_date(dt)} · "
                 f"{'Incluída em dobro neste cálculo ✅' if incluir_fp_ng else 'Não incluída em dobro (marque a opção acima)'}")
        css   = "fp-proj-card"
    elif k == "future":
        label = f"⏳ {q}º FP — Futura (próxima)"
        sub   = (f"Previsão de concessão: {fmt_date(dt)}  (faltam {days_label(miss_ef)} de efetivo serviço)<br>"
                 f"Ao converter em dobro: +90 dias na base de cálculo")
        css   = "fp-proj-card fp-future"
    else:
        label = f"📌 {q}º FP — Prevista"
        sub   = (f"Previsão de concessão: {fmt_date(dt)}  (faltam {days_label(miss_ef)} de efetivo serviço)")
        css   = "fp-proj-card fp-far"

    st.markdown(f'<div class="{css}"><strong>{label}</strong><br>{sub}</div>',
                unsafe_allow_html=True)

# ─── Disclaimer ───────────────────────────────────────────────────────────────

st.markdown("""
<div class="disclaimer">
    ⚠️ <strong>Aviso Legal:</strong> Estimativas baseadas nos dados do relatório e na
    Lei n.º 5.301/1969 (atualizada até LC 168/2022). Não substituem análise oficial da DAL/PMMG.
    Afastamentos, licenças, processos administrativos e outros fatores individuais podem alterar
    as datas calculadas. A data de ingresso é <em>estimada</em> a partir do tempo de efetivo serviço —
    pequenas variações podem ocorrer. O serviço público averbado anterior a 2002 deve ser confirmado
    junto à DAL/PMMG.
</div>
""", unsafe_allow_html=True)
