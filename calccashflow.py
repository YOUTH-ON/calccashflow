import streamlit as st
import pandas as pd
import numpy as np
from datetime import datetime
from dateutil.relativedelta import relativedelta
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import A3, landscape
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
from reportlab.lib import colors, styles
import io
import requests
import os

st.set_page_config(layout="wide", page_title="プロフェッショナル財務シミュレーター")

# --- 1. フォント・初期設定 ---
@st.cache_resource
def load_font():
    font_path = "SawarabiGothic.ttf"
    if not os.path.exists(font_path):
        url = "https://github.com/google/fonts/raw/main/ofl/sawarabigothic/SawarabiGothic-Regular.ttf"
        try:
            r = requests.get(url, timeout=10)
            with open(font_path, "wb") as f: f.write(r.content)
        except: return None
    try:
        pdfmetrics.registerFont(TTFont('JapaneseGothic', font_path))
        return 'JapaneseGothic'
    except: return None

FONT_NAME = load_font() or 'Helvetica'

# --- 2. セッションステート初期化 (千円単位) ---
# 各カテゴリーの初期データ
initial_pl_data = {
    "売上の部": [["売上高", 10000, 30]],
    "売上原価の部": [["外注費", 3000, 30], ["材料費", 1000, 30], ["労務費", 2000, 0], ["減価償却費", 500, 0]],
    "販管費の部": [["役員報酬", 1000, 0], ["人件費", 2000, 0], ["減価償却費", 100, 0], ["交際費", 100, 30], ["その他経費", 100, 30]],
    "雑収益・雑損失の部": [["受取配当金", 10, 0], ["支払利息", 20, 0]],
    "特別利益・特別損失の部": [["固定資産売却益", 0, 0], ["固定資産売却損", 0, 0]]
}

for cat, data in initial_pl_data.items():
    if f"df_{cat}" not in st.session_state:
        st.session_state[f"df_{cat}"] = pd.DataFrame(data, columns=["項目", "金額(千円)", "入出金サイト(日)"])

if 'df' not in st.session_state: # 通常モード用
    st.session_state.df = pd.DataFrame([{"案件名": "案件A", "受注金額(千円)": 5000, "原価率": 0.7, "開始日": datetime.today().date(), "終了日": (datetime.today() + relativedelta(months=3)).date(), "入金条件": "出来高払い", "サイト(日)": 30}])

for key in ['pl_edit_mode', 'detail_edit_mode', 'calc_done']:
    if key not in st.session_state: st.session_state[key] = False

# --- 3. サイドバー・共通設定 ---
st.sidebar.title("🛠 設定メニュー")
st.sidebar.info("単位：千円")
app_mode = st.sidebar.radio("モード選択", ["通常モード (受注案件)", "詳細モード (損益計算書)"])

# --- 4. 補助計算関数 ---
def calculate_cashflow_k(amount, start_date, end_date, condition, site_days, months_header):
    results = pd.Series(0.0, index=months_header)
    if not amount or amount <= 0 or pd.isna(start_date) or pd.isna(end_date): return results
    site_m = int(round(site_days / 30))
    s_month = pd.to_datetime(start_date).replace(day=1)
    e_month = pd.to_datetime(end_date).replace(day=1)
    duration = max(1, (e_month.year - s_month.year) * 12 + (e_month.month - s_month.month) + 1)
    def get_pay_m(base_date): return (base_date + relativedelta(months=site_m)).strftime("%Y/%m")
    
    if condition in ["出来高払い", "毎月均等払い"]:
        monthly_amt = amount / duration
        for i in range(duration):
            pay_m = get_pay_m(s_month + relativedelta(months=i))
            if pay_m in results.index: results[pay_m] += monthly_amt
    elif condition == "完工時一括":
        pay_m = get_pay_m(e_month)
        if pay_m in results.index: results[pay_m] += amount
    return results

# --- 5. 通常モード ---
if app_mode == "通常モード (受注案件)":
    st.title("💰 通常シミュレーション (千円単位)")
    with st.form("normal_input"):
        edited_df = st.data_editor(st.session_state.df, num_rows="dynamic", use_container_width=True, hide_index=True)
        c1, c2, c3, c4 = st.columns(4)
        with c1: initial_cash = st.number_input("期首現金(千円)", value=10000)
        with c2: m_sga = st.number_input("月間販管費(千円)", value=1500)
        with c3: m_loan = st.number_input("借入返済(千円)", value=500)
        with c4: s_period = st.date_input("開始月", datetime.today().replace(day=1))
        submitted = st.form_submit_button("🚀 案件情報を反映")

    if submitted:
        st.session_state.df = edited_df
        months = [(s_period + relativedelta(months=i)).strftime("%Y/%m") for i in range(12)]
        inc, cost = pd.Series(0.0, index=months), pd.Series(0.0, index=months)
        for _, r in edited_df.dropna(subset=["案件名"]).iterrows():
            inc += calculate_cashflow_k(r["受注金額(千円)"], r["開始日"], r["終了日"], r["入金条件"], r["サイト(日)"], months)
            cost += calculate_cashflow_k(r["受注金額(千円)"]*r["原価率"], r["開始日"], r["終了日"], r["入金条件"], r["サイト(日)"], months)
        st.session_state.manual_summary = pd.DataFrame({"入金合計": inc, "原価支払合計": cost, "販管費": m_sga, "借入返済": m_loan, "短期借入金": 0.0}).T
        st.session_state.calc_done, st.session_state.initial_cash, st.session_state.months_header = True, initial_cash, months

# --- 6. 詳細モード (表の分割と行追加) ---
else:
    st.title("📊 詳細シミュレーション (千円単位)")
    col_c1, col_c2, col_c3 = st.columns(3)
    with col_c1: initial_cash = st.number_input("期首現預金残高(千円)", value=20000)
    with col_c2: m_loan_repay = st.number_input("借入返済(月額/千円)", value=1000)
    with col_c3: s_month = st.date_input("シミュレーション開始月", datetime.today().replace(day=1))

    st.subheader("損益計算書 各部の設定")
    cats = ["売上の部", "売上原価の部", "販管費の部", "雑収益・雑損失の部", "特別利益・特別損失の部"]
    
    if not st.session_state.pl_edit_mode:
        for cat in cats:
            st.write(f"#### {cat}")
            st.dataframe(st.session_state[f"df_{cat}"], use_container_width=True, hide_index=True)
        if st.button("📝 損益計算書を編集"): st.session_state.pl_edit_mode = True; st.rerun()
    else:
        for cat in cats:
            st.write(f"#### {cat}")
            st.session_state[f"df_{cat}"] = st.data_editor(st.session_state[f"df_{cat}"], num_rows="dynamic", use_container_width=True, hide_index=True, key=f"edit_{cat}")
        if st.button("💾 損益設定を保存"): st.session_state.pl_edit_mode = False; st.rerun()

    if st.button("📉 詳細計算実行", type="primary"):
        months = [(s_month + relativedelta(months=i)).strftime("%Y/%m") for i in range(12)]
        all_items = pd.concat([st.session_state[f"df_{cat}"] for cat in cats])
        
        # 簡易PL計算
        rev = st.session_state["df_売上の部"]["金額(千円)"].sum()
        cogs = st.session_state["df_売上原価の部"]["金額(千円)"].sum()
        sga = st.session_state["df_販管費の部"]["金額(千円)"].sum()
        pre_tax = rev - cogs - sga + st.session_state["df_雑収益・雑損失の部"].iloc[0,1] - st.session_state["df_雑収益・雑損失の部"].iloc[1,1] # 簡易
        tax = max(0, pre_tax * 0.19)
        
        # 明細生成
        detail = {}
        for _, r in all_items.iterrows():
            sm = int(round(r["入出金サイト(日)"] / 30))
            vals = [0.0]*12
            for m in range(12):
                if m + sm < 12: vals[m + sm] = r["金額(千円)"]
            if "減価償却費" in r["項目"]: vals = [0.0]*12
            detail[r["項目"]] = vals
        
        detail["法人税等"] = [tax/12]*12
        detail["借入返済"] = [m_loan_repay]*12
        detail["短期借入金"] = [0.0]*12
        st.session_state.manual_summary = pd.DataFrame(detail, index=months).T
        st.session_state.calc_done, st.session_state.initial_cash, st.session_state.months_header = True, initial_cash, months

# --- 7. 明細表・編集・PDF ---
if st.session_state.get('calc_done'):
    st.divider()
    st.subheader(f"📋 資金繰り明細表 (単位: 千円)")
    
    if not st.session_state.detail_edit_mode:
        if st.button("📝 明細を修正する"): st.session_state.detail_edit_mode = True; st.rerun()
        ms = st.session_state.manual_summary
    else:
        ms = st.data_editor(st.session_state.manual_summary, use_container_width=True)
        if st.button("✅ 修正を完了"): st.session_state.manual_summary = ms; st.session_state.detail_edit_mode = False; st.rerun()

    # 収支計算
    # 支出項目の判定 (入金以外をすべて支出とする簡易ロジック)
    income_rows = ["入金合計", "売上高"] # 各モードの主要入金項目
    in_sum = ms.loc[ms.index.isin(income_rows)].sum() if any(ms.index.isin(income_rows)) else ms.iloc[0] 
    out_sum = ms.loc[~ms.index.isin(income_rows + ["短期借入金"])].sum()
    
    monthly_cf = in_sum + ms.loc["短期借入金"] - out_sum
    cash_bal = monthly_cf.cumsum() + st.session_state.initial_cash
    final_view = pd.concat([ms, pd.DataFrame({"月次収支": monthly_cf, "現預金残高": cash_bal}, index=st.session_state.months_header).T])
    
    st.dataframe(final_view.style.format("{:,.0f}"), use_container_width=True)
    st.line_chart(cash_bal)

    def create_pdf():
        buffer = io.BytesIO()
        doc = SimpleDocTemplate(buffer, pagesize=landscape(A3))
        elements = [Paragraph(f"資金繰り報告書 (単位:千円)", styles.getSampleStyleSheet()['Title'])]
        data = [["項目"] + st.session_state.months_header]
        for idx, row in final_view.iterrows(): data.append([idx] + [f"{v:,.0f}" for v in row.values])
        t = Table(data, hAlign='LEFT')
        t.setStyle(TableStyle([('FONT', (0,0), (-1,-1), FONT_NAME, 7), ('GRID', (0,0), (-1,-1), 0.5, colors.grey)]))
        elements.append(t)
        doc.build(elements)
        return buffer.getvalue()

    st.download_button("📄 PDFダウンロード (千円単位)", data=create_pdf(), file_name="cashflow_k.pdf")
