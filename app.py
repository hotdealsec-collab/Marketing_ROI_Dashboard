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
    
    # OSが複数ある場合は "Cross-platform" に統一する関数
    def get_os_label(x):
        unique_os = sorted(x.dropna().unique().astype(str).tolist())
        if len(unique_os) > 1:
            return "Cross-platform"
        elif len(unique_os) == 1:
            return unique_os[0]
        else:
            return np.nan

    adj_grouped = df_adj.groupby('campaign_network').agg({
        'cost': 'sum',
        'installs': 'sum',
        'all_revenue': 'sum',
        'channel': lambda x: ', '.join(x.dropna().unique().astype(str)),
        'os_name': get_os_label
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
        # --- Filters ---
        st.markdown("### Filters")
        f1, f2, f3, f4 = st.columns(4)
        
        channel_opts = sorted(audit_df['channel'].dropna().unique().tolist())
        sel_ch = f1.multiselect("Channel", channel_opts, placeholder="All (Select to filter)")
        
        os_opts = sorted(audit_df['os_name'].dropna().unique().tolist())
        sel_os = f2.selectbox("OS", ["All"] + os_opts)
        
        campaign_opts = sorted(audit_df['campaign_network'].dropna().unique().tolist())
        sel_cp = f3.multiselect("Campaign", campaign_opts, placeholder="All (Select to filter)")
        
        category_opts = sorted(audit_df['growth_category'].dropna().unique().tolist())
        sel_ct = f4.selectbox("Growth Category", ["All"] + category_opts)

        f_df = audit_df.copy()
        if sel_ch:
            f_df = f_df[f_df['channel'].isin(sel_ch)]
        if sel_os != "All":
            f_df = f_df[f_df['os_name'] == sel_os]
        if sel_cp:
            f_df = f_df[f_df['campaign_network'].isin(sel_cp)]
        if sel_ct != "All":
            f_df = f_df[f_df['growth_category'] == sel_ct]

        # --- Overview ---
        st.markdown("### Overview")
        k1, k2, k3 = st.columns(3)
        
        if len(f_df) > 0:
            mean_score = f_df['growth_health_score'].mean()
            mean_conf = f_df['confidence_score'].mean()
            
            k1.metric("Average Growth Score", f"{mean_score:.1f}" if pd.notna(mean_score) else "N/A")
            k2.metric("Average Confidence", f"{mean_conf:.1f}" if pd.notna(mean_conf) else "N/A")
            k3.metric("Campaigns (Unique)", len(f_df))
        else:
            k1.metric("Average Growth Score", "N/A")
            k2.metric("Average Confidence", "N/A")
            k3.metric("Campaigns (Unique)", 0)

        # --- Positioning Chart ---
        st.markdown("### Campaign Positioning")
        
        f_df_plot = f_df.copy()
        
        np.random.seed(42) 
        f_df_plot["plot_x"] = f_df_plot["growth_health_score"] + np.random.uniform(-1.0, 1.0, len(f_df_plot))
        f_df_plot["plot_y"] = f_df_plot["confidence_score"] + np.random.uniform(-1.0, 1.0, len(f_df_plot))

        scatter = alt.Chart(f_df_plot).mark_circle(size=140, opacity=0.7).encode(
            x=alt.X("plot_x:Q", title="Growth Health Score", scale=alt.Scale(zero=False)),
            y=alt.Y("plot_y:Q", title="Confidence", scale=alt.Scale(zero=False)),
            color=alt.Color("growth_category:N", title="Category"),
            tooltip=["campaign_network", "growth_health_score", "confidence_score", "growth_category"]
        ).properties(height=400).interactive()
        
        st.altair_chart(scatter, use_container_width=True)

        # --- Campaign Table ---
        # 다운로드 버튼과 테이블 제목을 같은 줄에 배치하기 위해 컬럼 사용
        col_title, col_btn = st.columns([4, 1])
        col_title.markdown("### Campaign Table")
        
        display_cols = [
            "campaign_network", "channel", "os_name", 
            "growth_category", "growth_health_score", "confidence_score",
            "cpi", "activation", "intensity", "retention_d7", "bm_rate", "payback"
        ]

        # CSV 변환 함수 (Excel에서 일본어 깨짐 방지를 위해 utf-8-sig 사용)
        @st.cache_data
        def convert_df(df):
            return df.to_csv(index=False).encode('utf-8-sig')

        csv_data = convert_df(f_df[display_cols])

        # 다운로드 버튼
        col_btn.download_button(
            label="📥 Download CSV",
            data=csv_data,
            file_name='campaign_health_check.csv',
            mime='text/csv',
        )

        def style_red(val):
            return "background-color: rgba(239, 68, 68, 0.2); color: #ef4444;" if isinstance(val, (int, float)) and val < 60 else ""
        
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
