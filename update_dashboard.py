"""
Build BATMANLT_REGIME dashboard (GBS_V1 composite + 3 patas: BQI_pctE / (1-TS_M3_pctE) / MAX(TEN,PUT))

Analoga a STT_REGIME pero para Batman LT (DTE>=200) con score validado APR 8/9 PASS.

Fuente principal: [MAIN RANKEO LT]_..._OWN_ALLDAYS.csv (1614 dias / 46.118 trades).
Senales diarias:
  - GBS_V1            (composite, 0-1) -- headline
  - BQI_pctE          (pata 1, calidad endogena cohorte Batman)
  - (1 - TS_M3_pctE)  (pata 2, stress macro VIX term structure)
  - MAXOR             (pata 3, MAX(TEN_pctE, PUT_pctE) -- skew stress externo)

Tablas/stats fijas: backtest 2019-01-02 -> 2025-08-14. El chart/panel "latest"
se refresca diariamente desde daily_refresh.py (worker ligero V2 PERMA).
"""
import sys, os, json
from bisect import bisect_right, insort
import numpy as np, pandas as pd
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
sys.stdout.reconfigure(encoding='utf-8')

OUTDIR = r'C:/Users/Administrator/Desktop/BULK OPTIONSTRAT/ESTRATEGIAS/Skew/dashboards/BATMANLT_REGIME_DASHBOARD'
EVDIR  = os.path.join(OUTDIR, 'evidence')
os.makedirs(EVDIR, exist_ok=True)

LT_CSV   = r'C:/Users/Administrator/Desktop/BULK OPTIONSTRAT/ESTRATEGIAS/Batman/SPX/LIVE/[MAIN RANKEO LT]_combined_BATMAN_mediana_w_stats_w_vix_OWN_ALLDAYS.csv'
PS_PATH  = r'C:/Users/Administrator/Desktop/BULK OPTIONSTRAT/ESTRATEGIAS/Skew/SKEW_PUT_ENRICHED.csv'
SPX_PATH = r'C:/Users/Administrator/Desktop/FINAL DATA/SP_SPX_CLOSE_HISTORICAL_PRICES.csv'

# ---------- 1. LOAD ----------
print('[1] Loading OWN_ALLDAYS via pyarrow ...', flush=True)
import pyarrow.csv as pacsv
cols = ['dia','GBS_V1','GBS_V1_decile','GBS_V1_pctile_100',
        'BQI_V4_pct_exp','TS_M3_pct_exp','TENSION_3WAY_MIN',
        'PnL_d020_mediana','PnL_d050_mediana']
ropts = pacsv.ReadOptions(use_threads=True, block_size=1<<25)
copts = pacsv.ConvertOptions(include_columns=cols)
df = pacsv.read_csv(LT_CSV, read_options=ropts, convert_options=copts).to_pandas()
df['dia'] = pd.to_datetime(df['dia'])
df['year'] = df['dia'].dt.year
print(f'    {len(df):,} trades, {df.dia.dt.date.nunique():,} dias unicos, range {df.dia.min().date()} -> {df.dia.max().date()}')

# Aggregate per-day cohort
daily = df.groupby(df.dia.dt.date).agg(
    GBS=('GBS_V1','mean'),
    BQI_pctE=('BQI_V4_pct_exp','mean'),
    TS_pctE=('TS_M3_pct_exp','mean'),
    TEN_raw=('TENSION_3WAY_MIN','mean'),
    pnl_d020=('PnL_d020_mediana','mean'),
    pnl_d050=('PnL_d050_mediana','mean'),
    n_trades=('GBS_V1','count'),
).reset_index().rename(columns={'dia':'date'})
daily['date'] = pd.to_datetime(daily['date'])
daily['year'] = daily['date'].dt.year

# PUT_pctE from SKEW_PUT_ENRICHED
print('[2] Loading PUT_SKEW @DTE60/10:30 ...', flush=True)
ps = pd.read_csv(PS_PATH, usecols=['trade_date','snapshot_time','dte_target','side','skew_25d_vs50_pct_expanding'], low_memory=False)
ps = ps[(ps.snapshot_time=='10:30:00') & (ps.dte_target==60) & (ps.side=='PUT')].copy()
ps['date'] = pd.to_datetime(ps.trade_date).dt.normalize()
ps = ps.dropna(subset=['skew_25d_vs50_pct_expanding']).sort_values('date').drop_duplicates('date',keep='last')
ps['PUT_pctE'] = ps['skew_25d_vs50_pct_expanding'] / 100.0
daily = daily.merge(ps[['date','PUT_pctE']], on='date', how='left')

# TEN_pctE: expanding rank on cohort TEN_raw
daily = daily.sort_values('date').reset_index(drop=True)
def exp_pct(vals, warm=30):
    acc=[]; out=np.full(len(vals), np.nan)
    for i,v in enumerate(vals):
        if not pd.isna(v):
            if len(acc) >= warm: out[i] = bisect_right(acc, float(v)) / len(acc)
            insort(acc, float(v))
    return out
daily['TEN_pctE'] = exp_pct(daily.TEN_raw.values)
daily['MAXOR']    = daily[['TEN_pctE','PUT_pctE']].max(axis=1)

def banda(p):
    if pd.isna(p): return 'INDETERMINADO'
    if p>=0.80: return 'FAVORABLE'   # ALTO GBS = REGIMEN BUENO (alto stress + bqi alto)
    if p<=0.20: return 'ADVERSO'
    return 'NEUTRAL'

# ---------- 2. BACKTEST TABLES ----------
def pf(v):
    v=np.asarray(v,float); v=v[~np.isnan(v)]; p=v[v>0].sum(); n=-v[v<0].sum()
    return float(p/n) if n>0 else float('inf')
def cvar5(v):
    v=np.asarray(v,float); v=v[~np.isnan(v)]
    return float(v[v<=np.percentile(v,5)].mean()) if len(v)>=20 else float('nan')

RAW_d020_mean = float(daily['pnl_d020'].mean())
RAW_d050_mean = float(daily['pnl_d050'].mean())

def cohort_row(sub, label):
    a020 = sub['pnl_d020'].dropna().values
    a050 = sub['pnl_d050'].dropna().values
    return {
        'label': label, 'n_dias': int(len(sub)),
        'd020_mean': round(float(a020.mean()),2) if len(a020) else None,
        'd020_median': round(float(np.median(a020)),2) if len(a020) else None,
        'd020_wr': round(100*float((a020>0).mean()),1) if len(a020) else None,
        'd020_pf': round(pf(a020),2) if len(a020) else None,
        'd020_cvar5': round(cvar5(a020),2) if len(a020)>=20 else None,
        'd050_mean': round(float(a050.mean()),2) if len(a050) else None,
        'd050_pf': round(pf(a050),2) if len(a050) else None,
    }

# RAW + cutoffs
d = daily.dropna(subset=['GBS','pnl_d020']).copy()
cohort_tbl = [cohort_row(d, 'RAW (universo)')]
for cut, lbl in [(50,'TOP50 (GBS>=P50)'),(70,'TOP30 (GBS>=P70)'),(80,'TOP20 (GBS>=P80)'),(90,'TOP10 (GBS>=P90)'),(95,'TOP5 (GBS>=P95)')]:
    th = np.percentile(d.GBS, cut)
    cohort_tbl.append(cohort_row(d[d.GBS>=th], lbl))
for cut, lbl in [(30,'BOT30 (GBS<=P30)'),(20,'BOT20 (GBS<=P20)'),(10,'BOT10 (GBS<=P10)')]:
    th = np.percentile(d.GBS, cut)
    cohort_tbl.append(cohort_row(d[d.GBS<=th], lbl))

# Decile breakdown
d['dec'] = pd.qcut(d.GBS, 10, labels=False, duplicates='drop') + 1
decile_tbl = []
for i in range(1, 11):
    sub = d[d.dec==i]
    a = sub.pnl_d020.dropna().values
    decile_tbl.append({
        'decile': int(i), 'n': int(len(sub)),
        'd020_mean': round(float(a.mean()),2) if len(a) else None,
        'd020_median': round(float(np.median(a)),2) if len(a) else None,
        'd020_wr': round(100*float((a>0).mean()),1) if len(a) else None,
        'd020_pf': round(pf(a),2) if len(a) else None,
    })

# Year stability
def spearman(x, y):
    s = pd.DataFrame({'x':x,'y':y}).dropna()
    return float(s.x.rank().corr(s.y.rank())) if len(s)>10 else float('nan')

year_tbl = []
for y in sorted(d.year.unique()):
    g = d[d.year==y]
    if len(g) < 50: continue
    r = spearman(g.GBS, g.pnl_d020)
    a = g.pnl_d020.values
    year_tbl.append({
        'year': int(y), 'n_dias': int(len(g)),
        'spearman_r': round(r, 3),
        'd020_mean': round(float(a.mean()),2),
        'd020_pf': round(pf(a),2),
        'spearman_pos': int(r > 0),
    })

# Per-signal SOLO tables (BQI_pctE, 1-TS_pctE, MAXOR)
def solo_table(col, name, inv=False):
    d2 = daily.dropna(subset=[col, 'pnl_d020']).copy()
    if inv: d2['_score'] = 1 - d2[col]
    else: d2['_score'] = d2[col]
    rows = [cohort_row(d2, f'RAW ({len(d2)} dias)')]
    for cut, lbl in [(70,f'TOP30 ({name}>=P70)'),(80,f'TOP20 ({name}>=P80)'),(90,f'TOP10 ({name}>=P90)')]:
        th = np.percentile(d2['_score'], cut)
        rows.append(cohort_row(d2[d2['_score']>=th], lbl))
    for cut, lbl in [(30,f'BOT30 ({name}<=P30)'),(20,f'BOT20 ({name}<=P20)'),(10,f'BOT10 ({name}<=P10)')]:
        th = np.percentile(d2['_score'], cut)
        rows.append(cohort_row(d2[d2['_score']<=th], lbl))
    return rows

solo_bqi   = solo_table('BQI_pctE',  'BQI_pctE')
solo_tsinv = solo_table('TS_pctE',   '(1-TS_pctE)', inv=True)  # invertido
solo_maxor = solo_table('MAXOR',     'MAXOR (TEN|PUT)')

# Inter-signal correlations
m4 = daily[['GBS','BQI_pctE','TS_pctE','MAXOR']].dropna()
corr_4 = {
    'GBS_BQI':    round(float(m4.GBS.corr(m4.BQI_pctE)),3),
    'GBS_TSinv':  round(float(m4.GBS.corr(1-m4.TS_pctE)),3),
    'GBS_MAXOR':  round(float(m4.GBS.corr(m4.MAXOR)),3),
    'BQI_TSinv':  round(float(m4.BQI_pctE.corr(1-m4.TS_pctE)),3),
    'BQI_MAXOR':  round(float(m4.BQI_pctE.corr(m4.MAXOR)),3),
    'TSinv_MAXOR':round(float((1-m4.TS_pctE).corr(m4.MAXOR)),3),
}

# Spearman r each signal vs PnL d020
sig_r = {
    'GBS':   spearman(daily.GBS,    daily.pnl_d020),
    'BQI_pctE': spearman(daily.BQI_pctE, daily.pnl_d020),
    'TSinv_pctE': spearman(1-daily.TS_pctE, daily.pnl_d020),
    'MAXOR': spearman(daily.MAXOR,  daily.pnl_d020),
}
sig_r = {k: round(v,4) for k,v in sig_r.items()}

# ---------- 3. SERIE DIARIA + LATEST (refrescable por daily_refresh.py) ----------
print('[3] Building daily chart series + latest panel ...', flush=True)
# Para chart: misma serie que tablas (in-sample backtest). El daily_refresh.py
# extiende esta serie hasta hoy con los componentes recomputados desde
# SKEW_PUT_ENRICHED + cohort means actuales.
spx = pd.read_csv(SPX_PATH, usecols=['time','close'])
spx['date'] = pd.to_datetime(spx['time']).dt.normalize()
daily = daily.merge(spx[['date','close']].rename(columns={'close':'spx'}), on='date', how='left')

series = []
for _, r in daily.iterrows():
    if pd.isna(r.GBS): continue
    series.append({
        't':    r['date'].strftime('%Y-%m-%d'),
        'gbs':  round(float(r['GBS'])*100, 2),
        'bqi':  round(float(r['BQI_pctE'])*100, 2)  if not pd.isna(r['BQI_pctE']) else None,
        'tsinv':round((1-float(r['TS_pctE']))*100, 2) if not pd.isna(r['TS_pctE']) else None,
        'maxor':round(float(r['MAXOR'])*100, 2)     if not pd.isna(r['MAXOR']) else None,
        'spx':  (round(float(r['spx']),2) if pd.notna(r['spx']) else None),
    })

latest_row = daily.dropna(subset=['GBS']).iloc[-1]
latest = {
    'date':       latest_row['date'].strftime('%Y-%m-%d'),
    'gbs_pct':    round(float(latest_row['GBS'])*100, 2),
    'regime_gbs': banda(latest_row['GBS']),
    'bqi_pct':    round(float(latest_row['BQI_pctE'])*100, 2),
    'regime_bqi': banda(latest_row['BQI_pctE']),
    'tsinv_pct':  round((1-float(latest_row['TS_pctE']))*100, 2),
    'regime_tsinv': banda(1-latest_row['TS_pctE']),
    'maxor_pct':  round(float(latest_row['MAXOR'])*100, 2),
    'regime_maxor': banda(latest_row['MAXOR']),
    'gbs_decile': int(min(10, max(1, int(latest_row['GBS']*10)+1))),
}

# ---------- 4. DATA.JSON ----------
data = {
    'meta': {
        'dataset': '[MAIN RANKEO LT]_combined_BATMAN_OWN_ALLDAYS',
        'n_trades': int(len(df)),
        'n_days_backtest': int(d['date'].dt.date.nunique()),
        'date_min': d['date'].min().strftime('%Y-%m-%d'),
        'date_max': d['date'].max().strftime('%Y-%m-%d'),
        'chart_date_max': latest['date'],
        'chart_n_days': len(series),
        'target': 'PnL_d020_mediana cohort-mean per day',
        'score_doc': 'GATE_BATMAN_SCORE_V1_Formula_(Batman).md',
    },
    'baseline': {
        'n_dias': int(len(d)),
        'd020_mean': round(RAW_d020_mean, 2),
        'd050_mean': round(RAW_d050_mean, 2),
    },
    'latest': latest,
    'series': series,
    'thresholds': {'favorable_min': 80.0, 'adverso_max': 20.0},
    'stats': {
        'r_day_GBS_vs_d020': sig_r['GBS'],
        'r_day_BQI_vs_d020': sig_r['BQI_pctE'],
        'r_day_TSinv_vs_d020': sig_r['TSinv_pctE'],
        'r_day_MAXOR_vs_d020': sig_r['MAXOR'],
        'inter_corr': corr_4,
    },
    'tbl_cohort_cuts': cohort_tbl,
    'tbl_decile_GBS': decile_tbl,
    'tbl_year_stability': year_tbl,
    'tbl_solo_BQI':   solo_bqi,
    'tbl_solo_TSinv': solo_tsinv,
    'tbl_solo_MAXOR': solo_maxor,
}

OUT_JSON = os.path.join(OUTDIR, 'data.json')
with open(OUT_JSON, 'w', encoding='utf-8') as f:
    json.dump(data, f, indent=2, ensure_ascii=False)
print(f'[4] data.json saved ({os.path.getsize(OUT_JSON)/1024:.1f} KB)')

# ---------- 5. CHARTS (PNG evidence) ----------
print('[5] Generating PNG plots ...', flush=True)
plt.style.use('dark_background')
COL_BG = '#0d1117'; COL_PAN = '#161b22'

def plot_decile_bars():
    fig, ax = plt.subplots(figsize=(10, 4.5), dpi=120, facecolor=COL_BG)
    ax.set_facecolor(COL_PAN)
    dec = [r['decile'] for r in decile_tbl]
    mn  = [r['d020_mean'] or 0 for r in decile_tbl]
    colors = ['#f85149' if m < 0 else ('#d29922' if m < 10 else '#3fb950') for m in mn]
    bars = ax.bar(dec, mn, color=colors, edgecolor='#30363d')
    for b, m in zip(bars, mn):
        ax.text(b.get_x()+b.get_width()/2, m, f'{m:+.1f}',
                ha='center', va='bottom' if m>=0 else 'top', fontsize=9)
    ax.axhline(0, color='#666', linewidth=0.6)
    ax.set_xticks(dec)
    ax.set_xlabel('Decile GBS_V1 (1=peor regimen, 10=mejor)')
    ax.set_ylabel('mean PnL_d020 cohort (pts)')
    ax.set_title('Batman LT - PnL_d020 cohort-mean por decile GBS_V1')
    ax.grid(alpha=0.18)
    fig.tight_layout()
    fig.savefig(os.path.join(EVDIR, 'gbs_decile_bars.png'), facecolor=COL_BG)
    plt.close(fig)

def plot_year_stability():
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(13, 4.2), dpi=120, facecolor=COL_BG)
    yrs = [r['year'] for r in year_tbl]
    rs  = [r['spearman_r'] for r in year_tbl]
    means = [r['d020_mean'] for r in year_tbl]
    for ax, vals, ttl, ylbl in [
        (ax1, rs, 'Spearman r por anio (GBS vs d020)', 'r_day'),
        (ax2, means, 'PnL_d020 mean por anio (RAW)', 'pts'),
    ]:
        ax.set_facecolor(COL_PAN)
        colors = ['#3fb950' if v>0 else '#f85149' for v in vals]
        ax.bar([str(y) for y in yrs], vals, color=colors, edgecolor='#30363d')
        for x, v in zip([str(y) for y in yrs], vals):
            ax.text(x, v, f'{v:+.2f}' if 'r' in ttl else f'{v:+.1f}',
                    ha='center', va='bottom' if v>=0 else 'top', fontsize=9)
        ax.axhline(0, color='#666', linewidth=0.6)
        ax.set_title(ttl); ax.set_ylabel(ylbl); ax.grid(alpha=0.18)
    fig.tight_layout()
    fig.savefig(os.path.join(EVDIR, 'gbs_year_stability.png'), facecolor=COL_BG)
    plt.close(fig)

def plot_signal_inter_corr():
    fig, ax = plt.subplots(figsize=(7, 4.2), dpi=120, facecolor=COL_BG)
    ax.set_facecolor(COL_PAN)
    labels = ['GBS-BQI','GBS-TSinv','GBS-MAXOR','BQI-TSinv','BQI-MAXOR','TSinv-MAXOR']
    vals = [corr_4['GBS_BQI'], corr_4['GBS_TSinv'], corr_4['GBS_MAXOR'],
            corr_4['BQI_TSinv'], corr_4['BQI_MAXOR'], corr_4['TSinv_MAXOR']]
    colors = ['#58a6ff' if v>0.5 else '#3fb950' if v>0 else '#f85149' for v in vals]
    bars = ax.barh(labels, vals, color=colors, edgecolor='#30363d')
    for b, v in zip(bars, vals):
        ax.text(v, b.get_y()+b.get_height()/2, f'{v:+.2f}', va='center',
                ha='left' if v>=0 else 'right', fontsize=10)
    ax.axvline(0, color='#666', linewidth=0.6)
    ax.set_xlim(-1, 1)
    ax.set_title('Correlaciones inter-senal (Spearman)')
    ax.grid(alpha=0.18)
    fig.tight_layout()
    fig.savefig(os.path.join(EVDIR, 'gbs_inter_corr.png'), facecolor=COL_BG)
    plt.close(fig)

plot_decile_bars()
plot_year_stability()
plot_signal_inter_corr()

print('\n=== SUMMARY ===')
print(f'Latest:  date={latest["date"]}  GBS={latest["gbs_pct"]:.1f} ({latest["regime_gbs"]})')
print(f'         BQI={latest["bqi_pct"]:.1f} ({latest["regime_bqi"]})  TSinv={latest["tsinv_pct"]:.1f} ({latest["regime_tsinv"]})  MAXOR={latest["maxor_pct"]:.1f} ({latest["regime_maxor"]})')
print(f'Stats:   r_day GBS={sig_r["GBS"]:+.3f}  BQI={sig_r["BQI_pctE"]:+.3f}  TSinv={sig_r["TSinv_pctE"]:+.3f}  MAXOR={sig_r["MAXOR"]:+.3f}')
print(f'Decile spread D10-D1 d020 = {decile_tbl[-1]["d020_mean"] - decile_tbl[0]["d020_mean"]:+.2f} pts')
print(f'Yrs positivos: {sum(r["spearman_pos"] for r in year_tbl)}/{len(year_tbl)}')
print(f'Done. data.json + 3 PNGs en {EVDIR}')
