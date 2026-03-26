# Campaign Performance Integrator

Adjustの外部獲得データと社内システムの行動データを統合し、真のROIを可視化するStreamlitアプリです。

## 主な機能
- **自動キャンペーンマッチング**: Fuzzy Matchingにより表記揺れを吸収
- **ROAS & CPRU分析**: 獲得単価と収益性の多角的な評価
- **ユーザーファン넬可視化**: インストールから課金までの歩留まりを分析
- **リテンション比較**: MMP指標と実サービスの利用継続率の乖離を確認

## 実行方法
1. `pip install -r requirements.txt`
2. `streamlit run app.py`

## 🚀 Growth Health Score Methodology
본 대시보드는 픽코마 BM에 최적화된 유입 유저를 선별하기 위해 6가지 지표에 가중치를 부여합니다.

| 항목 | 가중치 | 계산 공식 | 비즈니스 의미 |
| :--- | :---: | :--- | :--- |
| **Traffic** | 10% | `cost / installs` | 유입 단가(CPI)의 적절성 |
| **Activation** | 15% | `ru_count / user_count` | 작품 열람 전환율 (초기 관심도) |
| **Intensity** | 15% | `product_count / ru_count` | 열람 강도 (유저 1인당 평균 작품 소비량) |
| **Retention** | 20% | `d7_count / ru_count` | 7일 후 잔존율 (장기 정착 여부) |
| **BM Contribution** | 25% | `bm_user_count / user_count` | 픽코마 비즈니스 모델(기다무 등) 이용률 |
| **Payback** | 15% | `cost / r_sales` | 마케팅 비용 회수 효율 |
