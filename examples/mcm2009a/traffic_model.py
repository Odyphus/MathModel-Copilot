"""Original fluid-queue teaching model for the historical MCM traffic-circle task.

All demand and capacities are synthetic, NOT calibrated traffic observations.
One second is one step. Vehicles are divisible fluid, not individual drivers.
The model distinguishes approach queues, circulating traffic and departures.
"""
from __future__ import annotations
import math

SCENARIOS = {
    "balanced": [0.13, 0.13, 0.13, 0.13],
    "commuter": [0.36, 0.07, 0.26, 0.07],
    "overload": [0.48, 0.26, 0.40, 0.26],
}


def green_plan(rates, cycle, weighted):
    """Reserve clearance per phase; positive integer green time at each entry."""
    available = cycle - 8
    weights = rates if weighted and sum(rates) else [1] * 4
    raw = [available * value / sum(weights) for value in weights]
    green = [max(1, math.floor(value)) for value in raw]
    while sum(green) < available:
        i = max(range(4), key=lambda i: (raw[i] - green[i], -i))
        green[i] += 1
    while sum(green) > available:
        i = max((i for i in range(4) if green[i] > 1), key=lambda i: (green[i] - raw[i], -i))
        green[i] -= 1
    return green


def simulate(rates, *, mode="circle", horizon=600, capacity=0.8, cycle=60, weighted=False):
    if mode not in {"circle", "entry", "signal"}:
        raise ValueError("Unknown control policy")
    if len(rates) != 4 or any(not math.isfinite(x) or x < 0 for x in rates):
        raise ValueError("Four finite nonnegative synthetic demands required")
    if type(horizon) is not int or horizon <= 0 or not math.isfinite(capacity) or capacity <= 0:
        raise ValueError("Positive horizon and capacity required")
    if type(cycle) is not int or cycle < 12:
        raise ValueError("Cycle must leave positive green time after clearances")
    queue, ring, area, exited = [0.0]*4, [0.0]*4, 0.0, 0.0
    greens = green_plan(rates, cycle, weighted)
    ledger = []
    for tick in range(horizon):
        before_queue, before_ring = queue[:], ring[:]
        queue = [queue[i] + rates[i] for i in range(4)]
        # A fixed fraction exits at each junction; remaining fluid competes
        # with entrants for the downstream junction capacity. This geometric
        # trip length is a modeling assumption, not measured turn movements.
        departures = [min(ring[i], capacity) * 0.5 for i in range(4)]
        available_ring = [ring[i] - departures[i] for i in range(4)]
        active = None
        if mode == "signal":
            phase = tick % cycle
            for i, green in enumerate(greens):
                if phase < green:
                    active = i
                    break
                phase -= green + 2
                if phase < 0:
                    break
        entries, moves = [0.0]*4, [0.0]*4
        for i in range(4):
            previous = (i - 1) % 4
            demand = queue[i] if mode != "signal" or active == i else 0.0
            if mode == "entry":
                entries[i] = min(demand, capacity)
                moves[previous] = min(available_ring[previous], capacity-entries[i])
            else:
                moves[previous] = min(available_ring[previous], capacity)
                entries[i] = min(demand, capacity-moves[previous])
        queue = [queue[i] - entries[i] for i in range(4)]
        ring = [available_ring[i] - moves[i] + moves[(i-1)%4] + entries[i] for i in range(4)]
        exited += sum(departures)
        area += sum(queue) + sum(ring)
        ledger.append({"tick":tick,"queue_before":before_queue,"ring_before":before_ring,
            "arrivals":rates[:],"entries":entries,"moves":moves,"departures":departures,
            "queue_after":queue[:],"ring_after":ring[:],"active":active})
    arrived = horizon * sum(rates)
    residual = sum(queue) + sum(ring)
    return {"mode":mode,"cycle":cycle,"weighted":weighted,"greens":greens,
        "rates":rates,"horizon":horizon,"capacity":capacity,
        "arrived":arrived,"departed":exited,"residual":residual,"queue_area":area,
        "mean_time_with_terminal_penalty":(area+20*residual)/arrived if arrived else 0.0,
        "ledger":ledger}


def candidates(rates, horizon, capacity):
    specs = [{"mode":"circle"},{"mode":"entry"}]
    specs += [{"mode":"signal","cycle":cycle,"weighted":weighted} for cycle in (30,60,90) for weighted in (False,True)]
    return [simulate(rates,horizon=horizon,capacity=capacity,**spec) for spec in specs]
