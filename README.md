# ParlayStats ⚽

Football parlay predictor berbasis statistik murni — no AI, no biaya API.

## Setup

### 1. Vercel Deploy
1. Upload folder ini ke GitHub repo baru
2. Import ke Vercel
3. Tambah Environment Variable:
   - `FOOTBALL_DATA_KEY` = API key dari football-data.org (gratis)

### 2. Local Development
```bash
pip install flask requests
export FOOTBALL_DATA_KEY=your_key_here
python app.py
```

## Cara Dapat API Key
1. Daftar gratis di https://www.football-data.org/client/register
2. Cek email, copy API key
3. Paste di Vercel Environment Variables

## Fitur
- Form 5 match terakhir (W/D/L)
- Head-to-head record
- Posisi & poin standings
- Home/away win rate
- Expected goals (xG)
- BTTS probability
- Outcome probability (Home/Draw/Away %)
- Parlay confidence score (2-6 legs)

## Competitions Supported (Free Tier)
- Premier League (PL)
- La Liga (PD)
- Bundesliga (BL1)
- Serie A (SA)
- Ligue 1 (FL1)
- Eredivisie (DED)
- Primeira Liga (PPL)
- Champions League (CL)
- Europa League (EL)
