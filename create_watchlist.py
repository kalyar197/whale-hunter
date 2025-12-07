"""Create watchlist from master whale list"""
import pandas as pd

# Load master list
master = pd.read_csv('data/master_whale_list.csv')

# Create watchlist (score >= 40)
watchlist = master[master['whale_score'] >= 40].copy()

# Add notes column for manual tracking
watchlist['notes'] = ''
watchlist['status'] = 'ACTIVE'

# Reorder for watchlist focus
watchlist_columns = [
    'status',
    'wallet',
    'chain',
    'whale_score',
    'early_hit_count',
    'avg_buy_rank',
    'precision_rate',
    'patterns',
    'analysis_date',
    'notes'
]

watchlist_df = watchlist[watchlist_columns].copy()

# Save watchlist
watchlist_path = 'data/watchlist.csv'
watchlist_df.to_csv(watchlist_path, index=False)

print('='*80)
print('WATCHLIST CREATED')
print('='*80)
print(f'Saved to: {watchlist_path}')
print(f'Total watchlist wallets: {len(watchlist_df)}')
print()

# Show the watchlist
print('CURRENT WATCHLIST (Score >= 40):')
print()
for idx, row in watchlist_df.iterrows():
    tier = '*** TIER 1 ***' if row['whale_score'] >= 60 else '** TIER 2 **'
    print(f'{tier}  {row["wallet"]}')
    print(f'  Score: {row["whale_score"]:.1f} | Hits: {int(row["early_hit_count"])} | Rank: {row["avg_buy_rank"]:.1f} | Precision: {row["precision_rate"]*100:.1f}%')
    if pd.notna(row['patterns']) and str(row['patterns']) not in ['None', 'nan']:
        print(f'  Patterns: {row["patterns"]}')
    print()

print('='*80)
print('Files created:')
print('  1. data/master_whale_list.csv - ALL wallets tested (97 total)')
print('  2. data/watchlist.csv - High-priority wallets only (score >= 40)')
print()
print('Next time you run analysis (Helius, different timeframe, etc.):')
print('  - New wallets will be ADDED to master_whale_list.csv')
print('  - Duplicate wallets will keep HIGHEST score')
print('  - Run this script again to update watchlist.csv')
print('='*80)
