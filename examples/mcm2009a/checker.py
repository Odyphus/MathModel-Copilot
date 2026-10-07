"""Independent conservation/capacity/signal accounting; does not import solver."""
import csv,json,math,sys
from pathlib import Path

def require(ok,message):
    if not ok:raise ValueError(message)
def close(a,b):return math.isclose(a,b,rel_tol=1e-8,abs_tol=1e-8)

def verify_trial(trial):
    rates=trial["rates"];horizon=trial["horizon"];capacity=trial["capacity"]
    require(len(trial["ledger"])==horizon,"Missing time steps")
    previous_q=previous_r=[0.0]*4;total_exit=area=0.0
    greens=trial["greens"]
    require(all(type(g) is int and g>0 for g in greens) and sum(greens)+8==trial["cycle"],"Bad signal plan")
    weights=rates if trial['weighted'] and sum(rates) else [1]*4
    quota=[(trial['cycle']-8)*weight/sum(weights) for weight in weights]
    expected_greens=[max(1,math.floor(value)) for value in quota]
    while sum(expected_greens)<trial['cycle']-8:
        index=max(range(4),key=lambda i:(quota[i]-expected_greens[i],-i));expected_greens[index]+=1
    while sum(expected_greens)>trial['cycle']-8:
        index=max((i for i in range(4) if expected_greens[i]>1),key=lambda i:(expected_greens[i]-quota[i],-i));expected_greens[index]-=1
    require(greens==expected_greens,'Green allocation differs from declared equal/proportional rule')
    for tick,row in enumerate(trial["ledger"]):
        require(row["tick"]==tick,"Missing or reordered time step")
        require(row["queue_before"]==previous_q and row["ring_before"]==previous_r,"Discontinuous state")
        require(row["arrivals"]==rates,"Demand drift")
        for key in ("queue_before","ring_before","entries","moves","departures","queue_after","ring_after"):
            require(len(row[key])==4 and all(math.isfinite(x) and x>=-1e-9 for x in row[key]),"Invalid queue or flow")
        for i in range(4):
            prior=(i-1)%4
            require(close(row["queue_before"][i]+rates[i]-row["entries"][i],row["queue_after"][i]),"Approach conservation failed")
            require(close(row["ring_before"][i]+row["entries"][i]+row["moves"][prior]-row["moves"][i]-row["departures"][i],row["ring_after"][i]),"Ring conservation failed")
            require(row["entries"][i]+row["moves"][prior]<=capacity+1e-9,"Junction capacity exceeded")
            require(close(row["departures"][i],min(row["ring_before"][i],capacity)/2),"Exit assumption violated")
            available=row["ring_before"][prior]-row["departures"][prior]
            demand=row["queue_before"][i]+rates[i]
            if trial["mode"]=="entry":
                require(close(row["entries"][i],min(demand,capacity)),"Entry priority violated")
                require(close(row["moves"][prior],min(available,capacity-row["entries"][i])),"Entry-priority circulation violated")
            else:
                require(close(row["moves"][prior],min(available,capacity)),"Circle priority violated")
                if trial["mode"]=="signal":
                    phase=tick%trial["cycle"];start=0;expected=None
                    for j,green in enumerate(greens):
                        if start<=phase<start+green:expected=j
                        start+=green+2
                    require(row["active"]==expected,"Signal timing differs")
                    if expected!=i:demand=0
                require(close(row["entries"][i],min(demand,capacity-row["moves"][prior])),"Entry service violated")
        previous_q,previous_r=row["queue_after"],row["ring_after"]
        total_exit+=sum(row["departures"]);area+=sum(previous_q)+sum(previous_r)
    residual=sum(previous_q)+sum(previous_r);arrived=horizon*sum(rates)
    require(close(arrived,total_exit+residual),"Global vehicle conservation failed")
    for key,value in (("arrived",arrived),("departed",total_exit),("residual",residual),("queue_area",area),("mean_time_with_terminal_penalty",(area+20*residual)/arrived if arrived else 0)):
        require(close(trial[key],value),"Wrong reported metric: "+key)
    return horizon

def check(root):
    root=Path(root);context=json.loads((root/"run_context.json").read_text(encoding="utf-8"))
    params={row["parameter_id"]:row["current_value"] for row in context["ParameterSet"]["entries"]}
    output=json.loads((root/"results/traffic.json").read_text(encoding="utf-8"))
    require(output["synthetic"] is True,"Missing synthetic-data boundary")
    expected={(name,factor) for name in ("balanced","commuter","overload") for factor in (0.8,1.0,1.2)}
    require(len(output["cases"])==9 and {(row["scenario"],row["demand_factor"]) for row in output["cases"]}==expected,"Scenario grid incomplete")
    metrics=[];ticks=0
    rates_by_name={"balanced":[0.13]*4,"commuter":[0.36,0.07,0.26,0.07],"overload":[0.48,0.26,0.40,0.26]}
    for row in output["cases"]:
        candidates=row["candidates"]
        specs={(t["mode"],t["cycle"],t["weighted"]) for t in candidates}
        expected_specs={("circle",60,False),("entry",60,False)}|{("signal",c,w) for c in (30,60,90) for w in (False,True)}
        require(len(candidates)==8 and specs==expected_specs,"Missing or duplicated controller candidate")
        for trial in candidates:
            require(trial["horizon"]==params["horizon"] and trial["capacity"]==params["capacity"],"Frozen parameter mismatch")
            require(trial["rates"]==[v*row["demand_factor"] for v in rates_by_name[row["scenario"]]],"Scenario demand mismatch")
            ticks+=verify_trial(trial)
        best=min(range(8),key=lambda i:(candidates[i]["mean_time_with_terminal_penalty"],i))
        require(row["selected_index"]==best,"Selected policy is not finite-grid optimum")
        chosen=candidates[best]
        metrics.append({"scenario":row["scenario"],"demand_factor":row["demand_factor"],"selected_mode":chosen["mode"],"cycle":chosen["cycle"],"greens":chosen["greens"],"departed":chosen["departed"],"residual":chosen["residual"],"score":chosen["mean_time_with_terminal_penalty"]})
    with (root/"results/comparison.csv").open(encoding="utf-8",newline="") as handle: table=list(csv.DictReader(handle))
    require(len(table)==len(metrics),"Missing comparison table rows")
    for actual,expected in zip(table,metrics):
        require(actual["scenario"]==expected["scenario"] and actual["selected_mode"]==expected["selected_mode"],"Comparison labels differ")
        for column,key in (("factor","demand_factor"),("score","score"),("departed","departed"),("residual","residual")):
            require(close(float(actual[column]),expected[key]),"Comparison cell differs")
    summary=(root/"results/technical_summary.md").read_text(encoding="utf-8")
    require(len(summary.split())<=300 and all(phrase in summary for phrase in ("synthetic","clearance","green","safety","No field measurements")),"Technical summary omits engineering limitations or exceeds compact length")
    return {"checks":[{"check_id":key,"status":"pass","evidence":["results/traffic.json","results/comparison.csv","results/technical_summary.md"]} for key in ("conservation","capacity_and_policy","selection_and_sensitivity","technical_summary")],
        "metrics":{"scenario_count":9,"candidate_count":72,"checked_steps":ticks,"horizon":params["horizon"],"capacity":params["capacity"],"selected":metrics},
        "scope":"Independent per-step accounting of synthetic fluid model; finite policy grid only; no road-safety or calibrated predictive claim"}

if __name__=="__main__":
    destination=Path(sys.argv[2])
    try: report=check(Path(sys.argv[1]))
    except Exception as exc:
        destination.write_text(json.dumps({"checks":[],"error":str(exc)}),encoding="utf-8");raise
    destination.write_text(json.dumps(report,indent=2),encoding="utf-8")
