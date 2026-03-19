import streamlit as st
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from rapidfuzz import process, utils

# --- ページ設定 ---
st.set_page_config(page_title="Piccoma Marketing ROI Dashboard", layout="wide")

st.title("📊 広告キャンペーン分析ダッシュボード")
st.markdown("""
Adjust（外部）と社内システム（内部）のデータを統合し、真の広告投資対効果（ROAS）とユーザー質を可視化します。
""")

# --- サイドバー：ファイルアップロード ---
st.sidebar.header("1. データアップロード")
adjust_file = st.sidebar.file_uploader("Adjustレポート (CSV)", type="csv")
internal_file = st.sidebar.file_uploader("社内行動データ (CSV)", type="csv")

if adjust_file and internal_file:
    # データ読み込み
    df_adj = pd.read_csv(adjust_file)
    df_int = pd.read_csv(internal_file)

    # --- データ前処理 & マッチング ---
    # 社内データのキャンペーン名からIDを分離する処理
    df_int['campaign_clean'] = df_int['campaign_name'].str.split(' \(').str[0].str.strip()
    
    # Adjustのキャンペーンリスト
    adj_campaigns = df_adj['campaign_network'].unique().tolist()

    # マッチング関数の定義 (Fuzzy Matching)
    def find_match(name):
        if pd.isna(name): return None
        match = process.extractOne(name, adj_campaigns, score_cutoff=80)
        return match[0] if match else None

    with st.spinner('キャンペーン名を照合中...'):
        df_int['matched_campaign'] = df_int['campaign_clean'].apply(find_match)

    # データの結合
    df_merged = pd.merge(
        df_adj, 
        df_int, 
        left_on='campaign_network', 
        right_on='matched_campaign', 
        how='inner'
    )

    # --- 指標計算 (Advanced Metrics) ---
    df_merged['Actual_ROAS'] = (df_merged['r_sales'] / df_merged['cost']) * 100
    df_merged['CPRU'] = df_merged['cost'] / df_merged['ru_count'] # 閲覧ユーザー獲得単価
    df_merged['Reading_Rate'] = (df_merged['ru_count'] / df_merged['user_count']) * 100
    df_merged['PU_Rate'] = (df_merged['pu_count'] / df_merged['user_count']) * 100

    # --- ダッシュボード表示 ---
    
    # KPI Summary
    col1, col2, col3, col4 = st.columns(4)
    col1.metric("Total Cost", f"¥{df_merged['cost'].sum():,.0f}")
    col2.metric("Total Sales (Internal)", f"¥{df_merged['r_sales'].sum():,.0f}")
    col3.metric("Avg. ROAS", f"{(df_merged['r_sales'].sum()/df_merged['cost'].sum()*100):.1f}%")
    col4.metric("Total Reading Users", f"{df_merged['ru_count'].sum():,.0f}")

    st.divider()

    # 1. ROAS vs CPRU 分析
    st.subheader("🎯 キャンペーン効率分析 (ROAS vs 閲覧ユーザー獲得単価)")
    fig_scatter = px.scatter(
        df_merged, 
        x="CPRU", 
        y="Actual_ROAS", 
        size="cost", 
        color="channel",
        hover_name="campaign_network",
        title="獲得コストと収益性の相関 (バブルサイズは広告費)"
    )
    st.plotly_chart(fig_scatter, use_container_width=True)

    # 2. ファンネル分析 (유저 퍼널 시각화)
    st.subheader("📉 ユーザー遷移ファンネル")
    total_data = df_merged[['first_login_events', 'user_count', 'ru_count', 'bm_user_count', 'pu_count']].sum()
    fig_funnel = go.Figure(go.Funnel(
        y = ["New Installs(MMP)", "Internal Users", "Reading Users", "BM Users", "Paying Users"],
        x = total_data.values,
        textinfo = "value+percent initial"
    ))
    st.plotly_chart(fig_funnel, use_container_width=True)

    # 3. リテンション比較 (MMP vs 内部)
    st.subheader("📅 リテンション乖離分析")
    # AdjustのD7維持率と内部のD7(d7_count/user_count)を比較
    df_merged['internal_retention_d7'] = df_merged['d7_count'] / df_merged['user_count']
    
    fig_ret = go.Figure()
    fig_ret.add_trace(go.Bar(name='MMP Retention D7', x=df_merged['campaign_network'], y=df_merged['retention_rate_d7']))
    fig_ret.add_trace(go.Bar(name='Internal Content Retention D7', x=df_merged['campaign_network'], y=df_merged['internal_retention_d7']))
    fig_ret.update_layout(barmode='group', title="アプリ起動維持率 vs コンテンツ閲覧維持率")
    st.plotly_chart(fig_ret, use_container_width=True)

    # 4. 詳細データテーブル
    st.subheader("📋 統合データ詳細")
    st.dataframe(df_merged[[
        'campaign_network', 'cost', 'first_login_events', 'user_count', 
        'ru_count', 'Actual_ROAS', 'CPRU', 'Reading_Rate'
    ]].sort_values(by='Actual_ROAS', ascending=False))

else:
    st.info("サイドバーからAdjustと社内システムのCSVファイルをアップロードしてください。")
