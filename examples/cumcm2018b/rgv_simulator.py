"""2018 CUMCM B practice solver, written for this reproduction, not upstream code.

Demand-triggered discrete-event scheduling. The controller sees only observed
machine states; future fault events are private to the physical event queue.
Two-process policy carries at most one intermediate part and fixes each CNC's
tool for the whole shift. This is a restricted heuristic, not an optimal solver.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import heapq
import itertools
import json
import math
import random
import statistics
import time
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OFFICIAL = "https://en.mcm.edu.cn/html_en/node/b4184fa60b0e32c59e451c1e351d321d.html"
PARAMETERS = [
    dict(group=1, move=[0, 20, 33, 46], single=560, first=400, second=378, odd=28, even=31, clean=25),
    dict(group=2, move=[0, 23, 41, 59], single=580, first=280, second=500, odd=30, even=35, clean=30),
    dict(group=3, move=[0, 18, 32, 46], single=545, first=455, second=182, odd=27, even=32, clean=25),
]


def write_json(path: Path, obj):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8")


@dataclass
class Machine:
    number: int
    phase: int
    state: str = "idle"
    job: int | None = None
    ready_since: float = 0.0
    generation: int = 0

    @property
    def position(self):
        return (self.number - 1) // 2


class Simulation:
    def __init__(self, params, mode="single", first_machines=(), policy="greedy", horizon=28800,
                 fault_probability=0.0, repair_range=(600, 1200), seed=0, machine_count=8):
        if mode not in {"single", "two"} or policy not in {"greedy", "cyclic", "oldest"}:
            raise ValueError("unknown mode or policy")
        if not 0 <= fault_probability <= 1 or horizon < 0 or machine_count < 1 or machine_count > 8:
            raise ValueError("invalid probability, horizon or machine count")
        if mode == "two" and not 0 < len(set(first_machines)) < machine_count:
            raise ValueError("two-process requires both fixed tool groups")
        if any(i < 1 or i > machine_count for i in first_machines):
            raise ValueError("invalid machine assignment")
        self.p, self.mode, self.policy, self.horizon = dict(params), mode, policy, horizon
        self.first = sorted(set(first_machines))
        self.fault_probability, self.repair_range, self.seed = fault_probability, repair_range, seed
        # Separate streams prevent a repair draw from changing subsequent failure Bernoulli draws.
        self.failure_rng, self.timing_rng = random.Random(seed), random.Random(seed ^ 0x51A7)
        self.machines = [Machine(i, 0 if mode == "single" else (1 if i in self.first else 2))
                         for i in range(1, machine_count + 1)]
        self.clock, self.position, self.carried = 0.0, 0, None
        self.events, self.event_serial = [], 0
        self.jobs, self.actions, self.faults, self.completed = {}, [], [], []
        self.last_served = {0: 0, 1: 0, 2: 0}

    def duration(self, phase):
        return self.p[{0: "single", 1: "first", 2: "second"}[phase]]

    def queue(self, when, kind, machine, job, generation):
        self.event_serial += 1
        heapq.heappush(self.events, (when, self.event_serial, kind, machine.number, job, generation))

    def advance(self, target):
        if target < self.clock - 1e-9:
            raise AssertionError("clock reversal")
        while self.events and self.events[0][0] <= target + 1e-9:
            when, _, kind, number, job_id, generation = heapq.heappop(self.events)
            m = self.machines[number - 1]
            if m.generation != generation:
                continue
            if kind == "finish" and m.state == "busy" and m.job == job_id:
                m.state, m.ready_since = "done", when
                self.jobs[job_id]["phases"][str(m.phase)]["finish"] = when
            elif kind == "fault" and m.state == "busy" and m.job == job_id:
                job = self.jobs[job_id]
                job["discarded"] = True
                repair = self.timing_rng.uniform(*self.repair_range)
                self.faults.append(dict(job=job_id, cnc=number, phase=m.phase, start=when, end=when + repair))
                m.state, m.job = "broken", None
                m.generation += 1  # invalidates the originally planned finish event
                self.queue(when + repair, "repair", m, None, m.generation)
            elif kind == "repair" and m.state == "broken":
                m.state, m.ready_since = "idle", when
        self.clock = target

    def action(self, kind, duration, **data):
        if duration < 0:
            raise AssertionError("negative action")
        start, end = self.clock, self.clock + duration
        if end > self.horizon + 1e-9:
            raise AssertionError("shift exceeded")
        self.actions.append(dict(kind=kind, start=start, end=end, **data))
        self.advance(end)

    def eligible(self):
        # Crucially: dispatcher does not inspect self.events or unobserved future failures.
        ready = [m for m in self.machines if m.state in {"idle", "done"}]
        if self.mode == "single":
            return ready
        if self.carried is not None:
            return [m for m in ready if m.phase == 2]
        return [m for m in ready if m.phase == 1 or (m.phase == 2 and m.state == "done")]

    def service_time(self, m):
        return self.p["odd"] if m.number % 2 else self.p["even"]

    def choose(self, choices):
        if self.policy == "greedy":
            def key(m):
                clean = self.p["clean"] if m.state == "done" and m.phase in {0, 2} else 0
                return (self.p["move"][abs(self.position - m.position)] + self.service_time(m) + clean,
                        m.ready_since, m.number)
        elif self.policy == "oldest":
            def key(m):
                return (m.ready_since, self.p["move"][abs(self.position - m.position)], m.number)
        else:
            def key(m):
                n = len(self.machines)
                return ((m.number - self.last_served[m.phase] - 1) % n, m.number)
        return min(choices, key=key)

    def start_processing(self, m, job_id, load_start, load_end):
        job = self.jobs[job_id]
        job["phases"][str(m.phase)] = dict(cnc=m.number, load_start=load_start, load_end=load_end)
        m.job, m.state = job_id, "busy"
        m.generation += 1
        process_time = self.duration(m.phase)
        self.queue(load_end + process_time, "finish", m, job_id, m.generation)
        if self.failure_rng.random() < self.fault_probability:
            # This future time is known to the simulator, never to choose()/eligible().
            failure_time = load_end + self.timing_rng.uniform(0.000001, process_time - 0.000001)
            self.queue(failure_time, "fault", m, job_id, m.generation)

    def run(self, trace=True):
        while self.clock < self.horizon:
            choices = self.eligible()
            if not choices:
                if not self.events:
                    break
                stop_at = self.horizon - self.p["move"][self.position]
                when = min(self.events[0][0], stop_at)
                if when <= self.clock + 1e-9:
                    break
                self.action("wait", when - self.clock, reason="await observed machine event", position=self.position)
                continue
            m = self.choose(choices)
            old_job = m.job if m.state == "done" else None
            cleaned_job = old_job if m.phase in {0, 2} else None
            move = self.p["move"][abs(self.position - m.position)]
            clean = self.p["clean"] if cleaned_job is not None else 0
            required = move + self.service_time(m) + clean + self.p["move"][m.position]
            if self.clock + required > self.horizon + 1e-9:
                break
            if move:
                self.action("move", move, from_position=self.position, to_position=m.position)
                self.position = m.position
            # Other CNCs can finish/fail during travel; chosen ready CNC cannot fail while idle/done.
            before = self.carried
            if m.phase in {0, 1}:
                new_job = len(self.jobs) + 1
                self.jobs[new_job] = dict(id=new_job, phases={}, discarded=False)
            else:
                new_job = self.carried  # may be None for final-product unload-only
            start, end = self.clock, self.clock + self.service_time(m)
            after = old_job if m.phase == 1 else None
            max_paws = int(new_job is not None) + int(old_job is not None)
            self.action("service", end - start, cnc=m.number, phase=m.phase,
                        loaded=new_job, unloaded=old_job, holder_before=before,
                        holder_after=after, max_paws=max_paws)
            if old_job is not None:
                old_phase = self.jobs[old_job]["phases"][str(m.phase)]
                old_phase.update(unload_start=start, unload_end=end)
            self.carried = after
            m.job, m.state, m.ready_since = None, "idle", end
            if new_job is not None:
                self.start_processing(m, new_job, start, end)
            self.last_served[m.phase] = m.number
            if cleaned_job is not None:
                self.action("clean", self.p["clean"], job=cleaned_job, position=self.position)
                self.jobs[cleaned_job]["delivered"] = self.clock
                self.completed.append(cleaned_job)
        if self.position:
            self.action("return", self.p["move"][self.position], from_position=self.position, to_position=0)
            self.position = 0
        if self.clock < self.horizon:
            self.action("wait", self.horizon - self.clock, reason="shift end", position=0)
        utilization = sum(a["end"] - a["start"] for a in self.actions if a["kind"] != "wait") / self.horizon if self.horizon else 0
        answer = dict(params=self.p, mode=self.mode, first_machines=self.first, policy=self.policy,
                      horizon=self.horizon, fault_probability=self.fault_probability, repair_range=list(self.repair_range),
                      seed=self.seed, machine_count=len(self.machines), count=len(self.completed),
                      started=len(self.jobs), failures=len(self.faults), rgv_busy_fraction=utilization,
                      solver_status="feasible heuristic; no global-optimality proof",
                      controller_information="observed idle/done/broken states only; no future failure times")
        if trace:
            answer.update(actions=self.actions, jobs=list(self.jobs.values()), faults=self.faults,
                          completed_jobs=self.completed, end_position=self.position)
        return answer


def simulate(params, **kwargs):
    trace = kwargs.pop("trace", True)
    return Simulation(params, **kwargs).run(trace=trace)


def upper_bound(p, mode):
    if mode == "single":
        return math.floor(min(8 * 28800 / p["single"], 28800 / (p["odd"] + p["clean"])))
    # Relaxations omit startup, all travel, loading downtime and return-to-home.
    capacities = [min(m * 28800 / p["first"], (8-m) * 28800 / p["second"],
                      28800 / (2 * p["odd"] + p["clean"])) for m in range(1, 8)]
    return math.floor(max(capacities))


def interval(values):
    n, mean = len(values), statistics.mean(values)
    sd = statistics.stdev(values) if n > 1 else 0
    # Descriptive normal-approximation Monte Carlo interval, not a factory guarantee.
    half = 1.96 * sd / math.sqrt(n)
    return dict(n=n, mean=mean, sd=sd, minimum=min(values), maximum=max(values),
                mean_ci95_normal=[mean-half, mean+half])


def main(seeds):
    from verify_schedule import verify
    began = time.perf_counter()
    root = ROOT / "results"
    root.mkdir(exist_ok=True)
    parameter_file = ROOT / "support_materials/official_parameters.json"
    write_json(parameter_file, dict(source=OFFICIAL, anchor="Problem B page 2 Table 1; seconds", groups=PARAMETERS))
    healthy, search_rows, selected, fault_rows, sensitivity = [], [], {}, [], []
    feasibility_checks = []
    def run_case(params, **settings):
        keep_trace = settings.pop("trace", True)
        result = simulate(params, **settings, trace=True)
        check = verify(result, params)
        feasibility_checks.append(dict(group=params["group"], mode=result["mode"],
             policy=result["policy"], first_machines=result["first_machines"],
             probability=result["fault_probability"], repair_range=result["repair_range"], seed=result["seed"],
             count=result["count"], status=check["status"], commands_checked=check["commands_checked"]))
        if not keep_trace:
            for key in ("actions","jobs","faults","completed_jobs","end_position"):
                result.pop(key)
        return result
    for p in PARAMETERS:
        group = p["group"]
        single = [run_case(p, policy=policy, trace=False) for policy in ("cyclic", "greedy", "oldest")]
        best_single = max(single, key=lambda r: (r["count"], -r["rgv_busy_fraction"]))
        for r in single:
            healthy.append(dict(group=group, mode="single", policy=r["policy"], first_machines="", count=r["count"], upper_bound=upper_bound(p,"single")))
        best_two = None
        for policy in ("cyclic", "greedy"):
            for size in range(1, 8):
                for assignment in itertools.combinations(range(1, 9), size):
                    r = run_case(p, mode="two", first_machines=assignment, policy=policy, trace=False)
                    search_rows.append(dict(group=group, first_machines="-".join(map(str, assignment)), count=r["count"], policy=policy))
                    if best_two is None or (r["count"], -r["rgv_busy_fraction"]) > (best_two["count"], -best_two["rgv_busy_fraction"]):
                        best_two = r
        baseline = run_case(p, mode="two", first_machines=[1,3,5,7], policy="cyclic", trace=False)
        greedy_baseline = run_case(p, mode="two", first_machines=[1,3,5,7], policy="greedy", trace=False)
        for label, r in (("cyclic_alternating", baseline), ("greedy_alternating", greedy_baseline), ("best_of_two_assignment_search", best_two)):
            healthy.append(dict(group=group, mode="two", policy=label, first_machines="-".join(map(str,r["first_machines"])), count=r["count"], upper_bound=upper_bound(p,"two")))
        selected[str(group)] = dict(single_policy=best_single["policy"], two_policy=best_two["policy"], first_machines=best_two["first_machines"])
        for mode in ("single", "two"):
            settings = dict(mode=mode, policy=best_single["policy"] if mode == "single" else best_two["policy"],
                            first_machines=[] if mode == "single" else best_two["first_machines"])
            for fault_p, suffix in ((0.0,"healthy"),(0.01,"fault_seed_0")):
                r = run_case(p, **settings, fault_probability=fault_p, seed=0)
                write_json(root / f"trace_group{group}_{mode}_{suffix}.json", r)
            actual = []
            baseline_values = []
            failures = []
            for seed in range(seeds):
                r = run_case(p, **settings, fault_probability=0.01, seed=seed, trace=False)
                actual.append(r["count"])
                failures.append(r["failures"])
                base_settings = dict(mode=mode, policy="cyclic", first_machines=[] if mode=="single" else [1,3,5,7])
                b = run_case(p, **base_settings, fault_probability=0.01, seed=seed, trace=False)
                baseline_values.append(b["count"])
            fault_rows.append(dict(group=group, mode=mode, selected=interval(actual), baseline=interval(baseline_values),
                                   mean_failures=statistics.mean(failures), seeds=list(range(seeds)),
                                   sample_counts=actual, baseline_sample_counts=baseline_values,
                                   prefix16=interval(actual[:16]),
                                   pairing_caveat="same seed does not imply same job-machine failure realization across policies"))
            for probability in (0.005, 0.01, 0.02):
                for repair_range in ((600,900),(600,1200),(900,1200)):
                    values = [run_case(p, **settings, fault_probability=probability, repair_range=repair_range,
                                       seed=seed, trace=False)["count"] for seed in range(seeds)]
                    sensitivity.append(dict(group=group, mode=mode, fault_probability=probability,
                                            repair_range=list(repair_range), sample_counts=values, **interval(values)))
    for name, rows in (("healthy_comparison.csv",healthy),("assignment_search.csv",search_rows)):
        with (root/name).open("w",newline="",encoding="utf-8-sig") as f:
            w=csv.DictWriter(f,fieldnames=list(rows[0]));w.writeheader();w.writerows(rows)
    output = dict(problem="CUMCM 2018 B practice", source=OFFICIAL, healthy=healthy, selected=selected,
                  faults=fault_rows, sensitivity=sensitivity, assignments_tested_per_group=254,
                  policies_per_assignment=2, feasibility_checks_count=len(feasibility_checks),
                  parameter_sha256=hashlib.sha256(parameter_file.read_bytes()).hexdigest(),
                  python_source_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                  elapsed_seconds=time.perf_counter()-began,
                  assumptions=["one percent interpreted per machining start; independent Bernoulli events",
                               "fault time uniform within nominal processing; repair uniform within specified bounds",
                               "immediate complete clean/delivery after final unloading; no cleaning-slot pipelining optimization",
                               "two-process policy carries at most one intermediate part; no external buffer",
                               "unload-only service conservatively charged full tabulated load/unload time",
                               "future failure events private to physical simulator, not scheduling policy"],
                  conclusion_scope="best observed within stated policies and fixed-tool assignments; not global optimality")
    write_json(root/"experiment_summary.json",output)
    write_json(root/"all_feasibility_checks.json",feasibility_checks)
    print(json.dumps({"healthy":healthy,"faults":fault_rows,"elapsed_seconds":output["elapsed_seconds"]},ensure_ascii=False,indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--seeds", type=int, default=32)
    args=parser.parse_args()
    if args.seeds < 2:
        parser.error("at least two seeds are required")
    main(args.seeds)
