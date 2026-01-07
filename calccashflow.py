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

st.set_page_config(layout="wide", page_title="ハイブリッド資金繰り管理システム")

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

# --- 2. セッションステート初期化 ---
if 'df' not in st.session_state:
    st.session_state.df = pd.DataFrame([{"案件名": "案件A", "受注金額": 5000000, "原価率": 0.7, "開始日": datetime.today().date(), "終了日": (datetime.today() + relativedelta(months=3)).date(), "入金条件": "出来高払い", "サイト(日)": 30}])

if 'pl_df' not in st.session_state:
    init_pl = [
        ["売上の部", "売上高", 10000000, 30], ["売上原価の部", "外注費", 3000000, 30], ["売上原価の部", "材料費", 1000000, 30],
        ["売上原価の部", "労務費", 2000000, 0], ["売上原価の部", "減価償却費", 500000, 0], ["売上原価の部", "その他経費", 200000, 30],
        ["販管費の部", "役員報酬", 1000000, 0], ["販管費の部", "人件費", 2000000, 0], ["販管費の部", "減価償却費", 100000, 0],
        ["販管費の部", "修繕費", 50000, 30], ["販管費の部", "保険料", 30000, 0], ["販管費の部", "交際費", 100000, 30], ["販管費の部", "その他経費", 50000, 30],
        ["雑収入の部", "雑収入", 0, 0], ["雑収入の部", "受取配当金", 0, 0], ["雑損失の部", "雑損失", 0, 0], ["雑損失の部", "支払利息", 0, 0],
        ["特別利益の部", "固定資産売却益", 0, 0], ["特別損失の部", "固定資産売却損", 0, 0],
    ]
    st.session_state.pl_df = pd.DataFrame(init_pl, columns=["区分", "項目", "月額金額", "入出金サイト(日)"])

# モード管理フラグ
for key in ['edit_mode', 'pl_edit_mode', 'detail_edit_mode', 'calc_done']:
    if key not in st.session_state: st.session_state[key] = False

# --- 3. サイドバー設定 ---
st.sidebar.title("🛠 設定メニュー")
app_mode = st.sidebar.radio("シミュレーションモード選択", ["通常モード (受注案件ベース)", "詳細モード (損益計算書ベース)"])

# --- 4. 共通計算関数 ---
def calculate_row_cashflow(amount, start_date, end_date, condition, site_days, months_header):
    results = pd.Series(0.0, index=months_header)
    if not amount or amount <= 0 or pd.isna(start_date) or pd.isna(end_date): return results
    site_m = int(round(site_days / 30))
    s_month = pd.to_datetime(start_date).replace(day=1)
    e_month = pd.to_datetime(end_date).replace(day=1)
    duration = max(1, (e_month.year - s_month.year) * 12 + (e_month.month - s_month.month) + 1)
    
    def get_pay_m(base_date): return (base_date + relativedelta(months=site_m)).strftime("%Y/%m")

    if condition in ["出来高払い", "毎月均等払い"]:
        monthly_amt = amount // duration
        for i in range(duration):
            pay_m = get_pay_m(s_month + relativedelta(months=i))
            if pay_m in results.index: results[pay_m] += monthly_amt
        last_pay_m = get_pay_m(e_month)
        if last_pay_m in results.index: results[last_pay_m] += (amount - (monthly_amt * duration))
    elif condition == "完工時一括":
        pay_m = get_pay_m(e_month)
        if pay_m in results.index: results[pay_m] += amount
    return results

# --- 5. 通常モード (案件ベース) ---
if app_mode == "通常モード (受注案件ベース)":
    st.title("💰 通常シミュレーション (案件ベース)")
    with st.form("normal_input"):
        st.subheader("📋 受注案件入力表")
        edited_df = st.data_editor(st.session_state.df, num_rows="dynamic", use_container_width=True, hide_index=True,
                                  column_config={"開始日": st.column_config.DateColumn(format="YYYY/MM/DD"), "終了日": st.column_config.DateColumn(format="YYYY/MM/DD")})
        c1, c2, c3, c4 = st.columns(4)
        with c1: initial_cash = st.number_input("期首現金", value=10000000)
        with c2: monthly_sga = st.number_input("月間販管費", value=1500000)
        with c3: monthly_loan = st.number_input("月間借入返済", value=500000)
        with c4: start_period = st.date_input("開始月", datetime.today().replace(day=1))
        submitted = st.form_submit_button("🚀 案件情報を反映")

    if submitted or not st.session_state.calc_done:
        months_header = [(start_period + relativedelta(months=i)).strftime("%Y/%m") for i in range(12)]
        total_income = pd.Series(0.0, index=months_header)
        total_cost = pd.Series(0.0, index=months_header)
        for _, row in edited_df.dropna(subset=["案件名"]).iterrows():
            total_income += calculate_row_cashflow(row["受注金額"], row["開始日"], row["終了日"], row["入金条件"], row["サイト(日)"], months_header)
            total_cost += calculate_row_cashflow(row["受注金額"]*row["原価率"], row["開始日"], row["終了日"], row["入金条件"], row["サイト(日)"], months_header)
        
        st.session_state.manual_summary = pd.DataFrame({"入金合計": total_income, "原価支払合計": total_cost, "販管費": monthly_sga, "借入返済": monthly_loan, "短期借入金": 0.0}).T
        st.session_state.calc_done = True
        st.session_state.initial_cash = initial_cash
        st.session_state.months_header = months_header

# --- 6. 詳細モード (PLベース) ---
else:
    st.title("📊 詳細シミュレーション (PLベース)")
    with st.container(border=True):
        col_c1, col_c2, col_c3 = st.columns(3)
        with col_c1: initial_cash = st.number_input("期首現預金残高", value=20000000)
        with col_c2: monthly_loan_repay = st.number_input("借入金返済額 (月額)", value=1000000)
        with col_c3: start_month = st.date_input("シミュレーション開始月", datetime.today().replace(day=1))
    
    if not st.session_state.pl_edit_mode:
        st.dataframe(st.session_state.pl_df, use_container_width=True, hide_index=True)
        if st.button("📝 損益計算書を編集"): st.session_state.pl_edit_mode = True; st.rerun()
    else:
        edited_pl = st.data_editor(st.session_state.pl_df, num_rows="dynamic", use_container_width=True, hide_index=True)
        if st.button("💾 損益設定を保存"): st.session_state.pl_df = edited_pl; st.session_state.pl_edit_mode = False; st.rerun()

    if st.button("📉 詳細計算実行", type="primary"):
        months_header = [(start_month + relativedelta(months=i)).strftime("%Y/%m") for i in range(12)]
        df = st.session_state.pl_df
        # PL利益計算
        def get_s(cat): return df[df["区分"] == cat]["月額金額"].sum()
        pre_tax = (get_s("売上の部") + get_s("雑収入の部") + get_s("特別利益の部")) - (get_s("売上原価の部") + get_s("販管費の部") + get_s("雑損失の部") + get_s("特別損失の部"))
        tax = max(0, pre_tax * 0.19)
        
        # 資金繰り表生成
        detail_rows = {}
        for _, row in df.iterrows():
            site_m = int(round(row["入出金サイト(日)"] / 30))
            vals = [0.0]*12
            for m in range(12):
                if m + site_m < 12: vals[m + site_m] = row["月額金額"]
            if "減価償却費" in row["項目"]: vals = [0.0]*12
            detail_rows[row["項目"]] = vals
        
        detail_rows["法人税等"] = [tax/12]*12 # 簡易的に月額按分
        detail_rows["借入金返済"] = [monthly_loan_repay]*12
        detail_rows["短期借入金"] = [0.0]*12
        
        st.session_state.manual_summary = pd.DataFrame(detail_rows, index=months_header).T
        st.session_state.calc_done = True
        st.session_state.initial_cash = initial_cash
        st.session_state.months_header = months_header

# --- 7. 共通：資金繰り明細表・編集・グラフ ---
if st.session_state.calc_done:
    st.divider()
    st.subheader("📋 資金繰り明細表 (編集可能)")
    
    if not st.session_state.detail_edit_mode:
        if st.button("📝 明細を手動で編集する"): st.session_state.detail_edit_mode = True; st.rerun()
        ms = st.session_state.manual_summary
    else:
        ms = st.data_editor(st.session_state.manual_summary, use_container_width=True)
        if st.button("✅ 編集を確定"): st.session_state.manual_summary = ms; st.session_state.detail_edit_mode = False; st.rerun()

    # 最終計算
    # 詳細モードと通常モードで収支計算を共通化
    if app_mode == "通常モード (受注案件ベース)":
        monthly_cf = ms.loc["入金合計"] + ms.loc["短期借入金"] - ms.loc["原価支払合計"] - ms.loc["販管費"] - ms.loc["借入返済"]
    else:
        # 詳細モードはPL項目すべてを合算
        inc_items = st.session_state.pl_df[st.session_state.pl_df["区分"].str.contains("売上|雑収入|特別利益")]["項目"].tolist()
        exp_items = ms.index.difference(inc_items + ["短期借入金", "月次収支", "現預金残高"])
        monthly_cf = ms.loc[ms.index.isin(inc_items)].sum() + ms.loc["短期借入金"] - ms.loc[ms.index.isin(exp_items)].sum()

    cash_bal = monthly_cf.cumsum() + st.session_state.initial_cash
    final_view = pd.concat([ms, pd.DataFrame({"月次収支": monthly_cf, "現預金残高": cash_bal}, index=st.session_state.months_header).T])
    
    st.dataframe(final_view.style.format("{:,.0f}"), use_container_width=True)
    st.line_chart(cash_bal)

    # PDF生成
    def create_pdf():
        buffer = io.BytesIO()
        doc = SimpleDocTemplate(buffer, pagesize=landscape(A3), leftMargin=30, rightMargin=30)
        elements = [Paragraph(f"財務報告書 ({app_mode})", styles.getSampleStyleSheet()['Title'])]
        data = [["項目"] + st.session_state.months_header]
        for idx, row in final_view.iterrows(): data.append([idx] + [f"{v:,.0f}" for v in row.values])
        t = Table(data, hAlign='LEFT')
        t.setStyle(TableStyle([('FONT', (0,0), (-1,-1), FONT_NAME, 8), ('GRID', (0,0), (-1,-1), 0.5, colors.grey)]))
        elements.append(t)
        doc.build(elements)
        return buffer.getvalue()

    st.download_button("📄 PDFダウンロード", data=create_pdf(), file_name="report.pdf")
