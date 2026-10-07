"""Execute synthetic traffic scenarios from frozen Copilot ParameterSet."""
import csv,json
from pathlib import Path
from traffic_model import SCENARIOS, candidates

def main():
    context=json.loads(Path("run_context.json").read_text(encoding="utf-8"))
    values={row["parameter_id"]:row["current_value"] for row in context["ParameterSet"]["entries"]}
    rows=[]
    for scenario,rates in SCENARIOS.items():
        for factor in (0.8,1.0,1.2):
            trials=candidates([v*factor for v in rates],int(values["horizon"]),float(values["capacity"]))
            selected=min(range(len(trials)),key=lambda i:(trials[i]["mean_time_with_terminal_penalty"],i))
            rows.append({"scenario":scenario,"demand_factor":factor,"selected_index":selected,"candidates":trials})
    Path("results").mkdir()
    Path("results/traffic.json").write_text(json.dumps({"synthetic":True,"cases":rows},allow_nan=False),encoding="utf-8")
    with Path("results/comparison.csv").open("w",newline="",encoding="utf-8") as handle:
        writer=csv.writer(handle);writer.writerow(["scenario","factor","selected_mode","score","departed","residual"])
        for row in rows:
            chosen=row["candidates"][row["selected_index"]]
            writer.writerow([row["scenario"],row["demand_factor"],chosen["mode"],chosen["mean_time_with_terminal_penalty"],chosen["departed"],chosen["residual"]])
    summary="""# Technical Summary

Treat this model as a transparent screening calculation, not permission to change a real intersection. Measure approach arrivals, turn movements, queue storage and saturation flow before using it for a site. Replace the synthetic demands and compare circulating priority, entry priority and isolated signal phases with the same objective: accumulated occupancy plus a penalty for traffic left in the system.

At light demand, service priority can produce similar aggregate performance. As demand becomes uneven or exceeds capacity, inspect both approach queues and circulating queues: admitting vehicles quickly can merely move congestion into the circle. Signal control must also account for clearance losses; the fluid approximation omits safety benefits and therefore cannot decide whether unsignalized operation is safe.

For a signal candidate, divide the cycle after clearance time among entries, either equally or in proportion to measured demand. Round the green allocation while retaining a positive phase at each entry, then evaluate the saved plan and queue evolution. Repeat for changing demand and compare the residual traffic, rather than reporting throughput alone. The finite candidate table supplies example outcomes; it is not an optimum over all possible timings.

No field measurements or human engineering approval support this demonstration. Validate against observations and assess pedestrians, geometry, lane discipline and safety separately before applying any recommendation.
"""
    Path("results/technical_summary.md").write_text(summary,encoding="utf-8")
    print(json.dumps({"cases":len(rows),"candidates":sum(len(row["candidates"]) for row in rows)}))

if __name__=="__main__":main()
