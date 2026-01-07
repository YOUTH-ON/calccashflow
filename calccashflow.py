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
if 'pl_df' not in st.session_state:
    # 損益計算書の初期構造
    init_pl = [
        ["売上の部", "売上高", 10000000, 30],
        ["売上原価の部", "外注費", 3000000, 30], ["売上原価の部", "材料費", 1000000, 30],
        ["売上原価の部", "労務費", 2000000, 0], ["売上原価の部", "減価償却費", 500000, 0], ["売上原価の部", "その他経費", 200000, 30],
        ["販管費の部", "役員報酬", 1000000, 0], ["販管費の部", "人件費", 2000000, 0], ["販管費の部", "減価償却費", 100000, 0],
        ["販管費の部", "修繕費", 50000, 30], ["販管費の部", "保険料", 30000, 0], ["販管費の部", "交際費", 100000, 30], ["販管費の部", "その他経費", 50000, 30],
        ["雑収入の部", "雑収入", 10000, 0], ["雑収入の部", "受取配当金", 5000, 0],
        ["雑損失の部", "雑損失", 0, 0], ["雑損失の部", "支払利息", 20000, 0],
        ["特別利益の部", "固定資産売却益", 0, 0], ["特別損失の部", "固定資産売却損", 0, 0],
    ]
    st.session_state.pl_df = pd.DataFrame(init_pl, columns=["区分", "項目", "月額金額", "入出金サイト(日)"])

# モード管理フラグ
for key in ['pl_edit_mode', 'detail_edit_mode', 'detailed_sim_active', 'calc_done']:
    if key not in st.session_state: st.session_state[key] = False

# --- 3. メイン UI ---
st.title("📊 プロフェッショナル財務シミュレーター")

# ① 詳細シミュレートモードの切り替え
if not st.session_state.detailed_sim_active:
    if st.button("🚀 詳細シミュレートモードを起動"):
        st.session_state.detailed_sim_active = True
        st.rerun()
else:
    if st.button("🔙 通常モードへ戻る"):
        st.session_state.detailed_sim_active = False
        st.rerun()

if st.session_state.detailed_sim_active:
    # --- ② 損益計算書入力セクション ---
    st.header("1. 損益計算書 (PL) 設定")
    
    with st.container(border=True):
        col_c1, col_c2, col_c3 = st.columns(3)
        with col_c1: initial_cash = st.number_input("期首現預金残高 (円)", value=20000000, step=1000000)
        with col_c2: monthly_loan_repay = st.number_input("借入金返済額 (月額/円)", value=1000000, step=100000)
        with col_c3: start_month = st.date_input("シミュレーション開始月", datetime.today().replace(day=1))
    
    # ④ 損益計算書の編集モード管理
    if not st.session_state.pl_edit_mode:
        st.dataframe(st.session_state.pl_df, use_container_width=True, hide_index=True)
        if st.button("📝 損益計算書を編集"):
            st.session_state.pl_edit_mode = True
            st.rerun()
    else:
        st.info("項目を編集・追加してください。サイト0日は当月入出金、30日は翌月となります。")
        edited_pl = st.data_editor(st.session_state.pl_df, num_rows="dynamic", use_container_width=True, hide_index=True)
        if st.button("💾 損益設定を保存して計算準備"):
            st.session_state.pl_df = edited_pl
            st.session_state.pl_edit_mode = False
            st.rerun()

    # ③ 計算実行ボタン
    if st.button("📉 計算実行 (PL & 資金繰り生成)", type="primary"):
        st.session_state.calc_done = True
        st.session_state.detail_edit_mode = False

    if st.session_state.calc_done:
        # --- PL計算ロジック ---
        df = st.session_state.pl_df.copy()
        def get_sum(category): return df[df["区分"] == category]["月額金額"].sum()

        sales = get_sum("売上の部")
        cogs = get_sum("売上原価の部")
        gross_profit = sales - cogs
        sga = get_sum("販管費の部")
        op_profit = gross_profit - sga
        non_op_inc = get_sum("雑収入の部")
        non_op_exp = get_sum("雑損失の部")
        ord_profit = op_profit + non_op_inc - non_op_exp
        sp_inc = get_sum("特別利益の部")
        sp_exp = get_sum("特別損失の部")
        pre_tax_profit = ord_profit + sp_inc - sp_exp
        tax = max(0, pre_tax_profit * 0.19)
        net_profit = pre_tax_profit - tax

        # PL表示
        st.subheader("📋 損益計算結果 (月次ベース)")
        pl_summary = pd.DataFrame({
            "項目": ["売上高", "売上原価", "売上総利益", "販売管理費", "営業利益", "営業外収支", "経常利益", "特別損益", "税引前当期純利益", "法人税等(19%)", "税引後当期純利益"],
            "金額": [sales, cogs, gross_profit, sga, op_profit, non_op_inc - non_op_exp, ord_profit, sp_inc - sp_exp, pre_tax_profit, tax, net_profit]
        })
        st.table(pl_summary.style.format({"金額": "{:,.0f}"}))

        # --- ⑤ 資金繰り明細表生成 ---
        months_header = [(start_month + relativedelta(months=i)).strftime("%Y/%m") for i in range(12)]
        
        # 初回生成時のみセッションに保存
        if 'detailed_manual_summary' not in st.session_state or submitted:
            detail_rows = {}
            for _, row in df.iterrows():
                site_m = int(round(row["入出金サイト(日)"] / 30))
                monthly_values = [0.0] * 12
                for m in range(12):
                    if m + site_m < 12: # 簡易的なサイト反映
                        monthly_values[m + site_m] = row["月額金額"]
                # 減価償却費はキャッシュアウトしない
                if "減価償却費" in row["項目"]: monthly_values = [0.0] * 12
                detail_rows[row["項目"]] = monthly_values
            
            # 税金（簡易的に年度末ではなく毎月按分で表示。実務的には調整可）
            detail_rows["法人税等"] = [tax] * 12
            detail_rows["借入金返済"] = [monthly_loan_repay] * 12
            detail_rows["短期借入金"] = [0.0] * 12
            
            st.session_state.detailed_manual_summary = pd.DataFrame(detail_rows, index=months_header).T

        # ⑥ 明細表の編集フロー
        st.subheader("📅 資金繰り明細表 (12か月推移)")
        if not st.session_state.detail_edit_mode:
            if st.button("📝 明細表を編集する"):
                st.session_state.detail_edit_mode = True
                st.rerun()
            display_summary = st.session_state.detailed_manual_summary
        else:
            edited_detail = st.data_editor(st.session_state.detailed_manual_summary, use_container_width=True)
            if st.button("✅ 明細表の編集を完了する"):
                st.session_state.detailed_manual_summary = edited_detail
                st.session_state.detail_edit_mode = False
                st.rerun()
            display_summary = edited_detail

        # 計算（月次収支・残高）
        # 収支 = 売上 + 雑収 + 特利 + 短期借入 - (原価 + 販管 + 雑損 + 特損 + 税 + 返済) ※非資金項目除く
        income_items = df[df["区分"].isin(["売上の部", "雑収入の部", "特別利益の部"])]["項目"].tolist()
        expense_items = df[df["区分"].isin(["売上原価の部", "販管費の部", "雑損失の部", "特別損失の部"])]["項目"].tolist()
        expense_items += ["法人税等", "借入金返済"]
        
        # 非資金項目（減価償却）を除外
        income_data = display_summary.loc[display_summary.index.isin(income_items)].sum()
        expense_data = display_summary.loc[display_summary.index.isin(expense_items)].sum()
        short_loan = display_summary.loc["短期借入金"]
        
        monthly_cf = income_data + short_loan - expense_data
        cash_balance = monthly_cf.cumsum() + initial_cash

        # 最終ビュー表示
        final_summary = pd.concat([display_summary, pd.DataFrame({"月次収支": monthly_cf, "現預金残高": cash_balance}, index=months_header).T])
        st.dataframe(final_summary.style.format("{:,.0f}"), use_container_width=True)
        
        st.subheader("📈 現預金残高推移")
        st.line_chart(cash_balance)

        # PDF出力 (簡易版)
        def create_detailed_pdf():
            buffer = io.BytesIO()
            doc = SimpleDocTemplate(buffer, pagesize=landscape(A3), leftMargin=30, rightMargin=30)
            elements = []
            style_sheet = styles.getSampleStyleSheet()
            n_style = style_sheet['Normal']
            n_style.fontName = FONT_NAME
            
            elements.append(Paragraph("詳細財務シミュレーション報告書", style_sheet['Title']))
            elements.append(Spacer(1, 20))
            
            data = [["項目"] + months_header]
            for idx, row in final_summary.iterrows():
                data.append([idx] + [f"{v:,.0f}" for v in row.values])
            
            t = Table(data, hAlign='LEFT')
            t.setStyle(TableStyle([('FONT', (0,0), (-1,-1), FONT_NAME, 7), ('GRID', (0,0), (-1,-1), 0.5, colors.grey)]))
            elements.append(t)
            doc.build(elements)
            return buffer.getvalue()

        st.download_button("📄 PDF報告書をダウンロード", data=create_detailed_pdf(), file_name="detailed_report.pdf")
