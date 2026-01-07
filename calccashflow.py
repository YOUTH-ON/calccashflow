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

# --- 2. セッションステート初期化 ---
# カテゴリー定義
CATS = ["売上の部", "売上原価の部", "販管費の部", "雑収益・雑損失の部", "特別利益・特別損失の部"]

if 'pl_data' not in st.session_state:
    st.session_state.pl_data = {
        "売上の部": pd.DataFrame([["売上高", 10000, 30]], columns=["項目", "金額(千円)", "入出金サイト(日)"]),
        "売上原価の部": pd.DataFrame([["外注費", 3000, 30], ["材料費", 1000, 30]], columns=["項目", "金額(千円)", "入出金サイト(日)"]),
        "販管費の部": pd.DataFrame([["役員報酬", 1000, 0], ["人件費", 2000, 0]], columns=["項目", "金額(千円)", "入出金サイト(日)"]),
        "雑収益・雑損失の部": pd.DataFrame([["受取配当金", 10, 0], ["支払利息", 20, 0]], columns=["項目", "金額(千円)", "入出金サイト(日)"]),
        "特別利益・特別損失の部": pd.DataFrame([["固定資産売却益", 0, 0]], columns=["項目", "金額(千円)", "入出金サイト(日)"])
    }

if 'df' not in st.session_state:
    st.session_state.df = pd.DataFrame([{"案件名": "案件A", "受注金額(千円)": 5000, "原価率": 0.7, "開始日": datetime.today().date(), "終了日": (datetime.today() + relativedelta(months=3)).date(), "入金条件": "出来高払い", "サイト(日)": 30}])

for key in ['pl_edit_mode', 'detail_edit_mode', 'calc_done']:
    if key not in st.session_state: st.session_state[key] = False

# --- 3. サイドバー設定 ---
st.sidebar.title("🛠 設定メニュー")
st.sidebar.info("単位：千円")
app_mode = st.sidebar.radio("モード選択", ["通常モード (受注案件)", "詳細モード (損益計算書)"])

# --- 4. 詳細モード (PLベース) ---
if app_mode == "詳細モード (損益計算書)":
    st.title("📊 詳細シミュレーション (千円単位)")
    
    col_c1, col_c2, col_c3 = st.columns(3)
    with col_c1: initial_cash = st.number_input("期首現預金残高(千円)", value=20000)
    with col_c2: m_loan_repay = st.number_input("借入返済(月額/千円)", value=1000)
    with col_c3: s_month = st.date_input("シミュレーション開始月", datetime.today().replace(day=1))

    st.subheader("損益計算書 各部の設定")

    if not st.session_state.pl_edit_mode:
        for cat in CATS:
            st.write(f"#### {cat}")
            st.dataframe(st.session_state.pl_data[cat], use_container_width=True, hide_index=True)
        if st.button("📝 損益計算書を編集する"):
            st.session_state.pl_edit_mode = True
            st.rerun()
    else:
        st.success("表の最下行をクリックして新しい項目を追加できます。")
        for cat in CATS:
            st.write(f"#### {cat}")
            # num_rows="dynamic" で行追加を有効化
            st.session_state.pl_data[cat] = st.data_editor(
                st.session_state.pl_data[cat],
                num_rows="dynamic",
                use_container_width=True,
                hide_index=True,
                key=f"editor_{cat}"
            )
        if st.button("💾 編集を保存して計算準備"):
            st.session_state.pl_edit_mode = False
            st.rerun()

    if st.button("📉 計算実行 (PL & 資金繰り生成)", type="primary"):
        st.session_state.calc_done = True
        st.session_state.detail_edit_mode = False
        st.session_state.months_header = [(s_month + relativedelta(months=i)).strftime("%Y/%m") for i in range(12)]
        st.session_state.initial_cash = initial_cash

        # --- 資金繰り明細の生成 ---
        detail = {}
        total_pre_tax = 0
        
        for cat in CATS:
            df_cat = st.session_state.pl_data[cat]
            for _, r in df_cat.dropna(subset=["項目"]).iterrows():
                # 利益計算用のロジック
                val = r["金額(千円)"]
                if cat in ["売上の部", "雑収益・雑損失の部", "特別利益・特別損失の部"]:
                    # 雑収益などは「項目名」で判断（本来はさらに細分化すべきですが簡易化）
                    if "損失" in r["項目"] or "損" in r["項目"] or "利息" in r["項目"]: total_pre_tax -= val
                    else: total_pre_tax += val
                else:
                    total_pre_tax -= val

                # 資金繰り行の生成
                sm = int(round(r["入出金サイト(日)"] / 30))
                vals = [0.0]*12
                for m in range(12):
                    if m + sm < 12: vals[m + sm] = val
                
                # 非資金項目（減価償却費）の除外
                if "減価償却" in r["項目"]: vals = [0.0]*12
                
                detail[r["項目"]] = vals

        # 法人税と借入
        tax_total = max(0, total_pre_tax * 0.19)
        detail["法人税等"] = [tax_total / 12] * 12
        detail["借入金返済"] = [m_loan_repay] * 12
        detail["短期借入金"] = [0.0] * 12
        
        st.session_state.manual_summary = pd.DataFrame(detail, index=st.session_state.months_header).T

# --- 5. 通常モード (中略: 前回と同様) ---
elif app_mode == "通常モード (受注案件)":
    st.title("💰 通常シミュレーション (千円単位)")
    # (既存の通常モードロジック)
    st.info("案件ベースのシミュレーションです。")
    # ... (前回の通常モードコードをここに挿入) ...

# --- 6. 共通：結果表示と明細編集 ---
if st.session_state.get('calc_done'):
    st.divider()
    st.subheader(f"📋 資金繰り明細表 (12か月推移)")
    
    if not st.session_state.detail_edit_mode:
        if st.button("📝 資金繰り明細を手動で修正する"):
            st.session_state.detail_edit_mode = True
            st.rerun()
        ms = st.session_state.manual_summary
    else:
        ms = st.data_editor(st.session_state.manual_summary, use_container_width=True, key="detail_editor")
        if st.button("✅ 修正を完了して反映"):
            st.session_state.manual_summary = ms
            st.session_state.detail_edit_mode = False
            st.rerun()

    # 収支計算
    # 収入項目の抽出（PL設定の「売上の部」などに含まれる項目を収入とみなす）
    income_list = st.session_state.pl_data["売上の部"]["項目"].tolist() + ["雑収入", "受取配当金", "固定資産売却益"]
    
    in_sum = ms.loc[ms.index.isin(income_list)].sum()
    # 支出は収入と「短期借入金、収支、残高」以外のすべて
    out_items = ms.index.difference(income_list + ["短期借入金", "月次収支", "現預金残高"])
    out_sum = ms.loc[out_items].sum()
    
    monthly_cf = in_sum + ms.loc["短期借入金"] - out_sum
    cash_bal = monthly_cf.cumsum() + st.session_state.initial_cash
    
    final_view = pd.concat([ms, pd.DataFrame({"月次収支": monthly_cf, "現預金残高": cash_bal}, index=st.session_state.months_header).T])
    
    st.dataframe(final_view.style.format("{:,.0f}"), use_container_width=True)
    
    st.subheader("📈 現預金残高推移 (千円)")
    st.line_chart(cash_bal)
