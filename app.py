import numpy as np
import pandas as pd
import streamlit as st
import altair as alt
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
# 2. 判定ロジック関数
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
# 3. データ処理エンジン (完全一致 & 重複排除)
# --------------------------------------------------
def run_growth_audit(df_adj, df_int):
    # --- 1. 外部データ(Adjust)のクレンジングと集計 ---
    df_adj = df_adj.dropna(subset=['campaign_network']).copy()
    df_adj['campaign_network'] = df_adj['campaign_network'].astype(str).str.strip()
    
    adj_grouped = df_adj.groupby('campaign_network').agg({
        'cost': 'sum',
        'installs': 'sum',
        'all_revenue': 'sum',
        'channel': lambda x: ', '.join(x.dropna().unique().astype(str)),
        'os_name': lambda x: ', '.join(x.dropna().unique().astype(str))
    }).reset_index()

    # --- 2. 内部データのクレンジングと集計 ---
    df_int = df_int.dropna(subset=['campaign_name']).copy()
    
    def clean_campaign_name(name):
        return re.sub(r'\s*\(\d+\)\s*$', '', str(name)).strip()

    df_int['campaign_name_clean'] = df_int['campaign_name'].apply(clean_campaign_name)
    
    int_grouped = df_int.groupby('campaign_name_clean').agg({
        'user_count': 'sum', 'ru_count': 'sum', 'd1_count': 'sum',
        'd7_count': 'sum', 'product_count': 'sum', 'bm_user_count': 'sum', 'r_sales': 'sum'
    }).reset_index()

    # --- 3. 結合 (Adjust基準 Left Join) ---
    df = pd.merge(adj_grouped, int_grouped, left_on='campaign_network', right_on='campaign_name_clean', how='left')
    
    if df.empty: return df

    # --- 4. 指標計算とスコアリング ---
    df["cpi"] = df.apply(lambda x: safe_divide(x["cost"], x["installs"]), axis=1)
    df["activation"] = df.apply(lambda x: safe_divide(x["ru_count"], x["user_count"]), axis=1)
    df["intensity"] = df.apply(lambda x: safe_divide(x["product_count"], x["ru_count"]), axis=1)
    df["retention_d7"] = df.apply(lambda x: safe_divide(x["d7_count"], x["ru_count"]), axis=1)
    df["bm_rate"] = df.apply(lambda x: safe_divide(x["bm_user_count"], x["user_count"]), axis=1)
    df["payback"] = df.apply(lambda x: safe_divide(x["cost"], x["r_sales"]), axis=1)

    avg_cpi = df["cpi"].mean()
    avg_int = df["intensity"].mean()
    avg_bm = df["bm_rate"].mean()

    # スコア化
    df["s_traffic"] = df["cpi"].apply(lambda x: "不明" if pd.isna(x) or pd.isna(avg_cpi) else ("良好" if x <= avg_cpi*0.85 else ("普通" if x <= avg_cpi*1.15 else "注意"))).map(map_score)
    df["s_activation"] = df["activation"].apply(lambda x: 50 if pd.isna(x) else (100 if x >= 0.7 else (60 if x >= 0.5 else 30)))
    df["s_intensity"] = df["intensity"].apply(lambda x: "不明" if pd.isna(x) or pd.isna(avg_int) else ("良好" if x >= avg_int*1.15 else ("普通" if x >= avg_int*0.85 else "注意"))).map(map_score)
    df["s_retention"] = df["retention_d7"].apply(lambda x: 50 if pd.isna(x) else (100 if x >= 0.25 else (60 if x >= 0.15 else 30)))
    df["s_bm"] = df["bm_rate"].apply(lambda x: "不明" if pd.isna(x) or pd.isna(avg_bm) else ("良好" if x >= avg_bm*1.15 else ("普通" if x >= avg_bm*0.85 else "注意"))).map(map_score)
    
    # cost가 0인 경우 s_payback을 0으로 처리, 그 외의 경우 기존 로직 적용
    df["s_payback"] = df.apply(
        lambda x: 0 if x["cost"] == 0 else (
            50 if pd.isna(x["payback"]) else (100 if x["payback"] <= 1.2 else (60 if x["payback"] <= 2.5 else 20))
        ), axis=1
    )

    df["growth_health_score"] = (df["s_traffic"]*0.1 + df["s_activation"]*0.15 + df["s_intensity"]*0.15 + df["s_retention"]*0.2 + df["s_bm"]*0.25 + df["s_payback"]*0.15).round(1)
    df["growth_category"] = df["growth_health_score"].apply(score_category)
    df["confidence_score"] = df.apply(lambda x: max(100 - (50 if x["cost"]==0 else 0), 0), axis=1)
    
    return df

# --------------------------------------------------
# 4. メイン UI
# --------------------------------------------------
st.title("Campaign Health Check")

st.sidebar.header("Upload")
adj_file = st.sidebar.file_uploader("Adjust CSV", type="csv")
int_file = st.sidebar.file_uploader("Internal SQL CSV", type="csv")

st.sidebar.markdown("---")
with st.sidebar.expander("ℹ️ Growth Scoreの算出根拠", expanded=True):
    st.markdown("""
    総合スコアの重み付け：
    - **Traffic (10%)**: CPI効率
    - **Activation (15%)**: 作品閲覧転換率
    - **Intensity (15%)**: 平均閲覧作品数
    - **Retention (20%)**: D7維持率
    - **BM Contribution (25%)**: BM利用率
    - **Payback (15%)**: 投資回収効率
    """)

if adj_file and int_file:
    audit_df = run_growth_audit(pd.read_csv(adj_file), pd.read_csv(int_file))

    if audit_df.empty:
        st.error("❌ キャンペーンの一致が確認できませんでした。Adjustの'campaign_network'と社内データの'campaign_name'を確認してください。")
    else:
        st.markdown("### Overview")
        k1, k2, k3 = st.columns(3)
        
        mean_score = audit_df['growth_health_score'].mean()
        mean_conf = audit_df['confidence_score'].mean()
        
        k1.metric("Average Growth Score", f"{mean_score:.1f}" if pd.notna(mean_score) else "N/A")
        k2.metric("Average Confidence", f"{mean_conf:.1f}" if pd.notna(mean_conf) else "N/A")
        k3.metric("Campaigns (Unique)", len(audit_df))

        st.markdown("### Filters")
        f1, f2, f3, f4 = st.columns(4)
        
        sel_ch = f1.selectbox("Channel", ["All"] + sorted(audit_df['channel'].dropna().unique().tolist()))
        sel_os = f2.selectbox("OS", ["All"] + sorted(audit_df['os_name'].dropna().unique().tolist()))
        sel_cp = f3.selectbox("Campaign", ["All"] + sorted(audit_df['campaign_network'].dropna().unique().tolist()))
        sel_ct = f4.selectbox("Growth Category", ["All"] + sorted(audit_df['growth_category'].dropna().unique().tolist()))

        f_df = audit_df.copy()
        if sel_ch != "All": f_df = f_df[f_df['channel'].str.contains(sel_ch, na=False)]
        if sel_os != "All": f_df = f_df[f_df['os_name'].str.contains(sel_os, na=False)]
        if sel_cp != "All": f_df = f_df[f_df['campaign_network'] == sel_cp]
        if sel_ct != "All": f_df = f_df[f_df['growth_category'] == sel_ct]

      # Positioning Chart
        st.markdown("### Campaign Positioning")
        
        # 겹치는 캠페인들을 분산시키기 위해 차트용 데이터프레임 복사 및 Jitter(노이즈) 추가
        f_df_plot = f_df.copy()
        
        # 실제 데이터가 겹치지 않도록 X, Y 좌표에 -1.0 ~ +1.0 사이의 랜덤 값을 미세하게 추가
        np.random.seed(42) # 새로고침 시에도 점들이 너무 심하게 튀지 않도록 시드 고정
        f_df_plot["plot_x"] = f_df_plot["growth_health_score"] + np.random.uniform(-1.0, 1.0, len(f_df_plot))
        f_df_plot["plot_y"] = f_df_plot["confidence_score"] + np.random.uniform(-1.0, 1.0, len(f_df_plot))

        # 투명도(opacity=0.7)를 추가하여 점이 겹쳐있을 때 더 진하게 보이도록 개선
        scatter = alt.Chart(f_df_plot).mark_circle(size=140, opacity=0.7).encode(
            x=alt.X("plot_x:Q", title="Growth Health Score", scale=alt.Scale(zero=False)),
            y=alt.Y("plot_y:Q", title="Confidence", scale=alt.Scale(zero=False)),
            color=alt.Color("growth_category:N", title="Category"),
            # 마우스를 올렸을 때 보여지는 툴팁에는 Jitter 값이 아닌 "실제 점수"가 나오도록 설정
            tooltip=["campaign_network", "growth_health_score", "confidence_score", "growth_category"]
        ).properties(height=400).interactive()
        
        st.altair_chart(scatter, use_container_width=True)

        st.markdown("### Campaign Table")
        def style_red(val):
            return "background-color: rgba(239, 68, 68, 0.2); color: #ef4444;" if isinstance(val, (int, float)) and val < 60 else ""
        
        # 테이블 컬럼에서 s_ 항목들을 모두 제외하고 실제 수치 데이터만 표시
        display_cols = [
            "campaign_network", "channel", "os_name", 
            "growth_category", "growth_health_score", "confidence_score",
            "cpi", "activation", "intensity", "retention_d7", "bm_rate", "payback"
        ]
        
        st.dataframe(
            f_df[display_cols].style
            .map(style_red, subset=["growth_health_score"])
            .format({
                "cpi": "{:.2f}",
                "activation": "{:.1%}",
                "intensity": "{:.2f}",
                "retention_d7": "{:.1%}",
                "bm_rate": "{:.1%}",
                "payback": "{:.2f}"
            }, na_rep="N/A"), 
            use_container_width=True, 
            height=500
        )
else:
    st.info("左右のCSVファイルをアップロードしてください。")
