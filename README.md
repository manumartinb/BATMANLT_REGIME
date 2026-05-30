# BATMAN LT REGIME — GBS_V1 (composite + 3 patas)

Dashboard publico de regimen estructural para Batman LT (DTE>=200). Score canonico
`GATE_BATMAN_SCORE_V1` (GBS_V1) + sus 3 componentes ortogonales.

**Live:** https://manumartinb.github.io/BATMANLT_REGIME/

## Que mide

`GBS_V1` es un score continuo en [0, 100] que agrega 3 dimensiones del regimen
estructural Batman LT del dia, validado APR Layer A+B+C como ROBUSTO 8/9 PASS:

| Pata | Peso | Que mide | Stress -> alto |
|---|---|---|---|
| `BQI_pctE` | 1/3 | Calidad estructural endogena cohort Batman del dia | ALTO = bueno |
| `(1 - TS_M3_pctE)` | 1/3 | Stress macro vol via term-structure VIX | TS bajo -> termino alto |
| `MAX(TEN_pctE, PUT_pctE)` | 1/3 | Skew externo: compression OR put-skew 25d-vs-50d | ALTO = stress |

```
GBS_V1 = 0.333 * BQI_pctE + 0.333 * (1 - TS_M3_pctE) + 0.334 * MAX(TEN_pctE, PUT_pctE)
```

## Bandas operativas

- **FAVORABLE**: GBS >= 80 (top 20% historico)
- **NEUTRAL**: 20 < GBS < 80
- **ADVERSO**: GBS <= 20

## Hallazgos clave (validados APR)

- **D10 (top decile GBS)** mean d020 = **+22.7 pts** (PF 24.8, WR 83%)
- **D1 (bottom decile)** mean d020 = **-4.5 pts** (PF 0.66, WR 40%)
- **Spread D10-D1 = +27 pts**, Kendall tau = **+0.96** (monotonia casi perfecta)
- **LOYO 6/7 anos positivos** (unico fallo: 2021)
- **Spearman r_day pooled = +0.32** [CI95 +0.28, +0.37]
- Generaliza a Batman MT (P90 uplift +11 pts d020)
- **NO portable directamente a Allantis** (las patas TS_M3 y TENSION son Batman/SPX-especificas)

## Caveats honestos

1. **2021 roto**: unico ano con r negativo (-0.08). Mercado tranquilo post-COVID donde
   regimen alto fue falsa alarma.
2. **VIX bajo colapsa Spearman**: r=+0.04 en tercil inferior VIX, aunque uplift cohorte
   sigue positivo (+4 pts).
3. **Drift OOS -55%**: r cae de +0.40 (2019-22) a +0.18 (2023-25). Dentro de tolerancia.
4. **Coincidente, no adelantado**: mide regimen EN CURSO, no anticipa shocks exogenos.
5. **delta R^2 lineal = +0.002**: GBS NO aporta info aditiva vs sus 4 patas en regresion.
   Es re-expresion granular ordenada (decile rank-aware), no senal nueva.

## Estructura del estudio en el dashboard

- **Seccion 1**: KPIs headline (N dias, r_day, D10, D1, spread).
- **Seccion 2**: Cohort cuts (RAW + P50/P70/P80/P90/P95 + BOT10/20/30).
- **Seccion 3**: Decile analysis (10 deciles, monotonia tau).
- **Seccion 4**: Year stability (LOYO bar chart + tabla).
- **Seccion 5**: Senales SOLAS (las 3 patas por separado, comparable).
- **Seccion 6**: Correlaciones inter-senal (ortogonalidad).

## Archivos

- `index.html` — dashboard (lee data.json)
- `data.json` — datos serializados
- `evidence/` — PNGs (decile bars, year stability, inter-corr)
- `update_dashboard.py` — regenera data.json + PNGs desde dataset madre (batch)
- `daily_refresh.py` — worker ligero que refresca SOLO chart/latest a la ultima fecha
  de mercado disponible (llamado por V2 PERMA daily pipeline)

## Fuentes (NO incluidas en el repo)

- `[MAIN RANKEO LT]_combined_BATMAN_..._OWN_ALLDAYS.csv` (~355 MB, en VPS del autor)
- `Skew/SKEW_PUT_ENRICHED.csv` (PUT skew externo)
- `FINAL DATA/SP_SPX_CLOSE_HISTORICAL_PRICES.csv` (SPX overlay del chart)

Los datos persistidos en `data.json` son **agregados diarios anonimizados**: no contienen
strikes, IVs por pata, premiums, ni trade-level data. Solo cohort-means + percentiles
+ stats agregadas.

## Doc canonico

`ESTRATEGIAS/GATE_BATMAN_SCORE_V1_Formula_(Batman).md` (descripcion completa de la
formula, FASE 11-18 del proyecto `definitive_thermometer_residual`).

## Relacion con otros dashboards

- **STT_REGIME**: misma arquitectura (3 senales + composite implicito), pero para STT
  PUT BWB en DTE 150-170. Diferentes targets.
- **PUT_SKEW_NIVEL_BATMAN_LT**: solo la pata PUT externa (subset de la pata 3 de aqui).

GBS_V1 NO sustituye REGIME_SCORE (MAX-OR canonico, ya operativo en V51 LIVE). Son
complementarios: REGIME_SCORE = 2 patas externas; GBS_V1 = 3 patas incluyendo calidad
endogena Batman.
