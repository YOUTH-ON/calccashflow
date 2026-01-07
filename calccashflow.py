import streamlit as st
import pandas as pd
import numpy as np
from datetime import datetime
from dateutil.relativedelta import relativedelta
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import A4, portrait
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
from reportlab.lib import colors, styles
import io
import requests
import os

st.set_page_config(layout="wide", page_title="ハイブリッド財務シミュレーター")

# --- 1. フォント・初期設定 ---
@st.cache_resource
def load_font():
    font_path = "SawarabiGothic-Regular.ttf"
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

# --- 2. セッションステート初期化 ---
if 'normal_df' not in st.session_state:
    st.session_state.normal_df = pd.DataFrame([
        {"案件名": "案件A", "受注金額(千円)": 5000, "原価率": 0.7, "開始日": datetime.today().date(), "終了日": (datetime.today() + relativedelta(months=3)).date(), "入金条件": "出来高払い", "サイト(日)": 30}
    ])

CATS = ["売上の部", "売上原価の部", "販管費の部", "雑収益・雑損失の部", "特別利益・特別損失の部"]
if 'pl_data' not in st.session_state:
    st.session_state.pl_data = {cat: pd.DataFrame(columns=["項目", "金額(千円)", "入出金サイト(日)"]) for cat in CATS}
    st.session_state.pl_data["売上の部"] = pd.DataFrame([["売上高", 10000, 30]], columns=["項目", "金額(千円)", "入出金サイト(日)"])
    st.session_state.pl_data["売上原価の部"] = pd.DataFrame([["外注費", 3000, 30]], columns=["項目", "金額(千円)", "入出金サイト(日)"])

for key in ['pl_edit_mode', 'detail_edit_mode', 'calc_done']:
    if key not in st.session_state: st.session_state[key] = False

# --- 3. 補助関数 ---
def calculate_cashflow_k(amount, start_date, end_date, condition, site_days, months_header):
    results = pd.Series(0.0, index=months_header)
    if not amount or amount <= 0 or pd.isna(start_date) or pd.isna(end_date): return results
    site_m = int(round(site_days / 30))
    s_m = pd.to_datetime(start_date).replace(day=1)
    e_m = pd.to_datetime(end_date).replace(day=1)
    duration = max(1, (e_m.year - s_m.year) * 12 + (e_m.month - s_m.month) + 1)
    def get_pay_m(base_date): return (base_date + relativedelta(months=site_m)).strftime("%Y/%m")
    if condition in ["出来高払い", "毎月均等払い"]:
        monthly_amt = amount / duration
        for i in range(duration):
            pm = get_pay_m(s_m + relativedelta(months=i))
            if pm in results.index: results[pm] += monthly_amt
    elif condition == "完工時一括":
        pm = get_pay_m(e_m)
        if pm in results.index: results[pm] += amount
    return results

# --- 4. サイドバー設定 ---
st.sidebar.title("🛠 設定 (単位:千円)")
app_mode = st.sidebar.radio("モード選択", ["通常モード (受注案件)", "詳細モード (損益計算書)"])

# --- 5. UI構築 ---
if app_mode == "通常モード (受注案件)":
    st.title("💰 通常シミュレーション (案件ベース)")
    st.subheader("📋 受注案件入力表")
    st.session_state.normal_df = st.data_editor(st.session_state.normal_df, num_rows="dynamic", use_container_width=True, hide_index=True)
    
    with st.container(border=True):
        c1, c2, c3, c4 = st.columns(4)
        with c1: init_cash = st.number_input("期首現金(千円)", value=10000)
        with c2: m_sga = st.number_input("月間販管費(千円)", value=1500)
        with c3: m_loan = st.number_input("借入返済(月額/千円)", value=500)
        with c4: s_date = st.date_input("開始月", datetime.today().replace(day=1))
        
    if st.button("🚀 計算実行", type="primary"):
        st.session_state.months_header = [(s_date + relativedelta(months=i)).strftime("%Y/%m") for i in range(12)]
        st.session_state.initial_cash = init_cash
        inc, cost = pd.Series(0.0, index=st.session_state.months_header), pd.Series(0.0, index=st.session_state.months_header)
        for _, r in st.session_state.normal_df.dropna(subset=["案件名"]).iterrows():
            inc += calculate_cashflow_k(r["受注金額(千円)"], r["開始日"], r["終了日"], r["入金条件"], r["サイト(日)"], st.session_state.months_header)
            cost += calculate_cashflow_k(r["受注金額(千円)"]*r.get("原価率",0), r["開始日"], r["終了日"], r["入金条件"], r["サイト(日)"], st.session_state.months_header)
        st.session_state.manual_summary = pd.DataFrame({"入金合計": inc, "原価支払合計": cost, "販管費": m_sga, "借入返済": m_loan, "短期借入金": 0.0}).T
        st.session_state.income_items, st.session_state.calc_done = ["入金合計"], True

else:
    st.title("📊 詳細シミュレーション (PLベース)")
    with st.container(border=True):
        col_c1, col_c2, col_c3 = st.columns(3)
        with col_c1: init_cash = st.number_input("期首現預金残高(千円)", value=20000)
        with col_c2: m_loan_repay = st.number_input("借入返済(月額/千円)", value=1000)
        with col_c3: s_date = st.date_input("シミュレーション開始月", datetime.today().replace(day=1))

    st.subheader("損益計算書 各部の設定")
    for cat in CATS:
        st.write(f"#### {cat}")
        if not st.session_state.pl_edit_mode:
            st.dataframe(st.session_state.pl_data[cat], use_container_width=True, hide_index=True)
        else:
            st.session_state.pl_data[cat] = st.data_editor(st.session_state.pl_data[cat], num_rows="dynamic", use_container_width=True, hide_index=True, key=f"ed_{cat}")
    
    if not st.session_state.pl_edit_mode:
        if st.button("📝 損益計算書を編集する"): st.session_state.pl_edit_mode = True; st.rerun()
    else:
        if st.button("💾 編集内容を保存"): st.session_state.pl_edit_mode = False; st.rerun()

    if st.button("📉 詳細計算実行", type="primary"):
        st.session_state.months_header = [(s_date + relativedelta(months=i)).strftime("%Y/%m") for i in range(12)]
        st.session_state.initial_cash = init_cash
        detail, inc_list = {}, []
        for cat in CATS:
            for _, r in st.session_state.pl_data[cat].dropna(subset=["項目"]).iterrows():
                name, val, site = r["項目"], r["金額(千円)"], r["入出金サイト(日)"]
                if cat in ["売上の部", "雑収益・雑損失の部", "特別利益・特別損失の部"]:
                    if not any(x in name for x in ["損失", "損", "利息"]): inc_list.append(name)
                sm = int(round(site / 30)); vals = [0.0]*12
                for m in range(12): 
                    if m + sm < 12: vals[m + sm] = val
                if "減価償却" in name: vals = [0.0]*12
                detail[name] = vals
        detail.update({"法人税等": [0.0]*12, "借入金返済": [m_loan_repay]*12, "短期借入金": [0.0]*12})
        st.session_state.manual_summary = pd.DataFrame(detail, index=st.session_state.months_header).T
        st.session_state.income_items, st.session_state.calc_done = inc_list, True

# --- 6. 結果表示・PDF/CSV出力 ---
if st.session_state.get('calc_done'):
    st.divider()
    st.subheader("📋 資金繰り明細表 (修正可能)")
    if not st.session_state.detail_edit_mode:
        if st.button("📝 資金繰り明細を直接修正"): st.session_state.detail_edit_mode = True; st.rerun()
        ms = st.session_state.manual_summary
    else:
        ms = st.data_editor(st.session_state.manual_summary, use_container_width=True)
        if st.button("✅ 修正完了"): st.session_state.manual_summary = ms; st.session_state.detail_edit_mode = False; st.rerun()

    in_sum = ms.loc[ms.index.isin(st.session_state.income_items)].sum()
    out_sum = ms.loc[ms.index.difference(st.session_state.income_items + ["短期借入金"])].sum()
    m_cf = in_sum + ms.loc["短期借入金"] - out_sum
    c_bal = m_cf.cumsum() + st.session_state.initial_cash
    final_view = pd.concat([ms, pd.DataFrame({"月次収支": m_cf, "現預金残高": c_bal}, index=st.session_state.months_header).T])
    st.dataframe(final_view.style.format("{:,.0f}"), use_container_width=True)
    st.line_chart(c_bal)

    # 出力用関数
    def get_output_elements():
        elements = []
        style = styles.getSampleStyleSheet()
        t_style = style['Title']; t_style.fontName = FONT_NAME
        h_style = style['Heading2']; h_style.fontName = FONT_NAME
        
        elements.append(Paragraph(f"財務報告書 ({app_mode})", t_style))
        elements.append(Spacer(1, 10))
        
        # 入力データの表を追加
        if app_mode == "通常モード (受注案件)":
            elements.append(Paragraph("【受注案件入力データ】", h_style))
            data = [st.session_state.normal_df.columns.tolist()] + st.session_state.normal_df.values.tolist()
        else:
            elements.append(Paragraph("【損益計算書 設定データ】", h_style))
            all_pl = pd.concat([st.session_state.pl_data[c] for c in CATS])
            data = [["項目", "金額", "サイト"]] + all_pl.values.tolist()
        
        t1 = Table(data, hAlign='LEFT')
        t1.setStyle(TableStyle([('FONT', (0,0), (-1,-1), FONT_NAME, 7), ('GRID', (0,0), (-1,-1), 0.5, colors.grey)]))
        elements.append(t1); elements.append(Spacer(1, 20))
        
        elements.append(Paragraph("【資金繰り明細表】", h_style))
        data_cf = [["項目"] + st.session_state.months_header]
        for idx, row in final_view.iterrows(): data_cf.append([idx] + [f"{v:,.0f}" for v in row.values])
        t2 = Table(data_cf, hAlign='LEFT')
        t2.setStyle(TableStyle([('FONT', (0,0), (-1,-1), FONT_NAME, 6), ('GRID', (0,0), (-1,-1), 0.5, colors.grey), ('BACKGROUND', (0,0), (-1,0), colors.whitesmoke)]))
        elements.append(t2)
        return elements

    # サイドバーに出力ボタンを配置
    st.sidebar.divider()
    st.sidebar.subheader("📥 データの書き出し")
    
    # PDF出力
    pdf_buffer = io.BytesIO()
    doc = SimpleDocTemplate(pdf_buffer, pagesize=portrait(A4))
    doc.build(get_output_elements())
    st.sidebar.download_button("📄 PDFダウンロード (A4縦)", data=pdf_buffer.getvalue(), file_name="report.pdf")

    # CSV出力 (全データを統合)
    csv_buffer = io.StringIO()
    if app_mode == "通常モード (受注案件)":
        st.session_state.normal_df.to_csv(csv_buffer, index=False)
    else:
        pd.concat([st.session_state.pl_data[c] for c in CATS]).to_csv(csv_buffer, index=False)
    csv_buffer.write("\n--- 資金繰り明細表 ---\n")
    final_view.to_csv(csv_buffer)
    st.sidebar.download_button("Excel/CSVダウンロード", data=csv_buffer.getvalue().encode('utf_8_sig'), file_name="data.csv", mime="text/csv")
