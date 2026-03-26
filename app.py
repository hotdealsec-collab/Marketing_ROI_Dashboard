import numpy as np
import pandas as pd
import streamlit as st
import altair as alt
from rapidfuzz import process

# --------------------------------------------------
# ページ設定
# --------------------------------------------------
st.set_page_config(page_title="Piccoma Growth Audit Pro", layout="wide")

st.markdown("""
<style>
.block-container { padding-top: 1.8rem; }
.small-note { color: #6b7280; font-size: 0.9rem; }
.stMetric { background-color: #f8fafc; padding: 15px; border-radius: 10px; border: 1px solid #e2e8f0; }
</style>
""", unsafe_allow_html=True)

# --------------------------------------------------
# スコアリング・ロ직 (6개 항목으로 확장)
# --------------------------------------------------
def safe_divide(a, b):
    return a / b if (pd.notna(a) and pd.notna(b) and b != 0) else np.nan

def map_score(value):
    score_map = {"良好": 100, "普通": 60, "注意": 30, "リスクあり": 20, "不明": 50}
    return score_map.get(value, 50)

def score_category(score):
    if score >= 80: return "健全 (Healthy)"
    if score >= 60: return "観察 (Monitor)"
    if score >= 40: return "注意 (Warning)"
    return "要確認 (Critical)"

# --------------------------------------------------
# データ処理エンジン
# --------------------------------------------------
def run_growth_audit_pro(df_adj, df_int):
    # キャンペーン名マッチング
    df_int['campaign_clean'] = df_int['campaign_name'].str.split(' \(').str[0].str.strip()
    adj_campaigns = df_adj['campaign_network'].unique().tolist()
    
    def find_match(name):
        match = process.extractOne(name, adj_campaigns, score_cutoff=80)
        return match[0] if match else None

    df_int['matched_campaign'] = df_int['campaign_clean'].apply(find_match)
    df = pd.merge(df_adj, df_int, left_on='campaign_network', right_on='matched_campaign', how='inner')
    
    # --- 指標計算 (6개 핵심 지표) ---
    df["cpi"] = df.apply(lambda x: safe_divide(x["cost"], x["installs"]), axis=1) # Traffic
    df["activation_rate"] = df.apply(lambda x: safe_divide(x["ru_count"], x["user_count"]), axis=1) # Activation
    df["reading_intensity"] = df.apply(lambda x: safe_divide(x["product_count"], x["ru_count"]), axis=1) # Intensity (NEW)
    df["retention_d7_rate"] = df.apply(lambda x: safe_divide(x["d7_count"], x["ru_count"]), axis=1) # Retention (NEW)
    df["bm_usage_rate"] = df.apply(lambda x: safe_divide(x["bm_user_count"], x["user_count"]), axis=1) # BM Contribution
    df["payback_ratio"] = df.apply(lambda x: safe_divide(x["cost"], x["r_sales"]), axis=1) # Payback

    # --- 相対評価 & スコアリング ---
    avg_cpi = df["cpi"].mean(); avg_intensity = df["reading_intensity"].mean()
    avg_bm = df["bm_usage_rate"].mean()

    # 1. Traffic Score
    df["s_traffic"] = df["cpi"].apply(lambda x: "良好" if x <= avg_cpi*0.85 else ("普通" if x <= avg_cpi*1.15 else "注意")).map(map_score)
    # 2. Activation Score
    df["s_activation"] = df["activation_rate"].apply(lambda x: "良好" if x >= 0.7 else ("普通" if x >= 0.5 else "注意")).map(map_score)
    # 3. Intensity Score (NEW)
    df["s_intensity"] = df["reading_intensity"].apply(lambda x: "良好" if x >= avg_intensity*1.15 else ("普通" if x >= avg_intensity*0.85 else "注意")).map(map_score)
    # 4. Retention Score (NEW)
    df["s_retention"] = df["retention_d7_rate"].apply(lambda x: "良好" if x >= 0.25 else ("普通" if x >= 0.15 else "注意")).map(map_score)
    # 5. BM Score
    df["s_bm"] = df["bm_usage_rate"].apply(lambda x: "良好" if x >= avg_bm*1.15 else ("普通" if x >= avg_bm*0.85 else "注意")).map(map_score)
    # 6. Payback Score
    df["s_payback"] = df["payback_ratio"].apply(lambda x: "良好" if x <= 1.2 else ("普通" if x <= 2.5 else "リスクあり")).map(map_score)

    # 総合スコア計算 (가중치 적용)
    df["growth_health_score"] = (
        df["s_traffic"] * 0.10 +
        df["s_activation"] * 0.15 +
        df["s_intensity"] * 0.15 +
        df["s_retention"] * 0.20 +
        df["s_bm"] * 0.25 +
        df["s_payback"] * 0.15
    ).round(1)
    
    df["growth_category"] = df["growth_health_score"].apply(score_category)

    # 信頼度スコア (기존 로직 유지)
    def calc_confidence(row):
        score = 100
        if row["cost"] == 0: score -= 50
        if str(row["os_name"]).lower() == "ios": score -= 15
        return max(score, 0)
    df["confidence_score"] = df.apply(calc_confidence, axis=1)
    
    return df

# --------------------------------------------------
# UI 構築
# --------------------------------------------------
st.title("🚀 Piccoma Growth Health Audit")
st.markdown("<p class='small-note'>6つの主要指標に基づき、キャンペーンの真の価値を多角的に診断します。</p>", unsafe_allow_html=True)

# サイドバー
st.sidebar.header("📁 CSVアップロード")
adj_file = st.sidebar.file_uploader("Adjust (外部)", type="csv")
int_file = st.sidebar.file_uploader("Internal SQL (内部)", type="csv")

if adj_file and int_file:
    audit_df = run_growth_audit_pro(pd.read_csv(adj_file), pd.read_csv(int_file))

    # --- フィルター ---
    st.sidebar.divider()
    st.sidebar.header("🔍 フィルター")
    selected_channel = st.sidebar.multiselect("媒体 (Channel)", audit_df['channel'].unique(), default=audit_df['channel'].unique())
    selected_os = st.sidebar.multiselect("OS", audit_df['os_name'].unique(), default=audit_df['os_name'].unique())
    
    filtered_df = audit_df[(audit_df['channel'].isin(selected_channel)) & (audit_df['os_name'].isin(selected_os))]

    # --- KPI サマリー ---
    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Avg Growth Score", f"{filtered_df['growth_health_score'].mean():.1f}")
    m2.metric("Avg Reading Intensity", f"{filtered_df['reading_intensity'].mean():.2f}")
    m3.metric("Avg D7 Retention", f"{filtered_df['retention_d7_rate'].mean()*100:.1f}%")
    m4.metric("BM Usage Rate", f"{filtered_df['bm_usage_rate'].mean()*100:.1f}%")

    st.divider()

    # --- 可視화 ---
    c1, c2 = st.columns([1.5, 1])
    with c1:
        st.subheader("📍 健全性マトリクス (Growth vs Confidence)")
        scatter = alt.Chart(filtered_df).mark_circle(size=180).encode(
            x=alt.X("growth_health_score:Q", title="Growth Health (質)"),
            y=alt.Y("confidence_score:Q", title="Measurement Confidence (信頼)"),
            color="growth_category:N",
            tooltip=["campaign_network", "growth_health_score", "reading_intensity", "bm_usage_rate"]
        ).properties(height=450).interactive()
        st.altair_chart(scatter, use_container_width=True)
    
    with c2:
        st.subheader("📊 媒体別・重要指標スコア")
        radar_data = filtered_df.groupby('channel')[['s_intensity', 's_retention', 's_bm']].mean().reset_index()
        st.dataframe(radar_data.style.background_gradient(cmap='Blues'), use_container_width=True)

    # --- 詳細テーブル ---
    st.subheader("📋 キャンペーン診断詳細（6要素スコア）")
    def highlight_low(val):
        return "color: #ef4444; font-weight: bold;" if isinstance(val, (int, float)) and val < 60 else ""

    display_cols = ["campaign_network", "growth_health_score", "s_traffic", "s_activation", "s_intensity", "s_retention", "s_bm", "s_payback"]
    st.dataframe(filtered_df[display_cols].style.applymap(highlight_low), use_container_width=True)

else:
    st.info("左右のCSVファイルをアップロードしてください。")
