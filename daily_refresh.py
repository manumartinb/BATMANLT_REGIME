"""
BATMANLT_REGIME daily chart refresh (worker ligero para V2 PERMA MASTER DAILY PIPELINE).

Refresca SOLO el grafico/panel vivo del dashboard BATMANLT_REGIME:
  - data.json -> 'series' + 'latest' + 'meta.chart_*' desde la ultima fecha
    de mercado disponible.
  - NO toca las tablas/deciles/stats (estudio backtest frozen).
  - git add data.json + commit + push origin main (SSH).

Senales daily (todas reformuladas como percentil expanding ex-ante, 0-1):
  - BQI_pctE: percentil del BQI cohort-mean diario (Batman LT)
  - TS_pctE:  percentil del TS_M3_real_equal diario (VIX term structure)
  - TEN_pctE: percentil del TENSION_3WAY_MIN cohort diario
  - PUT_pctE: skew_25d_vs50_pct_expanding (PUT, DTE60, 10:30) -- ya en pct
  - MAXOR:    MAX(TEN_pctE, PUT_pctE)
  - GBS_V1:   0.333*BQI_pctE + 0.333*(1-TS_pctE) + 0.334*MAXOR

Exit codes:
  0 = data.json actualizado y pusheado
  3 = sin cambios (idempotente, no commit)
  2 = warn de datos (fuente vacia/incompleta)
  1 = error
"""
import sys, os, json, subprocess
from datetime import datetime
from bisect import bisect_right, insort
import numpy as np, pandas as pd
sys.stdout.reconfigure(encoding='utf-8')

DIR  = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(DIR, 'data.json')
LT_CSV   = r'C:/Users/Administrator/Desktop/BULK OPTIONSTRAT/ESTRATEGIAS/Batman/SPX/LIVE/[MAIN RANKEO LT]_combined_BATMAN_mediana_w_stats_w_vix_OWN_ALLDAYS.csv'
PS_PATH  = r'C:/Users/Administrator/Desktop/BULK OPTIONSTRAT/ESTRATEGIAS/Skew/SKEW_PUT_ENRICHED.csv'
SPX_PATH = r'C:/Users/Administrator/Desktop/FINAL DATA/SP_SPX_CLOSE_HISTORICAL_PRICES.csv'

def log(m): print(f"[BATMANLT-REFRESH {datetime.now():%H:%M:%S}] {m}", flush=True)

def expanding_pct(v, w=30):
    acc=[]; out=np.full(len(v), np.nan)
    for i,x in enumerate(v):
        if not pd.isna(x):
            if len(acc) >= w: out[i] = bisect_right(acc, float(x)) / len(acc)
            insort(acc, float(x))
    return out

def banda(p):
    if pd.isna(p): return 'INDETERMINADO'
    if p >= 0.80: return 'FAVORABLE'
    if p <= 0.20: return 'ADVERSO'
    return 'NEUTRAL'

def git(args):
    return subprocess.run(['git','-C',DIR]+args, capture_output=True, text=True)

def main():
    try:
        if not os.path.isfile(DATA):
            log(f"data.json no existe en {DIR} -> ejecuta update_dashboard.py primero"); return 1
        data = json.load(open(DATA, encoding='utf-8'))

        # --- Cargar componentes diarios desde OWN_ALLDAYS (cohort means) ---
        log('Loading OWN_ALLDAYS (pyarrow)...')
        import pyarrow.csv as pacsv
        cols = ['dia','BQI_V4','BQI_V4_pct_exp','TS_M3_real_equal','TS_M3_pct_exp','TENSION_3WAY_MIN']
        ropts = pacsv.ReadOptions(use_threads=True, block_size=1<<25)
        copts = pacsv.ConvertOptions(include_columns=cols)
        df = pacsv.read_csv(LT_CSV, read_options=ropts, convert_options=copts).to_pandas()
        df['dia'] = pd.to_datetime(df['dia'])
        daily = df.groupby(df.dia.dt.date).agg(
            BQI_pctE=('BQI_V4_pct_exp','mean'),
            BQI_raw=('BQI_V4','mean'),
            TS_pctE=('TS_M3_pct_exp','mean'),
            TS_raw=('TS_M3_real_equal','mean'),
            TEN_raw=('TENSION_3WAY_MIN','mean'),
        ).reset_index().rename(columns={'dia':'date'})
        daily['date'] = pd.to_datetime(daily['date'])
        daily = daily.sort_values('date').reset_index(drop=True)
        if len(daily) < 100:
            log(f"OWN_ALLDAYS insuficiente (N={len(daily)})"); return 2

        # TEN_pctE expanding
        daily['TEN_pctE'] = expanding_pct(daily['TEN_raw'].values)

        # PUT_pctE
        ps = pd.read_csv(PS_PATH, usecols=['trade_date','snapshot_time','dte_target','side','skew_25d_vs50_pct_expanding'], low_memory=False)
        ps = ps[(ps.snapshot_time=='10:30:00') & (ps.dte_target==60) & (ps.side=='PUT')].copy()
        ps['date'] = pd.to_datetime(ps.trade_date).dt.normalize()
        ps = ps.dropna(subset=['skew_25d_vs50_pct_expanding']).sort_values('date').drop_duplicates('date',keep='last')
        ps['PUT_pctE'] = ps['skew_25d_vs50_pct_expanding'] / 100.0
        daily = daily.merge(ps[['date','PUT_pctE']], on='date', how='left')

        # MAXOR + GBS recompute (fillna logic)
        daily['BQI_pctE'] = daily['BQI_pctE'].fillna(0.5)
        daily['TS_pctE']  = daily['TS_pctE'].fillna(0.5)
        daily['TEN_pctE'] = daily['TEN_pctE'].fillna(0.0)
        daily['PUT_pctE'] = daily['PUT_pctE'].fillna(0.0)
        daily['MAXOR']    = daily[['TEN_pctE','PUT_pctE']].max(axis=1)
        daily['GBS']      = 0.333*daily.BQI_pctE + 0.333*(1-daily.TS_pctE) + 0.334*daily.MAXOR

        # SPX close
        spx = pd.read_csv(SPX_PATH, usecols=['time','close'])
        spx['date'] = pd.to_datetime(spx['time']).dt.normalize()
        daily = daily.merge(spx[['date','close']].rename(columns={'close':'spx'}), on='date', how='left')

        # Build serie completa
        series = []
        for _, r in daily.iterrows():
            if pd.isna(r['GBS']): continue
            series.append({
                't':     r['date'].strftime('%Y-%m-%d'),
                'gbs':   round(float(r['GBS'])*100, 2),
                'bqi':   round(float(r['BQI_pctE'])*100, 2),
                'tsinv': round((1-float(r['TS_pctE']))*100, 2),
                'maxor': round(float(r['MAXOR'])*100, 2),
                'spx':   (round(float(r['spx']),2) if pd.notna(r['spx']) else None),
            })
        if not series:
            log("serie diaria vacia"); return 2

        last = daily.dropna(subset=['GBS']).iloc[-1]
        ten_v = float(last['TEN_pctE']) if pd.notna(last['TEN_pctE']) else 0
        put_v = float(last['PUT_pctE']) if pd.notna(last['PUT_pctE']) else 0
        dom = 'TEN' if ten_v >= put_v else 'PUT'
        latest = {
            'date':         last['date'].strftime('%Y-%m-%d'),
            'gbs_pct':      round(float(last['GBS'])*100, 2),
            'regime_gbs':   banda(float(last['GBS'])),
            'gbs_decile':   int(min(10, max(1, int(float(last['GBS'])*10)+1))),
            'bqi_pct':      round(float(last['BQI_pctE'])*100, 2),
            'regime_bqi':   banda(float(last['BQI_pctE'])),
            'bqi_raw':      round(float(last['BQI_raw']), 3) if pd.notna(last['BQI_raw']) else None,
            'tsinv_pct':    round((1-float(last['TS_pctE']))*100, 2),
            'regime_tsinv': banda(1-float(last['TS_pctE'])),
            'ts_raw':       round(float(last['TS_raw']), 4) if pd.notna(last['TS_raw']) else None,
            'maxor_pct':    round(float(last['MAXOR'])*100, 2),
            'regime_maxor': banda(float(last['MAXOR'])),
            'maxor_dominant': dom,
            'maxor_ten_pct': round(ten_v*100, 1),
            'maxor_put_pct': round(put_v*100, 1),
        }

        data['series'] = series
        data['latest'] = latest
        data.setdefault('meta', {})['chart_date_max'] = latest['date']
        data['meta']['chart_n_days'] = int(len(series))

        json.dump(data, open(DATA,'w',encoding='utf-8'), indent=2, ensure_ascii=False)
        log(f"data.json patched: series={len(series)} dias, latest={latest['date']} "
            f"(GBS {latest['gbs_pct']:.1f} {latest['regime_gbs']})")

        # --- git push ---
        git(['add','data.json'])
        if git(['diff','--cached','--quiet']).returncode == 0:
            log("sin cambios -> idempotente"); return 3
        c = git(['-c','user.email=noreply@anthropic.com','-c','user.name=manumartinb',
                 'commit','-m',f"daily refresh {latest['date']}"])
        if c.returncode != 0:
            log(f"commit fallo: {c.stderr.strip()}"); return 1
        p = git(['push','origin','main'])
        if p.returncode != 0:
            log(f"push fallo: {p.stderr.strip()}"); return 1
        log("pushed -> https://manumartinb.github.io/BATMANLT_REGIME/")
        return 0
    except Exception as e:
        log(f"ERROR {type(e).__name__}: {e}"); return 1

if __name__ == '__main__':
    sys.exit(main())
