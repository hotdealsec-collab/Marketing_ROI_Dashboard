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
# 3. データ処理エンジン (重複排除 & 6項目評価)
# --------------------------------------------------
def run_growth_audit(df_adj, df_int):
    df_adj = df_adj.copy()
    df_int = df_int.copy().dropna(subset=['campaign_name'])
    
    # キャンペーン名の正規化（括弧内のIDを削除）
    def normalize_name(name):
        return re.sub(r'\s*\([^)]*\)', '', str(name)).strip()

    df_int['campaign_clean'] = df_int['campaign_name'].apply(normalize_name)

    # 🔴 重複排除: 内部データをキャンペーン名ごとにグループ化して合算
    df_int_grouped = df_int.groupby('campaign_clean').agg({
        'user_count': 'sum',
        'ru_count': 'sum',
        'd1_count': 'sum',
        'd7_count': 'sum',
        'd30_count': 'sum',
        'product_count': 'sum',
        'pu_count': 'sum',
        'bm_user_count': 'sum',
        'r_sales': 'sum'
    }).reset_index()

    adj_campaigns = df_adj['campaign_network'].dropna().unique().tolist()
    
    # ファジーマッチングによる紐付け
    def find_match(name):
        match = process.extractOne(name, adj_campaigns, score_cutoff=75)
        return match[0] if match else None

    df_int_grouped['matched_campaign'] = df_int_grouped['campaign_clean'].apply(find_match)
    
    # 外部(Adjust)と内部データのマージ
    df = pd.merge(df_adj, df_int_grouped, left_on='campaign_network', right_on='matched_campaign', how='inner')
    
    if df.empty: return df

    # --- 指標計算 (6要素) ---
    df["cpi"] = df.apply(lambda x: safe_divide(x["cost"], x["installs"]), axis=1) # 1. Traffic
    df["activation_rate"] = df.apply(lambda x: safe_divide(x["ru_count"], x["user_count"]), axis=1) # 2. Activation
    df["intensity"] = df.apply(lambda x: safe_divide(x["product_count"], x["ru_count"]), axis=1) # 3. Intensity
    df["retention_d7"] = df.apply(lambda x: safe_divide(x["d7_count"], x["ru_count"]), axis=1) # 4. Retention
    df["bm_rate"] = df.apply(lambda x: safe_divide(x["bm_user_count"], x["user_count"]), axis=1) # 5. BM Contribution
    df["payback_ratio"] = df.apply(lambda x: safe_divide(x["cost"], x["r_sales"]), axis=1) # 6. Payback

    # 相対評価の基準値
    avg_cpi = df["cpi"].mean(); avg_int = df["intensity"].mean(); avg_bm = df["bm_rate"].mean()

    # 個別スコアリング
    df["s_traffic"] = df["cpi"].apply(lambda x: "良好" if x <= avg_cpi*0.85 else ("普通" if x <= avg_cpi*1.15 else "注意")).map(map_score)
    df["s_activation"] = df["activation_rate"].apply(lambda x: "良好" if x >= 0.7 else ("普通" if x >= 0.5 else "注意")).map(map_score)
    df["s_intensity"] = df["intensity"].apply(lambda x: "良好" if x >= avg_int*1.15 else ("普通" if x >= avg_int*0.85 else "注意")).map(map_score)
    df["s_retention"] = df["retention_d7"].apply(lambda x: "良好" if x >= 0.25 else ("普通" if x >= 0.15 else "注意")).map(map_score)
    df["s_bm"] = df["bm_rate"].apply(lambda x: "良好" if x >= avg_bm*1.15 else ("普通" if x >= avg_bm*0.85 else "注意")).map(map_score)
    df["s_payback"] = df["payback_ratio"].apply(lambda x: "良好" if x <= 1.2 else ("普通" if x <= 2.5 else "リスクあり")).map(map_score)

    # 総合グローススコア (重み付け)
    df["growth_health_score"] = (
        df["s_traffic"] * 0.10 +
        df["s_activation"] * 0.15 +
        df["s_intensity"] * 0.15 +
        df["s_retention"] * 0.20 +
        df["s_bm"] * 0.25 +
        df["s_payback"] * 0.15
    ).round(1)
    
    df["growth_category"] = df["growth_health_score"].apply(score_category)
    df["confidence_score"] = df.apply(lambda x: max(100 - (50 if x["cost"]==0 else 0) - (15 if str(x.get("os_name", "")).lower()=="ios" else 0), 0), axis=1)
    
    return df

# --------------------------------------------------
# 4. メイン UI
# --------------------------------------------------
st.title("Campaign Health Check")

st.sidebar.header("Upload")
adj_file = st.sidebar.file_uploader("Adjust CSV (External)", type="csv")
int_file = st.sidebar.file_uploader("Internal SQL CSV (Internal)", type="csv")

# スコア根拠の表示
st.sidebar.markdown("---")
with st.sidebar.expander("ℹ️ Growth Scoreの算出根拠", expanded=False):
    st.markdown("""
    総合スコアは以下の比率で構成されています：
    - **Traffic (10%)**: CPI効率
    - **Activation (15%)**: 作品閲覧転換率
    - **Intensity (15%)**: 平均閲覧作品数
    - **Retention (20%)**: D7維持率
    - **BM Contribution (25%)**: BM利用率
    - **Payback (15%)**: 投資回収効率
    """)

if adj_file and int_file:
    # データ読み込み
    audit_df = run_growth_audit(pd.read_csv(adj_file), pd.read_csv(int_file))

    if audit_df.empty:
        st.error("❌ キャンペーンの紐付け結果が0件です。ファイルの内容を確認してください。")
    else:
        # KPI サマリー
        st.markdown("### Overview")
        k1, k2, k3 = st.columns(3)
        k1.metric("Average Growth Score", f"{audit_df['growth_health_score'].mean():.1f}")
        k2.metric("Average Confidence", f"{audit_df['confidence_score'].mean():.1f}")
        k3.metric("Campaigns", len(audit_df))

        # --- メイン画面フィルター ---
        st.markdown("### Filters")
        f1, f2, f3, f4 = st.columns(4)
        
        def get_opts(df, col):
            return ["All"] + sorted(df[col].dropna().unique().tolist())

        sel_ch = f1.selectbox("Channel", get_opts(audit_df, 'channel'))
        sel_os = f2.selectbox("OS", get_opts(audit_df, 'os_name'))
        sel_cp = f3.selectbox("Campaign", get_opts(audit_df, 'campaign_network'))
        sel_ct = f4.selectbox("Growth Category", get_opts(audit_df, 'growth_category'))

        # フィルタリング適用
        f_df = audit_df.copy()
        if sel_ch != "All": f_df = f_df[f_df['channel'] == sel_ch]
        if sel_os != "All": f_df = f_df[f_df['os_name'] == sel_os]
        if sel_cp != "All": f_df = f_df[f_df['campaign_network'] == sel_cp]
        if sel_ct != "All": f_df = f_df[f_df['growth_category'] == sel_ct]

        # ポジショニングマトリクス
        st.markdown("### Campaign Positioning")
        scatter = alt.Chart(f_df).mark_circle(size=140).encode(
            x=alt.X("growth_health_score:Q", title="Growth Health Score"),
            y=alt.Y("confidence_score:Q", title="Measurement Confidence Score"),
            color=alt.Color("growth_category:N", title="Category"),
            tooltip=["campaign_network", "growth_health_score", "confidence_score"]
        ).properties(height=420).interactive()
        st.altair_chart(scatter, width='stretch')

        # キャンペーン詳細テーブル
        st.markdown("### Campaign Table")
        
        def highlight_low(val):
            return "background-color: rgba(239, 68, 68, 0.2); color: #ef4444;" if isinstance(val, (int, float)) and val < 60 else ""
        
        # 表示項目の選択（グローススコア関連を含む）
        display_cols = [
            "channel", "campaign_network", "os_name", 
            "growth_health_score", "growth_category", "confidence_score",
            "bm_rate", "retention_d7", "intensity"
        ]
        
        st.dataframe(
            f_df[display_cols].style.map(highlight_low, subset=["growth_health_score", "confidence_score"]), 
            width='stretch', 
            height=500
        )

else:
    st.info("左側のメニューからAdjustデータと社内データの両方をアップロードしてください。")
