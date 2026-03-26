import numpy as np
import pandas as pd
import streamlit as st
import altair as alt
from rapidfuzz import process
import re

# --------------------------------------------------
# 1. ページ設定 & スタイル
# --------------------------------------------------
st.set_page_config(page_title="Piccoma Growth Audit Pro", layout="wide")

st.markdown("""
<style>
.block-container { padding-top: 1.5rem; }
.small-note { color: #6b7280; font-size: 0.9rem; }
.stMetric { background-color: #f8fafc; padding: 15px; border-radius: 12px; border: 1px solid #e2e8f0; }
</style>
""", unsafe_allow_html=True)

# --------------------------------------------------
# 2. ヘルパー関数
# --------------------------------------------------
def safe_divide(a, b):
    return a / b if (pd.notna(a) and pd.notna(b) and b != 0) else np.nan

def map_score(value):
    score_map = {"良好": 100, "普通": 60, "注意": 30, "リスクあり": 20, "不明": 50}
    return score_map.get(value, 50)

def score_category(score):
    if pd.isna(score): return "不明"
    if score >= 80: return "健全 (Healthy)"
    if score >= 60: return "観察 (Monitor)"
    if score >= 40: return "注意 (Warning)"
    return "要確認 (Critical)"

# --------------------------------------------------
# 3. データ処理エンジン (外部・内部の両方で重複排除)
# --------------------------------------------------
def run_growth_audit(df_adj, df_int):
    # --- 1. 外部データ(Adjust)のグループ化 ---
    # 同一キャンペーンがOSやメディアで分かれている場合を合算
    adj_grouped = df_adj.groupby('campaign_network').agg({
        'cost': 'sum',
        'installs': 'sum',
        'all_revenue': 'sum',
        'channel': lambda x: ', '.join(x.unique()), # 媒体名は結合
        'os_name': lambda x: ', '.join(x.unique())  # OS名も結合
    }).reset_index()

    # --- 2. 内部データの正規化とグループ化 ---
    df_int = df_int.copy().dropna(subset=['campaign_name'])
    def normalize_name(name):
        return re.sub(r'\s*\([^)]*\)', '', str(name)).strip()

    df_int['campaign_clean'] = df_int['campaign_name'].apply(normalize_name)
    
    int_grouped = df_int.groupby('campaign_clean').agg({
        'user_count': 'sum',
        'ru_count': 'sum',
        'd1_count': 'sum',
        'd7_count': 'sum',
        'product_count': 'sum',
        'bm_user_count': 'sum',
        'r_sales': 'sum'
    }).reset_index()

    # --- 3. マッチングとマージ ---
    adj_campaign_list = adj_grouped['campaign_network'].unique().tolist()
    
    def find_match(name):
        match = process.extractOne(name, adj_campaign_list, score_cutoff=75)
        return match[0] if match else None

    int_grouped['matched_campaign'] = int_grouped['campaign_clean'].apply(find_match)
    
    # 1:1でマージ
    df = pd.merge(adj_grouped, int_grouped, left_on='campaign_network', right_on='matched_campaign', how='inner')
    
    if df.empty: return df

    # --- 4. 指標計算とスコアリング ---
    df["cpi"] = df.apply(lambda x: safe_divide(x["cost"], x["installs"]), axis=1)
    df["activation_rate"] = df.apply(lambda x: safe_divide(x["ru_count"], x["user_count"]), axis=1)
    df["intensity"] = df.apply(lambda x: safe_divide(x["product_count"], x["ru_count"]), axis=1)
    df["retention_d7"] = df.apply(lambda x: safe_divide(x["d7_count"], x["ru_count"]), axis=1)
    df["bm_rate"] = df.apply(lambda x: safe_divide(x["bm_user_count"], x["user_count"]), axis=1)
    df["payback_ratio"] = df.apply(lambda x: safe_divide(x["cost"], x["r_sales"]), axis=1)

    avg_cpi = df["cpi"].mean(); avg_int = df["intensity"].mean(); avg_bm = df["bm_rate"].mean()

    df["s_traffic"] = df["cpi"].apply(lambda x: "良好" if x <= avg_cpi*0.85 else ("普通" if x <= avg_cpi*1.15 else "注意")).map(map_score)
    df["s_activation"] = df["activation_rate"].apply(lambda x: "良好" if x >= 0.7 else ("普通" if x >= 0.5 else "注意")).map(map_score)
    df["s_intensity"] = df["intensity"].apply(lambda x: "良好" if x >= avg_int*1.15 else ("普通" if x >= avg_int*0.85 else "注意")).map(map_score)
    df["s_retention"] = df["retention_d7"].apply(lambda x: "良好" if x >= 0.25 else ("普通" if x >= 0.15 else "注意")).map(map_score)
    df["s_bm"] = df["bm_rate"].apply(lambda x: "良好" if x >= avg_bm*1.15 else ("普通" if x >= avg_bm*0.85 else "注意")).map(map_score)
    df["s_payback"] = df["payback_ratio"].apply(lambda x: "良好" if x <= 1.2 else ("普通" if x <= 2.5 else "リスクあり")).map(map_score)

    df["growth_health_score"] = (df["s_traffic"]*0.1 + df["s_activation"]*0.15 + df["s_intensity"]*0.15 + df["s_retention"]*0.2 + df["s_bm"]*0.25 + df["s_payback"]*0.15).round(1)
    df["growth_category"] = df["growth_health_score"].apply(score_category)
    
    # 信頼度（簡易版）
    df["confidence_score"] = df.apply(lambda x: max(100 - (50 if x["cost"]==0 else 0), 0), axis=1)
    
    return df

# --------------------------------------------------
# 4. メイン UI
# --------------------------------------------------
st.title("Campaign Health Check")

st.sidebar.header("Upload")
adj_file = st.sidebar.file_uploader("Adjust CSV", type="csv")
int_file = st.sidebar.file_uploader("Internal SQL CSV", type="csv")

if adj_file and int_file:
    audit_df = run_growth_audit(pd.read_csv(adj_file), pd.read_csv(int_file))

    if audit_df.empty:
        st.error("❌ キャンペーンの紐付けができませんでした。")
    else:
        # Overview
        st.markdown("### Overview")
        k1, k2, k3 = st.columns(3)
        k1.metric("Average Growth Score", f"{audit_df['growth_health_score'].mean():.1f}")
        k2.metric("Average Confidence", f"{audit_df['confidence_score'].mean():.1f}")
        k3.metric("Campaigns (Unique)", len(audit_df))

        # Filters
        st.markdown("### Filters")
        f1, f2, f3 = st.columns(3)
        sel_ch = f1.selectbox("Channel", ["All"] + sorted(audit_df['channel'].unique().tolist()))
        sel_os = f2.selectbox("OS", ["All"] + sorted(audit_df['os_name'].unique().tolist()))
        sel_ct = f3.selectbox("Growth Category", ["All"] + sorted(audit_df['growth_category'].unique().tolist()))

        f_df = audit_df.copy()
        if sel_ch != "All": f_df = f_df[f_df['channel'].str.contains(sel_ch)]
        if sel_os != "All": f_df = f_df[f_df['os_name'].str.contains(sel_os)]
        if sel_ct != "All": f_df = f_df[f_df['growth_category'] == sel_ct]

        # Chart
        st.markdown("### Campaign Positioning")
        scatter = alt.Chart(f_df).mark_circle(size=140).encode(
            x=alt.X("growth_health_score:Q"), y=alt.Y("confidence_score:Q"),
            color="growth_category:N", tooltip=["campaign_network", "growth_health_score"]
        ).properties(height=400).interactive()
        st.altair_chart(scatter, width='stretch')

        # Table
        st.markdown("### Campaign Table")
        def highlight_low(val):
            return "background-color: rgba(239, 68, 68, 0.2); color: #ef4444;" if isinstance(val, (int, float)) and val < 60 else ""
        
        display_cols = ["campaign_network", "channel", "os_name", "growth_health_score", "growth_category", "bm_rate", "intensity", "retention_d7"]
        st.dataframe(f_df[display_cols].style.map(highlight_low, subset=["growth_health_score"]), width='stretch', height=500)
