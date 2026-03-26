# --------------------------------------------------
# 3. 데이터 처리 엔진 (중복 제거 및 그룹화 로직 추가)
# --------------------------------------------------
def run_growth_audit(df_adj, df_int):
    df_adj = df_adj.copy()
    df_int = df_int.copy().dropna(subset=['campaign_name'])
    
    # 1. 캠페인명 정규화
    def normalize_name(name):
        return re.sub(r'\s*\([^)]*\)', '', str(name)).strip()

    df_int['campaign_clean'] = df_int['campaign_name'].apply(normalize_name)
    
    # 🔴 핵심 수정: 내부 데이터를 캠페인명 기준으로 그룹화하여 합산
    # 같은 캠페인명을 가진 여러 ID의 데이터를 하나로 합칩니다.
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
    
    # 2. Fuzzy Matching
    def find_match(name):
        match = process.extractOne(name, adj_campaigns, score_cutoff=75)
        return match[0] if match else None

    df_int_grouped['matched_campaign'] = df_int_grouped['campaign_clean'].apply(find_match)
    
    # 3. Merge (그룹화된 내부 데이터와 Adjust 데이터 결합)
    df = pd.merge(df_adj, df_int_grouped, left_on='campaign_network', right_on='matched_campaign', how='inner')
    
    if df.empty: return df

    # --- 이후 지표 계산 및 스코어링 로직은 동일 ---
    df["cpi"] = df.apply(lambda x: safe_divide(x["cost"], x["installs"]), axis=1)
    df["activation_rate"] = df.apply(lambda x: safe_divide(x["ru_count"], x["user_count"]), axis=1)
    df["intensity"] = df.apply(lambda x: safe_divide(x["product_count"], x["ru_count"]), axis=1)
    df["retention_d7"] = df.apply(lambda x: safe_divide(x["d7_count"], x["ru_count"]), axis=1)
    df["bm_rate"] = df.apply(lambda x: safe_divide(x["bm_user_count"], x["user_count"]), axis=1)
    df["payback_ratio"] = df.apply(lambda x: safe_divide(x["cost"], x["r_sales"]), axis=1)

    avg_cpi = df["cpi"].mean(); avg_int = df["intensity"].mean(); avg_bm = df["bm_rate"].mean()

    # (중략: 스코어링 및 신뢰도 계산 코드는 이전과 동일)
    # ...
    
    return df
