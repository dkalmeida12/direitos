# 🪖 Calculadora de Direitos – PMMG

Aplicativo web em **Streamlit** para calcular datas de aquisição de direitos financeiros e funcionais de militares da Polícia Militar de Minas Gerais, com base no relatório de **Contagem de Tempo** gerado pelo sistema da PMMG.

---

## 📋 Direitos Calculados

| Direito | Base Legal | Critério |
|---|---|---|
| Quinquênios | Art. 63 – Lei 5.301/69 | +10% a cada 5 anos de **anos de serviço** |
| Adicional Trintenário | Art. 64 – Lei 5.301/69 | +10% ao completar 30 **anos de serviço** |
| Abono de Permanência | Art. 204 §2º / Art. 220 §único – Lei 5.301/69 | 1/3 dos vencimentos ao atingir os requisitos para reserva voluntária |
| Transferência Voluntária para Reserva | Art. 136, II – Lei 5.301/69 | 35 anos de serviço e 30 anos de atividade militar |

---

## 🚀 Como Usar

### Requisitos

- Python 3.10+
- pip

### Instalação Local

```bash
# Clone o repositório
git clone https://github.com/SEU_USUARIO/pmmg-calculadora.git
cd pmmg-calculadora

# Instale as dependências
pip install -r requirements.txt

# Execute o aplicativo
streamlit run app.py
```

O aplicativo abrirá automaticamente no navegador em `http://localhost:8501`.

### Uso

1. Execute o aplicativo
2. Faça upload do PDF de **Contagem de Tempo** gerado pelo sistema da PMMG
3. O aplicativo extrai automaticamente os dados e calcula as datas de cada direito

---

## 🌐 Deploy no Streamlit Cloud (gratuito)

1. Faça fork deste repositório
2. Acesse [share.streamlit.io](https://share.streamlit.io)
3. Conecte sua conta GitHub
4. Selecione este repositório, branch `main` e arquivo `app.py`
5. Clique em **Deploy**

---

## 📁 Estrutura do Projeto

```
pmmg-calculadora/
├── app.py              # Aplicativo principal
├── requirements.txt    # Dependências Python
└── README.md           # Este arquivo
```

---

## ⚠️ Aviso Legal

Este aplicativo realiza **estimativas** com base nos dados extraídos do relatório de Contagem de Tempo e na legislação vigente. Os cálculos são meramente **informativos** e não substituem a análise oficial da DAL/PMMG ou de assessoria jurídica especializada.

Condições específicas de cada militar (afastamentos, licenças, processos administrativos, etc.) podem alterar as datas calculadas.

---

## 📜 Base Legal

- **Lei n.º 5.301, de 16/10/1969** – Estatuto dos Militares do Estado de Minas Gerais (texto atualizado até 28/12/2022)
- Lei Complementar n.º 95/2007 e demais alterações
- Lei Complementar n.º 168/2022

---

## 🤝 Contribuições

Pull requests são bem-vindos. Para mudanças maiores, abra uma issue primeiro para discutir o que você gostaria de alterar.
