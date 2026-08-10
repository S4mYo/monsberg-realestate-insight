import pandas as pd

url = "https://files.zillowstatic.com/research/public_csvs/zhvi/Metro_zhvi_uc_sfrcondo_tier_0.33_0.67_sm_sa_month.csv?t=1786371714"
df = pd.read_csv(url)

print(df.shape)
print(df.columns[:10])
print(df.describe())
print(df.head())