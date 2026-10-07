"""Independent replay of observable schedule constraints; no simulator import.

Checks feasibility and trace consistency, not optimality or historical award
quality. Timing is reconstructed from command logs and the supplied parameter
table instead of accepting the simulator's job summaries as proof.
"""
import argparse
import json
from pathlib import Path

EPS = 1e-6


def require(condition, message):
    if not condition:
        raise ValueError(message)


def equal(a, b):
    return abs(a-b) <= EPS


def verify(trace, expected_params=None):
    p, mode = trace["params"], trace["mode"]
    if expected_params is not None:
        require(p == expected_params, "parameter table changed")
    require(mode in {"single","two"}, "unsupported processing mode")
    first = set(trace["first_machines"])
    n, horizon = trace["machine_count"], trace["horizon"]
    require(1 <= n <= 8, "invalid machine count")
    require(mode == "single" or 0 < len(first) < n, "invalid fixed tool assignment")
    phase_for = {i:0 if mode=="single" else (1 if i in first else 2) for i in range(1,n+1)}
    processing = {0:p["single"], 1:p["first"], 2:p["second"]}
    faults = { (f["job"],f["phase"]):f for f in trace["faults"] }
    require(len(faults)==len(trace["faults"]), "duplicate fault record")
    current = {i:None for i in range(1,n+1)}
    phases, delivered, pending = {}, {}, None
    holder, position, clock = None, 0, 0.0
    commands = trace["actions"]
    for index, a in enumerate(commands):
        start, end, kind = a["start"], a["end"], a["kind"]
        require(equal(start, clock) and end>=start and end<=horizon+EPS, f"RGV overlap/gap/shift violation at {index}")
        if kind in {"move","return"}:
            require(pending is None, "movement before finished part clean/delivery")
            target=a["to_position"]
            require(a["from_position"]==position and 0 <= target <= (n-1)//2, "invalid RGV movement endpoint")
            require(equal(end-start,p["move"][abs(position-target)]), "travel time differs from official table")
            if kind=="return":
                require(target==0,"return did not reach initial position")
            position=target
        elif kind=="wait":
            require(a["position"]==position and pending is None, "invalid wait position/pending product")
        elif kind=="service":
            require(pending is None, "service before preceding final product is cleaned")
            cnc, phase = a["cnc"], a["phase"]
            require(cnc in current and phase_for[cnc]==phase, "CNC changed its fixed tool")
            require(position==(cnc-1)//2, "RGV serviced a CNC at a different position")
            service=p["odd"] if cnc%2 else p["even"]
            require(equal(end-start,service), "wrong load/unload duration")
            loaded, unloaded = a["loaded"], a["unloaded"]
            active=current[cnc]
            if active is not None:
                active_phase=phases[(active,phase)]
                failure=faults.get((active,phase))
                if failure is not None and failure["start"]<=start+EPS:
                    require(failure["end"]<=start+EPS and unloaded is None, "serviced CNC during repair or unloaded failed part")
                else:
                    require(start+EPS>=active_phase["load_end"]+processing[phase], "unloaded before machining finished")
                    require(unloaded==active, "overwrote an occupied CNC or mismatched unloaded part")
            else:
                require(unloaded is None, "unloaded a part from an empty CNC")
            require(a["holder_before"]==holder, "incorrect intermediate carrier before service")
            require(int(loaded is not None)+int(unloaded is not None)<=2, "more than two RGV paws used")
            require(a["max_paws"]==int(loaded is not None)+int(unloaded is not None), "wrong reported paw count")
            if unloaded is not None:
                require((unloaded,phase) in phases, "unloaded part was never loaded")
                require("unload_start" not in phases[(unloaded,phase)], "part unloaded twice")
                phases[(unloaded,phase)].update(unload_start=start,unload_end=end)
            if phase==1:
                require(holder is None, "two-process heuristic took a second intermediate part")
                holder=unloaded
            elif phase==2:
                require(loaded==holder, "second process loaded a different/unavailable intermediate part")
                if loaded is not None:
                    parent=phases.get((loaded,1))
                    require(parent is not None and "unload_end" in parent and parent["unload_end"]<=start+EPS,
                            "second processing before first processing/transfer finished")
                holder=None
                pending=unloaded
            else:
                require(holder is None, "unexpected intermediate part in single processing")
                pending=unloaded
            require(a["holder_after"]==holder, "incorrect intermediate carrier after service")
            current[cnc]=loaded
            if loaded is not None:
                require((loaded,phase) not in phases, "part loaded twice into same processing phase")
                phases[(loaded,phase)]=dict(cnc=cnc,load_start=start,load_end=end)
        elif kind=="clean":
            job=a["job"]
            require(pending==job and a["position"]==position, "cleaned wrong/unavailable final product")
            require(equal(end-start,p["clean"]), "wrong cleaning/delivery duration")
            require(job not in delivered, "product delivered twice")
            require(not any(j==job for j,_ in faults), "failed/discarded product counted as delivered")
            delivered[job]=end
            pending=None
        else:
            raise ValueError(f"unknown action {kind}")
        clock=end
    require(equal(clock,horizon) and position==0 and trace["end_position"]==0, "shift did not end at initial RGV position")
    require(pending is None,"final product never cleaned/delivered")
    for (job,phase),failure in faults.items():
        info=phases.get((job,phase))
        require(info is not None and info["cnc"]==failure["cnc"], "fault does not belong to a machining phase")
        require(info["load_end"]<=failure["start"]<info["load_end"]+processing[phase], "fault outside actual processing interval")
        require(trace["repair_range"][0]-EPS<=failure["end"]-failure["start"]<=trace["repair_range"][1]+EPS,
                "repair duration outside declared bounds")
        require("unload_start" not in info,"failed workpiece subsequently unloaded as successful")
    require(trace["count"]==len(delivered), "reported production differs from replayed deliveries")
    require(set(trace["completed_jobs"])==set(delivered) and len(trace["completed_jobs"])==len(delivered),
            "completed-product list differs from replay")
    require(trace["failures"]==len(faults), "failure count inconsistent")
    summaries={j["id"]:j for j in trace["jobs"]}
    require(len(summaries)==len(trace["jobs"])==trace["started"], "invalid job summaries")
    require(set(summaries)=={job for job,_ in phases}, "unregistered/extra job summary")
    for (job,phase),info in phases.items():
        stored=summaries[job]["phases"][str(phase)]
        for key,value in info.items():
            require(key in stored and equal(stored[key],value), f"job summary differs from reconstructed {key}")
    for job,summary in summaries.items():
        require(summary["discarded"]==any(j==job for j,_ in faults), "discard flag inconsistent")
        if job in delivered:
            require(equal(summary["delivered"],delivered[job]), "incorrect delivered timestamp")
    return dict(status="pass",scope="schedule feasibility and output trace consistency; not optimality",
                commands_checked=len(commands),phases_checked=len(phases),products_replayed=len(delivered),
                failures_checked=len(faults),shift_seconds=horizon,end_position=position)


if __name__=="__main__":
    p=argparse.ArgumentParser()
    p.add_argument("trace",type=Path)
    p.add_argument("--parameters",type=Path)
    args=p.parse_args()
    trace=json.loads(args.trace.read_text(encoding="utf-8"))
    expected=None
    if args.parameters:
        groups=json.loads(args.parameters.read_text(encoding="utf-8"))["groups"]
        expected=next(g for g in groups if g["group"]==trace["params"]["group"])
    print(json.dumps(verify(trace,expected),ensure_ascii=False,indent=2))
