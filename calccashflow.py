import streamlit as st
import pandas as pd
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
            r = requests.get(url)
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

# --- 4. メイン UI (入力フォーム) ---
st.title("💰 簡易資金繰りシミュレーター")

with st.form("input_form"):
    st.subheader("📋 受注案件入力表")
    edited_df = st.data_editor(
        st.session_state.df, 
        num_rows="dynamic", 
        use_container_width=True,
        hide_index=True, # 左側の数字列を非表示にする
        column_config={
            "開始日": st.column_config.DateColumn(format="YYYY/MM/DD"),
            "終了日": st.column_config.DateColumn(format="YYYY/MM/DD"),
            "受注金額": st.column_config.NumberColumn(format="%d"),
            "入金条件": st.column_config.SelectboxColumn(options=["出来高払い", "完工時一括", "毎月均等払い"]),
        }
    )
    
    col_s1, col_s2, col_s3, col_s4 = st.columns(4)
    with col_s1: initial_cash = st.number_input("期首現金 (円)", value=10000000, step=1000000)
    with col_s2: monthly_sga = st.number_input("月間販管費 (円)", value=1500000, step=100000)
    with col_s3: monthly_loan = st.number_input("月間借入返済 (円)", value=500000, step=100000)
    with col_s4: start_period = st.date_input("開始月", datetime.today().replace(day=1))
    
    submitted = st.form_submit_button("🚀 計算を実行する")

# --- 5. 計算と表示 (ボタン押下後) ---
if submitted or 'calculated' in st.session_state:
    st.session_state.calculated = True
    st.session_state.df = edited_df
    months_header = [(start_period + relativedelta(months=i)).strftime("%Y/%m") for i in range(12)]
    
    valid_df = edited_df[edited_df["案件名"].fillna("") != ""]
    total_income = pd.Series(0.0, index=months_header)
    total_cost = pd.Series(0.0, index=months_header)

    for _, row in valid_df.iterrows():
        amt = row.get("受注金額", 0) or 0
        rate = row.get("原価率", 0) or 0
        total_income += calculate_row_cashflow(amt, row["開始日"], row["終了日"], row["入金条件"], row["サイト(日)"], months_header)
        total_cost += calculate_row_cashflow(amt * rate, row["開始日"], row["終了日"], row["入金条件"], row["サイト(日)"], months_header)

    monthly_cf = total_income - total_cost - monthly_sga - monthly_loan
    cash_balance = monthly_cf.cumsum() + initial_cash

    st.subheader("📊 資金繰り明細表")
    summary_table = pd.DataFrame({
        "入金合計": total_income, "原価支払合計": total_cost, "販管費": monthly_sga, "借入返済": monthly_loan, "月次収支": monthly_cf, "現預金残高": cash_balance
    }).T
    st.dataframe(summary_table.style.format("{:,.0f}"), use_container_width=True)

    st.subheader("📈 資金繰り推移グラフ")
    st.line_chart(cash_balance)

    # --- 6. PDF生成 (左詰めレイアウト) ---
    def create_pdf():
        buffer = io.BytesIO()
        doc = SimpleDocTemplate(buffer, pagesize=landscape(A3), leftMargin=30, rightMargin=30)
        elements = []
        style_sheet = styles.getSampleStyleSheet()
        n_style = style_sheet['Normal']
        n_style.fontName = FONT_NAME

        # タイトル
        title_style = style_sheet['Title']
        title_style.fontName = FONT_NAME
        title_style.alignment = 0 # 0は左詰め
        elements.append(Paragraph(f"資金繰りシミュレーション報告書 ({datetime.now().strftime('%Y/%m/%d')})", title_style))
        elements.append(Spacer(1, 20))

        # 基本設定
        elements.append(Paragraph("【基本設定】", n_style))
        base_data = [["期首現金", "月間販管費", "月間借入返済"], [f"{initial_cash:,.0f}円", f"{monthly_sga:,.0f}円", f"{monthly_loan:,.0f}円"]]
        t_base = Table(base_data, hAlign='LEFT')
        t_base.setStyle(TableStyle([('FONT', (0,0), (-1,-1), FONT_NAME, 10), ('GRID', (0,0), (-1,-1), 0.5, colors.black), ('ALIGN', (0,0), (-1,-1), 'LEFT')]))
        elements.append(t_base)
        elements.append(Spacer(1, 20))

        # 入力内容
        elements.append(Paragraph("【受注案件入力内容】", n_style))
        in_data = [["案件名", "受注金額", "開始日", "終了日", "条件"]]
        for _, r in valid_df.fillna(0).iterrows():
            in_data.append([str(r["案件名"]), f"{r['受注金額']:,.0f}", str(r["開始日"]), str(r["終了日"]), str(r["入金条件"])])
        t_in = Table(in_data, hAlign='LEFT')
        t_in.setStyle(TableStyle([('FONT', (0,0), (-1,-1), FONT_NAME, 9), ('GRID', (0,0), (-1,-1), 0.5, colors.grey), ('ALIGN', (0,0), (-1,-1), 'LEFT')]))
        elements.append(t_in)
        elements.append(Spacer(1, 20))

        # 明細表
        elements.append(Paragraph("【資金繰り明細表】", n_style))
        detail_data = [["項目"] + months_header]
        for idx, row in summary_table.iterrows():
            detail_data.append([idx] + [f"{v:,.0f}" for v in row.values])
        t_det = Table(detail_data, hAlign='LEFT')
        t_det.setStyle(TableStyle([('FONT', (0,0), (-1,-1), FONT_NAME, 9), ('GRID', (0,0), (-1,-1), 0.5, colors.grey), ('ALIGN', (0,0), (-1,-1), 'LEFT')]))
        elements.append(t_det)

        doc.build(elements)
        return buffer.getvalue()

    st.divider()
    st.download_button(label="📄 報告書PDFをダウンロード", data=create_pdf(), file_name="report.pdf", mime="application/pdf")