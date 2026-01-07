import streamlit as st
import pandas as pd
from datetime import datetime
from dateutil.relativedelta import relativedelta
from reportlab.lib.pagesizes import A4, portrait
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
from reportlab.lib import colors, styles
import io
import os
import requests

st.set_page_config(layout="wide", page_title="財務シミュレーター Pro")

# --- 1. フォント設定 (PDF用) ---
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
CATS = ["売上の部", "売上原価の部", "販管費の部", "雑収益・雑損失の部", "特別利益・特別損失の部"]

# データの入れ物がない場合のみ初期化
if 'pl_data' not in st.session_state:
    st.session_state.pl_data = {
        "売上の部": pd.DataFrame([{"項目": "売上高", "金額(千円)": 10000, "入出金サイト(日)": 30}]),
        "売上原価の部": pd.DataFrame([{"項目": "外注費", "金額(千円)": 3000, "入出金サイト(日)": 30}]),
        "販管費の部": pd.DataFrame([{"項目": "役員報酬", "金額(千円)": 1000, "入出金サイト(日)": 0}]),
        "雑収益・雑損失の部": pd.DataFrame(columns=["項目", "金額(千円)", "入出金サイト(日)"]),
        "特別利益・特別損失の部": pd.DataFrame(columns=["項目", "金額(千円)", "入出金サイト(日)"])
    }

if 'normal_df' not in st.session_state:
    st.session_state.normal_df = pd.DataFrame([
        {"案件名": "案件A", "受注金額(千円)": 5000, "原価率": 0.7, "開始日": datetime.today().date(), "終了日": (datetime.today() + relativedelta(months=3)).date(), "入金条件": "出来高払い", "サイト(日)": 30}
    ])

if 'calc_done' not in st.session_state:
    st.session_state.calc_done = False

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

# --- 4. メインUI ---
st.sidebar.title("🛠 設定")
app_mode = st.sidebar.radio("モード選択", ["通常モード (受注案件)", "詳細モード (損益計算書)"])

if app_mode == "通常モード (受注案件)":
    st.title("💰 通常シミュレーション")
    st.session_state.normal_df = st.data_editor(st.session_state.normal_df, num_rows="dynamic", use_container_width=True, hide_index=True, key="ed_normal_v5")
    
    with st.container(border=True):
        c1, c2, c3, c4 = st.columns(4)
        init_cash = c1.number_input("期首現金(千円)", value=10000)
        m_sga = c2.number_input("月間販管費(千円)", value=1500)
        m_loan = c3.number_input("借入返済(月額/千円)", value=500)
        s_date = c4.date_input("開始月", datetime.today().replace(day=1))
        
    if st.button("🚀 計算実行", type="primary", use_container_width=True):
        st.session_state.months_header = [(s_date + relativedelta(months=i)).strftime("%Y/%m") for i in range(12)]
        st.session_state.initial_cash = init_cash
        inc, cost = pd.Series(0.0, index=st.session_state.months_header), pd.Series(0.0, index=st.session_state.months_header)
        for _, r in st.session_state.normal_df.dropna(subset=["案件名"]).iterrows():
            inc += calculate_cashflow_k(r["受注金額(千円)"], r["開始日"], r["終了日"], r["入金条件"], r["サイト(日)"], st.session_state.months_header)
            cost += calculate_cashflow_k(r["受注金額(千円)"]*r.get("原価率",0), r["開始日"], r["終了日"], r["入金条件"], r["サイト(日)"], st.session_state.months_header)
        st.session_state.manual_summary = pd.DataFrame({"入金合計": inc, "原価支払合計": cost, "販管費": [m_sga]*12, "借入返済": [m_loan]*12, "短期借入金": [0.0]*12}).T
        st.session_state.income_items, st.session_state.calc_done = ["入金合計"], True
        st.rerun()

else:
    st.title("📊 詳細シミュレーション")
    with st.container(border=True):
        c1, c2, c3 = st.columns(3)
        init_cash = c1.number_input("期首現預金残高(千円)", value=20000)
        m_loan_repay = c2.number_input("借入返済(月額/千円)", value=1000)
        s_date = c3.date_input("シミュレーション開始月", datetime.today().replace(day=1))

    st.subheader("損益計算書 各部の設定")
    st.info("💡 入力は自動保存されます。行を増やした後は、各項目を直接入力してください。")
    
    # 複数テーブルを同時に編集可能にする（通常モードと同じロジック）
    for cat in CATS:
        with st.expander(f"📌 {cat}", expanded=True):
            # keyを固定し、編集内容が即座にステートに書き戻されるようにする
            st.session_state.pl_data[cat] = st.data_editor(
                st.session_state.pl_data[cat],
                num_rows="dynamic",
                use_container_width=True,
                hide_index=True,
                key=f"editor_final_{cat}"
            )

    if st.button("📉 全体計算を実行", type="primary", use_container_width=True):
        st.session_state.months_header = [(s_date + relativedelta(months=i)).strftime("%Y/%m") for i in range(12)]
        st.session_state.initial_cash = init_cash
        detail, inc_list = {}, []
        for cat in CATS:
            # データのクレンジング（Noneを0にする）
            df_temp = st.session_state.pl_data[cat].copy()
            for _, r in df_temp.dropna(subset=["項目"]).iterrows():
                name, val = r["項目"], r["金額(千円)"] if pd.notna(r["金額(千円)"]) else 0
                site = r["入出金サイト(日)"] if pd.notna(r["入出金サイト(日)"]) else 0
                
                if cat in ["売上の部", "雑収益・雑損失の部", "特別利益・特別損失の部"]:
                    if not any(x in str(name) for x in ["損失", "損", "利息"]): inc_list.append(name)
                
                sm = int(round(site / 30)); vals = [0.0]*12
                for m in range(12): 
                    if m + sm < 12: vals[m + sm] = val
                detail[name] = vals
        
        detail.update({"法人税等": [0.0]*12, "借入金返済": [m_loan_repay]*12, "短期借入金": [0.0]*12})
        st.session_state.manual_summary = pd.DataFrame(detail, index=st.session_state.months_header).T
        st.session_state.income_items, st.session_state.calc_done = inc_list, True
        st.rerun()

# --- 5. 結果表示エリア ---
if st.session_state.calc_done:
    st.divider()
    st.subheader("📋 資金繰り明細表")
    
    # 計算後の明細表も直接編集可能にする
    st.session_state.manual_summary = st.data_editor(st.session_state.manual_summary, use_container_width=True, hide_index=False, key="res_ed_final")
    ms = st.session_state.manual_summary
    
    in_sum = ms.loc[ms.index.isin(st.session_state.income_items)].sum()
    out_items = ms.index.difference(list(st.session_state.income_items) + ["短期借入金", "月次収支", "現預金残高"])
    out_sum = ms.loc[out_items].sum()
    m_cf = in_sum + ms.loc["短期借入金"] - out_sum
    c_bal = m_cf.cumsum() + st.session_state.initial_cash
    
    final_view = pd.concat([ms, pd.DataFrame({"月次収支": m_cf, "現預金残高": c_bal}, index=st.session_state.months_header).T])
    st.dataframe(final_view.style.format("{:,.0f}"), use_container_width=True)
    st.line_chart(c_bal)

    # --- PDF/CSV 出力 ---
    def generate_pdf():
        buffer = io.BytesIO()
        doc = SimpleDocTemplate(buffer, pagesize=portrait(A4), leftMargin=30, rightMargin=30)
        elements = []
        style = styles.getSampleStyleSheet()
        elements.append(Paragraph("財務シミュレーション報告書", style['Title']))
        
        data_cf = [["項目"] + st.session_state.months_header]
        for idx, row in final_view.iterrows(): 
            data_cf.append([idx] + [f"{v:,.0f}" for v in row.values])
        
        t = Table(data_cf, hAlign='LEFT')
        t.setStyle(TableStyle([('FONT', (0,0), (-1,-1), FONT_NAME, 6), ('GRID', (0,0), (-1,-1), 0.5, colors.grey)]))
        elements.append(t)
        doc.build(elements)
        return buffer.getvalue()

    st.sidebar.divider()
    st.sidebar.subheader("📥 データの出力")
    st.sidebar.download_button("📄 PDFダウンロード", data=generate_pdf(), file_name=f"report_{datetime.now().strftime('%Y%m%d')}.pdf")
    st.sidebar.download_button("📊 CSVダウンロード", data=final_view.to_csv().encode('utf_8_sig'), file_name="data.csv", mime="text/csv")
