import streamlit as st
import pandas as pd
from datetime import datetime
from dateutil.relativedelta import relativedelta
import io

st.set_page_config(layout="wide", page_title="財務シミュレーター Pro")

# --- 1. セッションステート初期化 ---
CATS = ["売上の部", "売上原価の部", "販管費の部", "雑収益・雑損失の部", "特別利益・特別損失の部"]

if 'pl_data' not in st.session_state:
    st.session_state.pl_data = {
        "売上の部": pd.DataFrame([{"項目": "売上高", "金額(千円)": 10000, "入出金サイト(日)": 30}]),
        "売上原価の部": pd.DataFrame([{"項目": "外注費", "金額(千円)": 3000, "入出金サイト(日)": 30}]),
        "販管費の部": pd.DataFrame([{"項目": "役員報酬", "金額(千円)": 1000, "入出金サイト(日)": 0}]),
        "雑収益・雑損失の部": pd.DataFrame(columns=["項目", "金額(千円)", "入出金サイト(日)"]),
        "特別利益・特別損失の部": pd.DataFrame(columns=["項目", "金額(千円)", "入出金サイト(日)"])
    }
    for cat in CATS:
        st.session_state[f"edit_mode_{cat}"] = False

if 'normal_df' not in st.session_state:
    st.session_state.normal_df = pd.DataFrame([
        {"案件名": "案件A", "受注金額(千円)": 5000, "原価率": 0.7, "開始日": datetime.today().date(), "終了日": (datetime.today() + relativedelta(months=3)).date(), "入金条件": "出来高払い", "サイト(日)": 30}
    ])

# --- 2. 補助関数 (None対策) ---
def finalize_df(df):
    """None値を自動的に0や空文字で埋めてデータ型を安定させる"""
    df = df.copy()
    if "項目" in df.columns:
        df["項目"] = df["項目"].fillna("新項目")
    if "金額(千円)" in df.columns:
        df["金額(千円)"] = pd.to_numeric(df["金額(千円)"]).fillna(0)
    if "入出金サイト(日)" in df.columns:
        df["入出金サイト(日)"] = pd.to_numeric(df["入出金サイト(日)"]).fillna(0)
    return df

# --- 3. メインUI ---
st.sidebar.title("🛠 設定")
app_mode = st.sidebar.radio("モード選択", ["通常モード (受注案件)", "詳細モード (損益計算書)"])

if app_mode == "通常モード (受注案件)":
    st.title("💰 通常シミュレーション")
    st.session_state.normal_df = st.data_editor(st.session_state.normal_df, num_rows="dynamic", use_container_width=True, hide_index=True, key="normal_ed")
    
    if st.button("🚀 計算実行", type="primary"):
        st.session_state.calc_done = True
        st.rerun()

else:
    st.title("📊 詳細シミュレーション")
    st.subheader("損益計算書 各部の設定")
    
    for cat in CATS:
        with st.expander(f"📌 {cat}", expanded=True):
            col_left, col_right = st.columns([0.85, 0.15])
            
            # 編集・保存ボタンの処理
            if not st.session_state[f"edit_mode_{cat}"]:
                if col_right.button("編集", key=f"btn_edit_{cat}"):
                    st.session_state[f"edit_mode_{cat}"] = True
                    st.rerun()
                # 表示モード
                st.dataframe(st.session_state.pl_data[cat], use_container_width=True, hide_index=True)
            else:
                if col_right.button("保存", key=f"btn_save_{cat}"):
                    # 保存時にNone値をクレンジング
                    st.session_state.pl_data[cat] = finalize_df(st.session_state.pl_data[cat])
                    st.session_state[f"edit_mode_{cat}"] = False
                    st.rerun()
                # 編集モード
                # 編集中のデータ変更を即座に反映させるため、セッションに直接書き込む
                st.session_state.pl_data[cat] = st.data_editor(
                    st.session_state.pl_data[cat], 
                    num_rows="dynamic", 
                    use_container_width=True, 
                    hide_index=True, 
                    key=f"editor_v4_{cat}"
                )

    st.divider()
    if st.button("📉 全体計算を実行", type="primary", use_container_width=True):
        st.success("計算を実行しました。ページ下部を確認してください。")
        st.session_state.calc_done = True

# --- 4. 結果表示エリア (計算ロジック) ---
if st.session_state.get('calc_done', False):
    # ここに以前作成した計算ロジックとPDF/CSV出力コードを記述
    st.write("### 資金繰りシミュレーション結果")
    # ※計算処理部分は前回の安定版と同様のため、ここではUI改善を優先して省略
