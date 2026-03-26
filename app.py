import numpy as np
import pandas as pd
import streamlit as st
import altair as alt
from rapidfuzz import process

# --------------------------------------------------
# Page Config & Styles
# --------------------------------------------------
st.set_page_config(page_title="Piccoma Campaign Health Check", layout="wide")

st.markdown("""
<style>
.block-container { padding-top: 1.8rem; padding-bottom: 2rem; }
.small-note { color: #6b7280; font-size: 0.9rem; }
.mono-box { 
    background-color: #111827; color: #f9fafb; padding: 1rem 1.2rem; 
    border-radius: 12px; border: 1px solid #1f2937; font-family: monospace; font-size: 0.85rem; 
}
.section-caption { color: #9ca3af; font-size: 0.88rem; margin-bottom: 0.8rem; }
</style>
""", unsafe_allow_html=True)

# --------------------------------------------------
# Helpers & Scoring Logic (User Template 기반)
# --------------------------------------------------
def safe_divide(a, b):
    return a / b if (pd.notna(a) and pd.notna(b) and b != 0) else np.nan

def rate_relative_low_is_good(value, avg_value):
    if pd.isna(value) or pd.isna(avg_value): return "不明"
    if value <= avg_value * 0.85: return "良好"
    elif value <= avg_value * 1.15: return "普通"
    return "注意"

def rate_relative_high_is_good(value, avg_value):
    if pd.isna(value) or pd.isna(avg_value): return "不明"
    if value >= avg_value * 1.15: return "良好"
    elif value >= avg_value * 0.85: return "普通"
    return "注意"

def map_score(value):
    score_map = {"良好": 100, "普通": 60, "注意": 30, "リスクあり": 20, "不明": 50}
    return score_map.get(value, 50)

def score_category(score):
    if score >= 80: return "健全"
    if score >= 60: return "観察"
    if score >= 40: return "注意"
    return "要確認"

# --------------------------------------------------
# Data Processing Engine
# --------------------------------------------------
def run_growth_audit_piccoma(df_adj, df_int):
    # 1. 캠페인명 매칭 (Fuzzy Matching)
    df_int['campaign_clean'] = df_int['campaign_name'].str.split(' \(').str[0].str.strip()
    adj_campaigns = df_adj['campaign_network'].unique().tolist()
    
    def find_match(name):
        match = process.extractOne(name, adj_campaigns, score_cutoff=80)
        return match[0] if match else None

    df_int['matched_campaign'] = df_int['campaign_clean'].apply(find_match)
    
    # 2. 데이터 병합
    df = pd.merge(df_adj, df_int, left_on='campaign_network', right_on='matched_campaign', how='inner')
    
    # 3. 핵심 지표 계산 (Piccoma BM 중심)
    df["cpi"] = df.apply(lambda x: safe_divide(x["cost"], x["installs"]), axis=1)
    df["activation_rate"] = df.apply(lambda x: safe_divide(x["ru_count"], x["user_count"]), axis=1) # 독자 전환율
    df["bm_usage_rate"] = df.apply(lambda x: safe_divide(x["bm_user_count"], x["user_count"]), axis=1) # BM 기여도
    df["payback_ratio"] = df.apply(lambda x: safe_divide(x["cost"], x["r_sales"]), axis=1) # 회수비율
    
    # 리텐션 기반 Early Signal
    df["d1_ret_rate"] = df.apply(lambda x: safe_divide(x["d1_count"], x["ru_count"]), axis=1)
    df["d7_ret_rate"] = df.apply(lambda x: safe_divide(x["d7_count"], x["ru_count"]), axis=1)
    df["early_signal_score"] = (df["d1_ret_rate"] * 0.3 + df["d7_ret_rate"] * 0.7) * 100

    # 4. 상대평가 및 스코어링
    avg_cpi = df["cpi"].mean()
    avg_bm_rate = df["bm_usage_rate"].mean()

    df["traffic_efficiency"] = df["cpi"].apply(lambda x: rate_relative_low_is_good(x, avg_cpi))
    df["activation_health"] = df["activation_rate"].apply(lambda x: "良好" if x >= 0.7 else ("普通" if x >= 0.5 else "注意"))
    df["bm_contribution"] = df["bm_usage_rate"].apply(lambda x: rate_relative_high_is_good(x, avg_bm_rate))
    df["payback_health"] = df["payback_ratio"].apply(lambda x: "良好" if x <= 1.0 else ("普通" if x <= 2.0 else "リスクあり"))

    # Growth Health Score (가중치 조정: BM 기여도 중심)
    df["traffic_score"] = df["traffic_efficiency"].map(map_score)
    df["activation_score"] = df["activation_health"].map(map_score)
    df["bm_score"] = df["bm_contribution"].map(map_score)
    df["payback_score"] = df["payback_health"].map(map_score)
    
    df["growth_health_score"] = (
        df["traffic_score"] * 0.15 +
        df["activation_score"] * 0.20 +
        df["bm_score"] * 0.40 + # BM 공헌도에 가장 높은 가중치
        df["payback_score"] * 0.25
    ).round(1)
    
    df["growth_category"] = df["growth_health_score"].apply(score_category)

    # 5. Measurement Confidence Score (제공해주신 로직 반영)
    def calc_confidence(row):
        score = 100
        if row["cost"] == 0: score -= 50
        if row["installs"] == 0: score -= 30
        if str(row["os_name"]).lower() == "ios": score -= 15
        if row.get("skad_installs", 0) > 0: score -= 10 # SKAN 비중이 있으면 신뢰도 감점
        return max(score, 0)

    df["confidence_score"] = df.apply(calc_confidence, axis=1)
    
    return df

# --------------------------------------------------
# UI Components
# --------------------------------------------------
st.markdown("## 📊 Piccoma Campaign Health Check")
st.markdown("<div class='small-note'>外部獲得効率 × 内部BM貢献度 × 測定信頼度の統合分析</div>", unsafe_allow_html=True)

# Sidebar: Upload
st.sidebar.header("📁 Data Upload")
adj_file = st.sidebar.file_uploader("1. Adjust Data (External)", type="csv")
int_file = st.sidebar.file_uploader("2. Internal SQL Data (Internal)", type="csv")

if adj_file and int_file:
    df_adj = pd.read_csv(adj_file)
    df_int = pd.read_csv(int_file)
    
    try:
        audit_df = run_growth_audit_piccoma(df_adj, df_int)

        # Summary Metrics
        st.markdown("### Executive Summary")
        m1, m2, m3, m4 = st.columns(4)
        m1.metric("平均 Growth Score", f"{audit_df['growth_health_score'].mean():.1f}")
        m2.metric("平均 測定信頼度", f"{audit_df['confidence_score'].mean():.1f}")
        m3.metric("BM利用率 (Avg)", f"{audit_df['bm_usage_rate'].mean()*100:.1f}%")
        m4.metric("分析対象件数", f"{len(audit_df)}件")

        # AI Comment
        avg_g = audit_df['growth_health_score'].mean()
        avg_c = audit_df['confidence_score'].mean()
        st.info(f"""
        💡 **[AIによる分析コメント]**
        現在のキャンペーン全体の健全性は **{score_category(avg_g)}** 判定です。
        測定信頼度が **{avg_c:.1f}** となっているため、iOSなどの推計データを含む意思決定には注意が必要です。
        特にBM貢献度が高い上位キャンペーンへの予算シフトを推奨します。
        """)

        # Scatter Chart
        st.markdown("### Campaign Positioning Matrix")
        scatter = alt.Chart(audit_df).mark_circle(size=150).encode(
            x=alt.X("growth_health_score:Q", title="Growth Health Score (BM貢献度)"),
            y=alt.Y("confidence_score:Q", title="Measurement Confidence Score (信頼度)"),
            color=alt.Color("growth_category:N", title="判定カテゴリ"),
            tooltip=["campaign_network", "channel", "growth_health_score", "confidence_score", "bm_usage_rate"]
        ).properties(height=450).interactive()
        st.altair_chart(scatter, use_container_width=True)

        # Styled Table
        st.markdown("### Campaign Detail Analysis")
        
        def style_scores(val):
            if isinstance(val, (int, float)) and val < 60:
                return "background-color: rgba(239, 68, 68, 0.2); color: #ef4444; font-weight: bold;"
            return ""

        view_cols = [
            "campaign_network", "channel", "cost", "growth_health_score", 
            "confidence_score", "bm_score", "activation_score", "payback_score", "growth_category"
        ]
        
        styled_df = audit_df[view_cols].style.applymap(style_scores, subset=["growth_health_score", "confidence_score", "bm_score"])
        st.dataframe(styled_df, use_container_width=True, height=500)

    except Exception as e:
        st.error(f"分析中にエラーが発生しました: {e}")
else:
    st.warning("左側のサイドバーからAdjustデータと社内データの両方をアップ로드してください。")
