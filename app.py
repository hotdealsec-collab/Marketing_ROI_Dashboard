import numpy as np
import pandas as pd
import streamlit as st
import altair as alt
from rapidfuzz import process

# --------------------------------------------------
# 1. ページ設定 & スタイル
# --------------------------------------------------
st.set_page_config(page_title="Campaign Health Check", layout="wide")

st.markdown("""
<style>
.block-container { padding-top: 1.5rem; }
.small-note { color: #6b7280; font-size: 0.9rem; }
.stMetric { background-color: #f8fafc; padding: 15px; border-radius: 12px; border: 1px solid #e2e8f0; }
</style>
""", unsafe_allow_html=True)

# --------------------------------------------------
# 2. ロジック関数
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
# 3. データ処理エンジン
# --------------------------------------------------
def run_growth_audit(df_adj, df_int):
    # 内部データのキャンペーン名が空の行を除外
    df_int = df_int.dropna(subset=['campaign_name'])
    
    # キャンペーン名マッチング
    df_int['campaign_clean'] = df_int['campaign_name'].str.split(' \(').str[0].str.strip()
    adj_campaigns = df_adj['campaign_network'].dropna().unique().tolist()
    
    def find_match(name):
        match = process.extractOne(name, adj_campaigns, score_cutoff=80)
        return match[0] if match else None

    df_int['matched_campaign'] = df_int['campaign_clean'].apply(find_match)
    df = pd.merge(df_adj, df_int, left_on='campaign_network', right_on='matched_campaign', how='inner')
    
    # 指標計算
    df["cpi"] = df.apply(lambda x: safe_divide(x["cost"], x["installs"]), axis=1)
    df["activation_rate"] = df.apply(lambda x: safe_divide(x["ru_count"], x["user_count"]), axis=1)
    df["reading_intensity"] = df.apply(lambda x: safe_divide(x["product_count"], x["ru_count"]), axis=1)
    df["retention_d7_rate"] = df.apply(lambda x: safe_divide(x["d7_count"], x["ru_count"]), axis=1)
    df["bm_usage_rate"] = df.apply(lambda x: safe_divide(x["bm_user_count"], x["user_count"]), axis=1)
    df["payback_ratio"] = df.apply(lambda x: safe_divide(x["cost"], x["r_sales"]), axis=1)

    avg_cpi = df["cpi"].mean(); avg_intensity = df["reading_intensity"].mean(); avg_bm = df["bm_usage_rate"].mean()

    # スコアリング
    df["s_traffic"] = df["cpi"].apply(lambda x: "良好" if x <= avg_cpi*0.85 else ("普通" if x <= avg_cpi*1.15 else "注意")).map(map_score)
    df["s_activation"] = df["activation_rate"].apply(lambda x: "良好" if x >= 0.7 else ("普通" if x >= 0.5 else "注意")).map(map_score)
    df["s_intensity"] = df["reading_intensity"].apply(lambda x: "良好" if x >= avg_intensity*1.15 else ("普通" if x >= avg_intensity*0.85 else "注意")).map(map_score)
    df["s_retention"] = df["retention_d7_rate"].apply(lambda x: "良好" if x >= 0.25 else ("普通" if x >= 0.15 else "注意")).map(map_score)
    df["s_bm"] = df["bm_usage_rate"].apply(lambda x: "良好" if x >= avg_bm*1.15 else ("普通" if x >= avg_bm*0.85 else "注意")).map(map_score)
    df["s_payback"] = df["payback_ratio"].apply(lambda x: "良好" if x <= 1.2 else ("普通" if x <= 2.5 else "リスクあり")).map(map_score)

    df["growth_health_score"] = (df["s_traffic"]*0.1 + df["s_activation"]*0.15 + df["s_intensity"]*0.15 + df["s_retention"]*0.2 + df["s_bm"]*0.25 + df["s_payback"]*0.15).round(1)
    df["growth_category"] = df["growth_health_score"].apply(score_category)
    
    df["confidence_score"] = df.apply(lambda x: max(100 - (50 if x["cost"]==0 else 0) - (15 if str(x["os_name"]).lower()=="ios" else 0), 0), axis=1)
    
    return df

# --------------------------------------------------
# 4. メイン画面の構築
# --------------------------------------------------
st.title("Campaign Health Check")
st.markdown("<p class='small-note'>Performance × Measurement Confidence</p>", unsafe_allow_html=True)

st.sidebar.header("Upload")
adj_file = st.sidebar.file_uploader("Adjust CSV (External)", type="csv")
int_file = st.sidebar.file_uploader("Internal SQL CSV (Internal)", type="csv")

if adj_file and int_file:
    # データ読み込みとエラーハンドリング
    try:
        raw_adj = pd.read_csv(adj_file)
        raw_int = pd.read_csv(int_file)
        audit_df = run_growth_audit(raw_adj, raw_int)

        # Overview
        st.markdown("### Overview")
        k1, k2, k3 = st.columns(3)
        k1.metric("Average Growth Score", f"{audit_df['growth_health_score'].mean():.1f}")
        k2.metric("Average Confidence", f"{audit_df['confidence_score'].mean():.1f}")
        k3.metric("Campaigns", len(audit_df))

        # --- Filters (NaN対策済み) ---
        st.markdown("### Filters")
        f1, f2, f3, f4 = st.columns(4)
        
        # .dropna() を追加して NaN によるソートエラーを防止
        channel_list = ["All"] + sorted(audit_df['channel'].dropna().unique().tolist())
        os_list = ["All"] + sorted(audit_df['os_name'].dropna().unique().tolist())
        campaign_list = ["All"] + sorted(audit_df['campaign_network'].dropna().unique().tolist())
        category_list = ["All"] + sorted(audit_df['growth_category'].dropna().unique().tolist())

        sel_channel = f1.selectbox("Channel", channel_list)
        sel_os = f2.selectbox("OS", os_list)
        sel_campaign = f3.selectbox("Campaign", campaign_list)
        sel_category = f4.selectbox("Growth Category", category_list)

        # フィルタリング
        filtered_df = audit_df.copy()
        if sel_channel != "All": filtered_df = filtered_df[filtered_df['channel'] == sel_channel]
        if sel_os != "All": filtered_df = filtered_df[filtered_df['os_name'] == sel_os]
        if sel_campaign != "All": filtered_df = filtered_df[filtered_df['campaign_network'] == sel_campaign]
        if sel_category != "All": filtered_df = filtered_df[filtered_df['growth_category'] == sel_category]

        if not filtered_df.empty:
            # Visuals
            st.markdown("### Campaign Positioning")
            scatter = alt.Chart(filtered_df).mark_circle(size=140).encode(
                x=alt.X("growth_health_score:Q", title="Growth Health Score"),
                y=alt.Y("confidence_score:Q", title="Measurement Confidence Score"),
                color=alt.Color("growth_category:N", title="Category"),
                tooltip=["campaign_network", "channel", "growth_health_score"]
            ).properties(height=420).interactive()
            st.altair_chart(scatter, use_container_width=True)

            # Table
            st.markdown("### Campaign Table")
            display_cols = ["channel", "campaign_network", "os_name", "growth_health_score", "confidence_score", "growth_category"]
            st.dataframe(filtered_df[display_cols], use_container_width=True, height=500)
        else:
            st.warning("一致するデータがありません。フィルター条件を変更してください。")

    except Exception as e:
        st.error(f"データ処理中にエラーが発生しました: {e}")

else:
    st.info("サイドバーからAdjustデータと社内データの両方をアップロードしてください。")
