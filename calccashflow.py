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

st.set_page_config(layout="wide", page_title="簡易資金繰りシミュレーター")

# --- 1. フォントの準備 ---
@st.cache_resource
def load_font():
    font_path = "SawarabiGothic.ttf"
    if not os.path.exists(font_path):
        url = "https://github.com/google/fonts/raw/main/ofl/sawarabigothic/SawarabiGothic-Regular.ttf"
        try:
            r = requests.get(url, timeout=10)
            with open(font_path, "wb") as f:
                f.write(r.content)
        except: return None
    try:
        pdfmetrics.registerFont(TTFont('JapaneseGothic', font_path))
        return 'JapaneseGothic'
    except: return None

FONT_NAME = load_font() or 'Helvetica'

# --- 2. データの初期化 ---
if 'df' not in st.session_state:
    st.session_state.df = pd.DataFrame([
        {"案件名": "案件A", "受注金額": 5000000, "原価率": 0.7, "開始日": datetime.today().date(), "終了日": (datetime.today() + relativedelta(months=3)).date(), "入金条件": "出来高払い", "サイト(日)": 30},
    ])
if 'edit_mode' not in st.session_state:
    st.session_state.edit_mode = False

# --- 3. 補助計算関数 ---
def calculate_row_cashflow(amount, start_date, end_date, condition, site_days, months_header):
    results = pd.Series(0.0, index=months_header)
    if not amount or amount <= 0 or pd.isna(start_date) or pd.isna(end_date):
        return results
    site_months = int(round(site_days / 30))
    s_month = pd.to_datetime(start_date).replace(day=1)
    e_month = pd.to_datetime(end_date).replace(day=1)
    duration = (e_month.year - s_month.year) * 12 + (e_month.month - s_month.month) + 1
    duration = max(1, duration)

    def get_pay_month(base_date):
        return (base_date + relativedelta(months=site_months)).strftime("%Y/%m")

    if condition in ["出来高払い", "毎月均等払い"]:
        monthly_amt = amount // duration
        for i in range(duration):
            pay_m = get_pay_month(s_month + relativedelta(months=i))
            if pay_m in results.index: results[pay_m] += monthly_amt
        last_pay_m = get_pay_month(e_month)
        if last_pay_m in results.index:
            results[last_pay_m] += (amount - (monthly_amt * duration))
    elif condition in ["完工時一括"]:
        pay_m = get_pay_month(e_month)
        if pay_m in results.index: results[pay_m] += amount
    return results

# --- 4. メイン UI (受注案件入力) ---
st.title("💰 簡易資金繰りシミュレーター")

with st.form("input_form"):
    st.subheader("📋 1. 受注案件入力表")
    edited_df = st.data_editor(
        st.session_state.df, 
        num_rows="dynamic", 
        use_container_width=True,
        hide_index=True,
        column_config={
            "開始日": st.column_config.DateColumn(format="YYYY/MM/DD"),
            "終了日": st.column_config.DateColumn(format="YYYY/MM/DD"),
            "受注金額": st.column_config.NumberColumn(format="%d"),
            "入金条件": st.column_config.SelectboxColumn(options=["出来高払い", "完工時一括", "毎月均等払い"]),
        }
    )
    
    c1, c2, c3, c4 = st.columns(4)
    with c1: initial_cash = st.number_input("期首現金 (円)", value=10000000, step=1000000)
    with c2: monthly_sga = st.number_input("月間販管費 (円)", value=1500000, step=100000)
    with c3: monthly_loan = st.number_input("月間借入返済 (円)", value=500000, step=100000)
    with c4: start_period = st.date_input("開始月", datetime.today().replace(day=1))
    
    submitted = st.form_submit_button("🚀 案件情報を反映（明細をリセット）")

# --- 5. 明細データの生成ロジック ---
months_header = [(start_period + relativedelta(months=i)).strftime("%Y/%m") for i in range(12)]

if submitted or 'manual_summary' not in st.session_state:
    st.session_state.df = edited_df
    valid_df = edited_df[edited_df["案件名"].fillna("") != ""].copy()
    total_income = pd.Series(0.0, index=months_header)
    total_cost = pd.Series(0.0, index=months_header)

    for _, row in valid_df.iterrows():
        amt = row.get("受注金額", 0) or 0
        rate = row.get("原価率", 0) or 0
        total_income += calculate_row_cashflow(amt, row["開始日"], row["終了日"], row["入金条件"], row["サイト(日)"], months_header)
        total_cost += calculate_row_cashflow(amt * rate, row["開始日"], row["終了日"], row["入金条件"], row["サイト(日)"], months_header)

    # 案件入力から基本明細を生成
    st.session_state.manual_summary = pd.DataFrame({
        "入金合計": total_income,
        "原価支払合計": total_cost,
        "販管費": monthly_sga,
        "借入返済": monthly_loan,
        "短期借入金": 0.0
    }).T
    st.session_state.edit_mode = False # 案件反映直後は閲覧モード

# --- 6. 資金繰り明細表 (編集・確定フロー) ---
st.divider()
st.subheader("📊 2. 資金繰り明細表")

if not st.session_state.edit_mode:
    # 【閲覧モード】
    if st.button("📝 明細を手動で編集する"):
        st.session_state.edit_mode = True
        st.rerun()
    
    # 閲覧用表示
    st.dataframe(st.session_state.manual_summary.style.format("{:,.0f}"), use_container_width=True)
else:
    # 【編集モード】
    st.info("数値を編集してください。終了したら下の確定ボタンを押してください。")
    new_summary = st.data_editor(
        st.session_state.manual_summary,
        use_container_width=True,
        key="summary_editor"
    )
    
    if st.button("✅ 編集内容を確定して反映する"):
        st.session_state.manual_summary = new_summary
        st.session_state.edit_mode = False
        st.success("編集を保存しました！")
        st.rerun()

# --- 7. 最終計算とグラフ表示 ---
ms = st.session_state.manual_summary
monthly_cf = ms.loc["入金合計"] + ms.loc["短期借入金"] - ms.loc["原価支払合計"] - ms.loc["販管費"] - ms.loc["借入返済"]
cash_balance = monthly_cf.cumsum() + initial_cash

final_view = pd.concat([ms, pd.DataFrame({"月次収支": monthly_cf, "現預金残高": cash_balance}, index=months_header).T])

st.write("### 📉 収支・資金繰り推移")
st.dataframe(final_view.style.format("{:,.0f}"), use_container_width=True)
st.line_chart(cash_balance)

# --- 8. PDF生成 ---
def create_pdf():
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=landscape(A3), leftMargin=30, rightMargin=30, topMargin=30)
    elements = []
    style_sheet = styles.getSampleStyleSheet()
    title_style = style_sheet['Title']
    title_style.fontName = FONT_NAME
    title_style.alignment = 0
    elements.append(Paragraph(f"資金繰りシミュレーション報告書 ({datetime.now().strftime('%Y/%m/%d')})", title_style))
    elements.append(Spacer(1, 20))

    elements.append(Paragraph("【資金繰り明細表】", style_sheet['Normal']))
    detail_data = [["項目"] + months_header]
    for idx, row in final_view.iterrows():
        detail_data.append([idx] + [f"{v:,.0f}" for v in row.values])
    t_det = Table(detail_data, hAlign='LEFT')
    t_det.setStyle(TableStyle([('FONT', (0,0), (-1,-1), FONT_NAME, 8), ('GRID', (0,0), (-1,-1), 0.5, colors.grey), ('ALIGN', (0,0), (-1,-1), 'LEFT')]))
    elements.append(t_det)
    doc.build(elements)
    return buffer.getvalue()

st.divider()
st.download_button(label="📄 報告書PDFをダウンロード", data=create_pdf(), file_name=f"cashflow_{datetime.now().strftime('%Y%m%d')}.pdf", mime="application/pdf")
