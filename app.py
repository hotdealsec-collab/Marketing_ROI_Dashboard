import streamlit as st
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from rapidfuzz import process

# --- ページ設定 ---
st.set_page_config(page_title="Piccoma Executive Dashboard", layout="wide")

st.title("📊 広告投資対効果(ROAS)＆媒体品質 経営ダッシュボード")
st.markdown("外部MMP(Adjust)の獲得データと内部データベースを統合し、真のマーケティングROIとユーザーの質を可視化します。")

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

    # マッチング関数の定義
    def find_match(name):
        if pd.isna(name): return None
        match = process.extractOne(name, adj_campaigns, score_cutoff=80)
        return match[0] if match else None

    with st.spinner('データを統合中...'):
        df_int['matched_campaign'] = df_int['campaign_clean'].apply(find_match)

    # データの結合
    df_merged = pd.merge(
        df_adj, df_int, left_on='campaign_network', right_on='matched_campaign', how='inner'
    )

    # --- 指標計算 ---
    # 流入数とROASの計算
    df_merged['mmp_total_inflow'] = df_merged['first_login_events'] + df_merged['reattributions']
    df_merged['Actual_ROAS'] = (df_merged['r_sales'] / df_merged['cost']) * 100
    df_merged['Reading_Rate'] = (df_merged['ru_count'] / df_merged['user_count']) * 100
    df_merged['Discrepancy_Rate'] = ((df_merged['mmp_total_inflow'] - df_merged['user_count']) / df_merged['mmp_total_inflow']) * 100
    
    # ユーザー品質分類用データの生成
    df_merged['Inactive_Users'] = df_merged['user_count'] - df_merged['ru_count']
    df_merged['Active_Free_Users'] = df_merged['ru_count'] - df_merged['pu_count']
    df_merged['Paying_Users'] = df_merged['pu_count']

    # --- TOP: 核心 KPI ---
    total_cost = df_merged['cost'].sum()
    total_sales = df_merged['r_sales'].sum()
    avg_roas = (total_sales / total_cost) * 100
    avg_discrepancy = ((df_merged['mmp_total_inflow'].sum() - df_merged['user_count'].sum()) / df_merged['mmp_total_inflow'].sum()) * 100

    col1, col2, col3, col4 = st.columns(4)
    col1.metric("総広告費", f"¥{total_cost:,.0f}")
    col2.metric("総実売上", f"¥{total_sales:,.0f}")
    col3.metric("総合ROAS", f"{avg_roas:.1f}%")
    col4.metric("平均データ乖離率", f"{avg_discrepancy:.1f}%", delta_color="inverse")

    st.divider()

    # --- AIによる分析コメント ---
    st.info(f"""
    💡 **[AIによる分析コメント]**
    * **全体成果の要約:** 現在実行されているマーケティングの統合ROASは **{avg_roas:.1f}%** です。
    * **データの整合性:** 外部媒体から流入したと報告されたユーザーと、内部の実際の流入ユーザーとの間に **{avg_discrepancy:.1f}%** の乖離が発生しています。乖離率が異常に高いキャンペーンは、トラッキング漏れや不正トラフィック（Fraud）の確認が必要です。
    * **意思決定の提案:** 下部の「投資効率ポートフォリオ（Magic Quadrant）」で、**第1象限（右上）**に位置するキャンペーンには予算を増額し、**第3象限（左下）**のキャンペーンは即時の停止またはクリエイティブの変更を推奨します。
    """)

    st.divider()

    # --- SECTION 1: 外部 vs 内部 乖離率分析（予算漏れの検知） ---
    st.subheader("1. MMP vs 内部データ乖離率 (予算漏れの検知)")
    fig_scatter_disc = px.scatter(
        df_merged, x="mmp_total_inflow", y="user_count", 
        hover_name="campaign_network", size="cost", color="channel",
        labels={"mmp_total_inflow": "MMP報告流入数 (Adjust)", "user_count": "実際の内部流入数 (DB)"},
        title="流入数の乖離 (基準線より下は「虚数トラフィック」の疑いあり)"
    )
    # 理想的な基準線 (X=Y) を追加
    max_val = max(df_merged['mmp_total_inflow'].max(), df_merged['user_count'].max())
    fig_scatter_disc.add_shape(type="line", x0=0, y0=0, x1=max_val, y1=max_val, line=dict(color="red", dash="dash"))
    st.plotly_chart(fig_scatter_disc, use_container_width=True)

    # --- SECTION 2: 媒体別のユーザー品質分析 ---
    st.subheader("2. 媒体別ユーザー品質分析 (真の価値を生むチャネル)")
    df_quality = df_merged.groupby('channel')[['Inactive_Users', 'Active_Free_Users', 'Paying_Users']].sum().reset_index()
    fig_bar_quality = px.bar(
        df_quality, x="channel", y=['Inactive_Users', 'Active_Free_Users', 'Paying_Users'],
        title="チャネル別ユーザー行動の質 (100%積み上げ)",
        labels={"value": "ユーザー数", "variable": "ユーザータイプ", "channel": "流入元"},
        color_discrete_map={"Inactive_Users": "lightgray", "Active_Free_Users": "lightblue", "Paying_Users": "crimson"}
    )
    fig_bar_quality.update_layout(barmode='relative')
    st.plotly_chart(fig_bar_quality, use_container_width=True)

    # --- SECTION 3: 投資効率ポートフォリオ（予算再配分） ---
    st.subheader("3. 投資効率ポートフォリオ (Magic Quadrant)")
    fig_quadrant = px.scatter(
        df_merged, x="Reading_Rate", y="Actual_ROAS", size="cost", color="channel",
        hover_name="campaign_network",
        labels={"Reading_Rate": "作品閲覧転換率 (%)", "Actual_ROAS": "実ROAS (%)"},
        title="バブルサイズ: 広告費 / 右上(★): 拡大対象 / 左下(✖): 停止検討"
    )
    # 4象限を分ける平均線を追加
    fig_quadrant.add_vline(x=df_merged['Reading_Rate'].mean(), line_width=1, line_dash="dash", line_color="gray")
    fig_quadrant.add_hline(y=df_merged['Actual_ROAS'].mean(), line_width=1, line_dash="dash", line_color="gray")
    st.plotly_chart(fig_quadrant, use_container_width=True)

    # --- SECTION 4: 要アクション・キャンペーン ---
    st.subheader("🚨 要アクション・キャンペーン")
    col_table1, col_table2 = st.columns(2)

    with col_table1:
        st.markdown("**▼ 虚数疑い (乖離率ワースト5)**")
        bad_disc = df_merged.sort_values(by="Discrepancy_Rate", ascending=False).head(5)
        st.dataframe(bad_disc[['campaign_network', 'mmp_total_inflow', 'user_count', 'Discrepancy_Rate', 'cost']], hide_index=True)

    with col_table2:
        st.markdown("**▼ 赤字警告 (ROASワースト5)**")
        bad_roas = df_merged[df_merged['cost'] > 10000].sort_values(by="Actual_ROAS", ascending=True).head(5)
        st.dataframe(bad_roas[['campaign_network', 'cost', 'r_sales', 'Actual_ROAS', 'Reading_Rate']], hide_index=True)

else:
    st.info("サイドバーからAdjustと社内システムのCSVファイルをアップロードしてください。")
