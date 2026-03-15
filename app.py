from flask import Flask, render_template, request, jsonify
import requests, time, os, math, json, uuid
from datetime import datetime, timedelta

SUPABASE_URL      = os.environ.get("SUPABASE_URL", "https://mafnnqttvkdgqqxczqyt.supabase.co")
SUPABASE_ANON_KEY = os.environ.get("SUPABASE_ANON_KEY", "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6Im1hZm5ucXR0dmtkZ3FxeGN6cXl0Iiwicm9sZSI6ImFub24iLCJpYXQiOjE3NzE4NzQyMDEsImV4cCI6MjA4NzQ1MDIwMX0.YRh1oWVKnn4tyQNRbcPhlSyvr7V_1LseWN7VjcImb-Y")
SUPABASE_HEADERS  = {
    "apikey": SUPABASE_ANON_KEY,
    "Authorization": f"Bearer {SUPABASE_ANON_KEY}",
    "Content-Type": "application/json",
    "Prefer": "return=representation"
}

app = Flask(__name__)

FOOTBALL_KEY = os.environ.get("FOOTBALL_DATA_KEY", "450de9a377b74884a6cc15b28f40f5bc")  # hardcoded fallback
FD_BASE      = "https://api.football-data.org/v4"
FD_HEADERS   = {"X-Auth-Token": FOOTBALL_KEY}

# ── Cache ──────────────────────────────────────────────────────────────────
_cache = {}
def cache_get(k):
    e = _cache.get(k)
    return e["data"] if e and time.time() < e["expires"] else None
def cache_set(k, d, ttl=300):
    _cache[k] = {"data": d, "expires": time.time() + ttl}

# ── Simple API fetch with retry on 429 ────────────────────────────────────
def fd_get(path, ttl=300):
    cached = cache_get(path)
    if cached is not None:
        return cached
    try:
        r = requests.get(FD_BASE + path, headers=FD_HEADERS, timeout=15)
        if r.status_code == 429:
            time.sleep(62)
            r = requests.get(FD_BASE + path, headers=FD_HEADERS, timeout=15)
        if r.status_code == 403:
            return {"error": "API key invalid or expired"}
        if not r.ok:
            return {"error": f"API error {r.status_code}"}
        d = r.json()
        cache_set(path, d, ttl)
        return d
    except Exception as e:
        return {"error": str(e)}

# ── Poisson ────────────────────────────────────────────────────────────────
def poisson_prob(lam, k):
    try:
        return (math.exp(-lam) * (lam ** k)) / math.factorial(k)
    except:
        return 0.0

def calc_goal_probs(home_xg, away_xg, max_goals=8):
    matrix = {}
    for h in range(max_goals+1):
        for a in range(max_goals+1):
            matrix[(h,a)] = poisson_prob(home_xg,h) * poisson_prob(away_xg,a)
    tg = {}
    for (h,a),p in matrix.items():
        tg[h+a] = tg.get(h+a,0)+p
    def over_p(l):  return max(1,min(99,round(sum(p for t,p in tg.items() if t>l)*100)))
    def under_p(l): return max(1,min(99,round(sum(p for t,p in tg.items() if t<l)*100)))
    btts = sum(p for (h,a),p in matrix.items() if h>0 and a>0)
    top  = sorted(matrix.items(),key=lambda x:x[1],reverse=True)[:6]
    best = max(matrix,key=matrix.get)
    return {
        "over_0_5":over_p(0.5),"under_0_5":under_p(0.5),
        "over_1_5":over_p(1.5),"under_1_5":under_p(1.5),
        "over_2_5":over_p(2.5),"under_2_5":under_p(2.5),
        "over_3_5":over_p(3.5),"under_3_5":under_p(3.5),
        "over_4_5":over_p(4.5),"under_4_5":under_p(4.5),
        "btts_yes":max(1,min(99,round(btts*100))),
        "btts_no":max(1,min(99,round((1-btts)*100))),
        "most_likely_score":f"{best[0]}-{best[1]}",
        "top_scores":[{"score":f"{h}-{a}","prob":round(p*100,1)} for (h,a),p in top],
        "home_xg":round(home_xg,2),"away_xg":round(away_xg,2),
        "total_xg":round(home_xg+away_xg,2),
    }

# ── Pages ──────────────────────────────────────────────────────────────────
@app.route("/")
def index():
    return render_template("index.html")

# ── API: Matches ───────────────────────────────────────────────────────────
@app.route("/api/matches")
def get_matches():
    comp = request.args.get("comp","PL")
    date_from = request.args.get("from",datetime.now().strftime("%Y-%m-%d"))
    try:
        dt = datetime.strptime(date_from,"%Y-%m-%d")
    except:
        dt = datetime.now()
    date_to = (dt+timedelta(days=2)).strftime("%Y-%m-%d")
    data = fd_get(f"/competitions/{comp}/matches?dateFrom={date_from}&dateTo={date_to}",300)
    if not data.get("matches") and not data.get("error"):
        date_to7 = (dt+timedelta(days=7)).strftime("%Y-%m-%d")
        data = fd_get(f"/competitions/{comp}/matches?dateFrom={date_from}&dateTo={date_to7}",300)
    return jsonify(data)

# ── API: Team info (squad, venue, colors) ─────────────────────────────────
@app.route("/api/team/<int:team_id>")
def get_team_info(team_id):
    return jsonify(fd_get(f"/teams/{team_id}",86400))

# ── API: Top scorers ───────────────────────────────────────────────────────
@app.route("/api/scorers/<comp>")
def get_scorers(comp):
    return jsonify(fd_get(f"/competitions/{comp}/scorers?limit=10",3600))

# ── API: Standings ─────────────────────────────────────────────────────────
@app.route("/api/standings/<comp>")
def get_standings(comp):
    return jsonify(fd_get(f"/competitions/{comp}/standings",3600))

# ── API: Predict ───────────────────────────────────────────────────────────
@app.route("/api/predict",methods=["POST"])
def predict():
    body  = request.get_json(force=True) or {}
    picks = body.get("picks",[])
    if not picks:
        return jsonify({"error":"No picks provided"}),400

    # Pre-fetch standings + scorers once per comp (cached)
    comps     = list({p.get("comp","PL") for p in picks})
    standings = {c: fd_get(f"/competitions/{c}/standings",3600) for c in comps}
    scorers   = {c: fd_get(f"/competitions/{c}/scorers?limit=10",3600) for c in comps}

    results = []
    for pick in picks:
        comp     = pick.get("comp","PL")
        home_id  = pick["home_id"]
        away_id  = pick["away_id"]
        match_id = pick["match_id"]

        hfd  = fd_get(f"/teams/{home_id}/matches?status=FINISHED&limit=10",3600)
        afd  = fd_get(f"/teams/{away_id}/matches?status=FINISHED&limit=10",3600)
        h2hd = fd_get(f"/matches/{match_id}/head2head?limit=10",3600)
        hinf = fd_get(f"/teams/{home_id}",86400)
        ainf = fd_get(f"/teams/{away_id}",86400)

        results.append(analyze_match(
            pick, hfd, afd, h2hd,
            standings[comp], scorers[comp], hinf, ainf
        ))

    confs   = [r["confidence"] for r in results]
    geo     = math.exp(sum(math.log(max(c,1)) for c in confs)/len(confs))
    overall = max(5,min(95,round(geo*(0.85**(len(results)-1)))))
    return jsonify({"predictions":results,"overall_confidence":overall,"legs":len(results)})

# ── Engine ─────────────────────────────────────────────────────────────────
def analyze_match(pick, hfd, afd, h2hd, std, scrd, hinf, ainf):
    home_id   = pick["home_id"]
    away_id   = pick["away_id"]
    home_name = pick.get("home_name","Home")
    away_name = pick.get("away_name","Away")
    market    = pick.get("market","1X2")

    hf  = parse_form(home_id, hfd.get("matches",[]))
    af  = parse_form(away_id, afd.get("matches",[]))
    hs  = get_standing(home_id, std)
    as_ = get_standing(away_id, std)
    h2h = parse_h2h(home_id, away_id, h2hd.get("matches",[]))

    # Squad depth bonus
    h_squad = len(hinf.get("squad",[])) if isinstance(hinf,dict) else 0
    a_squad = len(ainf.get("squad",[])) if isinstance(ainf,dict) else 0
    squad_bonus = min(5, max(-5, (h_squad - a_squad) * 0.2))

    # Top scorer bonus
    h_scorer_bonus = a_scorer_bonus = 0
    h_scorer_name  = a_scorer_name  = None
    if isinstance(scrd,dict):
        for s in scrd.get("scorers",[]):
            tid   = s.get("team",{}).get("id")
            goals = s.get("goals",0) or 0
            name  = s.get("player",{}).get("name","")
            if tid == home_id and not h_scorer_name:
                h_scorer_bonus = min(4, goals*0.15)
                h_scorer_name  = f"{name} ({goals}g)"
            elif tid == away_id and not a_scorer_name:
                a_scorer_bonus = min(4, goals*0.15)
                a_scorer_name  = f"{name} ({goals}g)"

    # xG
    LAVG    = 1.35
    home_xg = max(0.3,min(4.0, hf["avg_scored"]*(af["avg_conceded"]/LAVG)*1.1))
    away_xg = max(0.3,min(4.0, af["avg_scored"]*(hf["avg_conceded"]/LAVG)*0.9))
    h2h_avg = calc_h2h_avg_goals(h2hd.get("matches",[]))
    if h2h_avg and h2h["total"]>=4:
        txg = home_xg+away_xg
        if txg>0:
            home_xg = home_xg*0.7+(home_xg/txg*h2h_avg)*0.3
            away_xg = away_xg*0.7+(away_xg/txg*h2h_avg)*0.3
    gp = calc_goal_probs(home_xg, away_xg)

    # 1X2
    hs_ = calc_team_score(hf,hs,True) + squad_bonus + h_scorer_bonus
    as__ = calc_team_score(af,as_,False) + a_scorer_bonus
    if h2h["home_wins"]>h2h["away_wins"]: hs_+=5
    elif h2h["away_wins"]>h2h["home_wins"]: as__+=5
    tot = hs_+as__
    hwp = round((hs_/tot)*100) if tot else 50
    awp = 100-hwp
    drp = round(20+(10 if abs(hs_-as__)<10 else 0))
    adj = (hwp+awp+drp-100)//3
    hwp-=adj; awp-=adj; drp-=adj

    pm = {
        "1X2":       lambda: (f"{home_name} Win",hwp) if hwp>=awp and hwp>=drp else (f"{away_name} Win",awp) if awp>=drp else ("Draw",drp),
        "Home Win":  lambda: (f"{home_name} Win",hwp),
        "Away Win":  lambda: (f"{away_name} Win",awp),
        "Draw":      lambda: ("Draw",drp),
        "Over 0.5":  lambda: ("Over 0.5 Goals",  gp["over_0_5"]),
        "Under 0.5": lambda: ("Under 0.5 Goals", gp["under_0_5"]),
        "Over 1.5":  lambda: ("Over 1.5 Goals",  gp["over_1_5"]),
        "Under 1.5": lambda: ("Under 1.5 Goals", gp["under_1_5"]),
        "Over 2.5":  lambda: ("Over 2.5 Goals",  gp["over_2_5"]),
        "Under 2.5": lambda: ("Under 2.5 Goals", gp["under_2_5"]),
        "Over 3.5":  lambda: ("Over 3.5 Goals",  gp["over_3_5"]),
        "Under 3.5": lambda: ("Under 3.5 Goals", gp["under_3_5"]),
        "Over 4.5":  lambda: ("Over 4.5 Goals",  gp["over_4_5"]),
        "Under 4.5": lambda: ("Under 4.5 Goals", gp["under_4_5"]),
        "BTTS Yes":  lambda: ("BTTS - Yes",gp["btts_yes"]),
        "BTTS No":   lambda: ("BTTS - No", gp["btts_no"]),
    }
    p_pick,conf = pm.get(market,pm["1X2"])()
    conf = max(5,min(92,conf))

    return {
        "home":home_name,"away":away_name,
        "market":market,"pick":p_pick,"confidence":conf,
        "reasoning":build_reasoning(home_name,away_name,hf,af,hs,as_,h2h,
            market,home_xg,away_xg,gp,h_scorer_name,a_scorer_name,h_squad,a_squad),
        "goal_probs":gp,
        "stats":{
            "home_form":hf["form_str"],"away_form":af["form_str"],
            "home_pos":hs["position"],"away_pos":as_["position"],
            "home_avg_scored":hf["avg_scored"],"away_avg_scored":af["avg_scored"],
            "home_avg_conceded":hf["avg_conceded"],"away_avg_conceded":af["avg_conceded"],
            "home_xg":round(home_xg,2),"away_xg":round(away_xg,2),
            "total_xg":round(home_xg+away_xg,2),
            "h2h_home_wins":h2h["home_wins"],"h2h_away_wins":h2h["away_wins"],"h2h_draws":h2h["draws"],
            "btts_prob":gp["btts_yes"],
            "home_win_prob":hwp,"draw_prob":drp,"away_win_prob":awp,
            "most_likely_score":gp["most_likely_score"],"top_scores":gp["top_scores"],
            "home_squad":h_squad,"away_squad":a_squad,"home_points":hs.get("points",0),"away_points":as_.get("points",0),
            "home_top_scorer":h_scorer_name or "—","away_top_scorer":a_scorer_name or "—",
        }
    }

def parse_form(team_id,matches):
    if not matches:
        return {"form_str":"?????","points":0,"avg_scored":1.2,"avg_conceded":1.2,
                "btts_rate":0.45,"wins":0,"draws":0,"losses":0,"clean_sheets":0}
    recent=matches[-10:]
    results,scored,conceded=[],[],[]
    btts=cs=0
    for m in recent:
        sc=m.get("score",{}).get("fullTime",{})
        hs,as_=sc.get("home"),sc.get("away")
        if hs is None or as_ is None: continue
        is_home=m.get("homeTeam",{}).get("id")==team_id
        tf,ta=(hs,as_) if is_home else (as_,hs)
        scored.append(tf);conceded.append(ta)
        results.append("W" if tf>ta else "L" if tf<ta else "D")
        if tf>0 and ta>0: btts+=1
        if ta==0: cs+=1
    last5=results[-5:] if len(results)>=5 else results
    return {
        "form_str":"".join(last5).ljust(5,"?"),
        "points":sum(3 if r=="W" else 1 if r=="D" else 0 for r in last5),
        "avg_scored":round(sum(scored)/len(scored),2) if scored else 1.2,
        "avg_conceded":round(sum(conceded)/len(conceded),2) if conceded else 1.2,
        "btts_rate":round(btts/len(results),2) if results else 0.45,
        "wins":results.count("W"),"draws":results.count("D"),"losses":results.count("L"),
        "clean_sheets":cs,
    }

def get_standing(team_id,std):
    try:
        for g in std.get("standings",[]):
            for row in g.get("table",[]):
                if row.get("team",{}).get("id")==team_id:
                    return {"position":row.get("position",99),"points":row.get("points",0),
                            "goalsFor":row.get("goalsFor",0),"goalsAgainst":row.get("goalsAgainst",0),
                            "played":row.get("playedGames",1),"won":row.get("won",0)}
    except: pass
    return {"position":99,"points":0,"goalsFor":0,"goalsAgainst":0,"played":1,"won":0}

def parse_h2h(hid,aid,matches):
    hw=aw=dr=0
    for m in matches:
        ht=m.get("homeTeam",{}).get("id")
        sc=m.get("score",{}).get("fullTime",{})
        h,a=sc.get("home"),sc.get("away")
        if h is None or a is None: continue
        if h>a:   hw+=(1 if ht==hid else 0);aw+=(1 if ht==aid else 0)
        elif a>h: aw+=(1 if ht==hid else 0);hw+=(1 if ht==aid else 0)
        else: dr+=1
    return {"home_wins":hw,"away_wins":aw,"draws":dr,"total":hw+aw+dr}

def calc_h2h_avg_goals(matches):
    tots=[m.get("score",{}).get("fullTime",{}).get("home",0)+m.get("score",{}).get("fullTime",{}).get("away",0)
          for m in matches if m.get("score",{}).get("fullTime",{}).get("home") is not None]
    return sum(tots)/len(tots) if tots else None

def calc_team_score(form,standing,is_home):
    s=50+(form.get("points",7)-7)*2
    s+=max(-15,min(15,(10-standing.get("position",10))*1.5))
    played=max(standing.get("played",1),1)
    s+=((standing.get("goalsFor",0)-standing.get("goalsAgainst",0))/played)*3
    if is_home: s+=6
    return max(1,s)

def build_reasoning(hn,an,hf,af,hs,as_,h2h,market,hxg,axg,gp,h_sc,a_sc,h_sq,a_sq):
    p=[]
    p.append(f"{hn} form: {hf['form_str']} | {an} form: {af['form_str']}.")
    if hs.get("position",99)<99:
        p.append(f"Klasemen: {hn} #{hs['position']} ({hs['points']} poin) vs {an} #{as_['position']} ({as_.get('points',0)} poin).")
    p.append(f"xG: {hn} {round(hxg,2)} — {an} {round(axg,2)} (total {round(hxg+axg,2)}).")
    if "Over" in market or "Under" in market or "BTTS" in market:
        p.append(f"Rata-rata gol: {hn} cetak {hf['avg_scored']}, kebobolan {hf['avg_conceded']}; "
                 f"{an} cetak {af['avg_scored']}, kebobolan {af['avg_conceded']}.")
        p.append(f"Over probs — 0.5:{gp['over_0_5']}% | 1.5:{gp['over_1_5']}% | 2.5:{gp['over_2_5']}% | 3.5:{gp['over_3_5']}% | 4.5:{gp['over_4_5']}%.")
        p.append(f"Skor paling mungkin: {gp['most_likely_score']}. BTTS: {gp['btts_yes']}%.")
    else:
        if h2h["total"]>0:
            p.append(f"H2H ({h2h['total']} laga): {hn} {h2h['home_wins']}M — {h2h['draws']}S — {h2h['away_wins']}M {an}.")
    if h_sc: p.append(f"Top scorer {hn}: {h_sc}.")
    if a_sc: p.append(f"Top scorer {an}: {a_sc}.")
    if h_sq and a_sq: p.append(f"Skuad: {hn} {h_sq} pemain vs {an} {a_sq} pemain.")
    return " ".join(p)

# ── Save slip to Supabase ──────────────────────────────────────────────────
@app.route("/api/slip/save", methods=["POST"])
def save_slip():
    if not SUPABASE_URL or not SUPABASE_ANON_KEY:
        return jsonify({"error": "Supabase not configured"}), 500

    body = request.get_json(force=True) or {}
    slip_id = str(uuid.uuid4())[:8].upper()  # short ID e.g. "A1B2C3D4"

    payload = {
        "slip_id":   slip_id,
        "data":      json.dumps(body.get("data", {})),
        "picks":     json.dumps(body.get("picks", [])),
        "created_at": datetime.utcnow().isoformat()
    }

    try:
        r = requests.post(
            f"{SUPABASE_URL}/rest/v1/parlay_slips",
            headers=SUPABASE_HEADERS,
            json=payload,
            timeout=10
        )
        if r.status_code in (200, 201):
            return jsonify({"slip_id": slip_id})
        else:
            return jsonify({"error": f"Supabase error: {r.status_code} {r.text[:200]}"}), 500
    except Exception as e:
        return jsonify({"error": str(e)}), 500

# ── Load slip from Supabase ────────────────────────────────────────────────
@app.route("/api/slip/<slip_id>")
def load_slip(slip_id):
    if not SUPABASE_URL or not SUPABASE_ANON_KEY:
        return jsonify({"error": "Supabase not configured"}), 500
    try:
        r = requests.get(
            f"{SUPABASE_URL}/rest/v1/parlay_slips?slip_id=eq.{slip_id.upper()}&select=*",
            headers=SUPABASE_HEADERS,
            timeout=10
        )
        rows = r.json()
        if not rows:
            return jsonify({"error": "Slip not found"}), 404
        row = rows[0]
        return jsonify({
            "slip_id": row["slip_id"],
            "data":    json.loads(row["data"]),
            "picks":   json.loads(row["picks"]),
            "created_at": row["created_at"]
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500

# ── Slip viewer page ───────────────────────────────────────────────────────
@app.route("/slip/<slip_id>")
def slip_page(slip_id):
    return render_template("slip.html", slip_id=slip_id.upper())

# ── Save slip ─────────────────────────────────────────────────────────────
@app.route("/api/slip/save", methods=["POST"])
def save_slip():
    body    = request.get_json(force=True) or {}
    slip_id = str(uuid.uuid4())[:8].upper()
    payload = {
        "slip_id":    slip_id,
        "data":       json.dumps(body.get("data", {})),
        "picks":      json.dumps(body.get("picks", [])),
        "created_at": datetime.utcnow().isoformat()
    }
    try:
        r = requests.post(
            f"{SUPABASE_URL}/rest/v1/parlay_slips",
            headers=SUPABASE_HEADERS, json=payload, timeout=10
        )
        if r.status_code in (200, 201):
            return jsonify({"slip_id": slip_id})
        return jsonify({"error": f"Supabase: {r.status_code} {r.text[:200]}"}), 500
    except Exception as e:
        return jsonify({"error": str(e)}), 500

# ── Load slip ──────────────────────────────────────────────────────────────
@app.route("/api/slip/<slip_id>")
def load_slip(slip_id):
    try:
        r = requests.get(
            f"{SUPABASE_URL}/rest/v1/parlay_slips?slip_id=eq.{slip_id.upper()}&select=*",
            headers=SUPABASE_HEADERS, timeout=10
        )
        rows = r.json()
        if not rows:
            return jsonify({"error": "Slip not found"}), 404
        row = rows[0]
        return jsonify({
            "slip_id":    row["slip_id"],
            "data":       json.loads(row["data"]),
            "picks":      json.loads(row["picks"]),
            "created_at": row["created_at"]
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500

# ── Slip viewer page ───────────────────────────────────────────────────────
@app.route("/slip/<slip_id>")
def slip_page(slip_id):
    return render_template("slip.html", slip_id=slip_id.upper())

if __name__=="__main__":
    app.run(debug=True)
