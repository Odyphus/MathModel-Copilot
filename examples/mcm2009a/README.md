# Historical MCM traffic circle example

This independent case uses the mathematical task in COMAP's [2009 MCM Problem A](https://www.contest.comap.com/undergraduate/contests/mcm/contests/2009/problems/), consulted on 2026-10-05. The official problem and student solutions are not redistributed. `problem.md` is an original short interpretation. Code and all traffic scenarios in this directory were authored for this project; synthetic rates must not be described as observed traffic.

From the product root, with Python 3.10+; this example uses only the standard library and requires no pip installation:

```bash
python examples/mcm2009a/run_example.py --workspace ../mcm-traffic-new
python scripts/copilot.py --workspace ../mcm-traffic-new status
```

The directory must be new or empty. The default run evaluates a 600-second fluid experiment, three demand patterns, three demand multipliers, and eight controllers per demand case. It freezes the actual solver, parameters and checker, then runs the same Requirement → Model → Run → Validation → Result → Claim → PaperSection chain as the existing CUMCM case. All 72 candidate ledgers and the original comparison table are retained. The checker independently checks 43,200 time steps; it does not import the solver.

Use `--horizon 30` for a shorter integration experiment, not as the documented full example. A full run has no external dataset dependency and uses only Python's standard library beyond the core runtime. Document generation additionally needs the document dependency group and a real DOCX-to-PDF backend; see `../v020_paper/README.md`.

The model tracks approach and circulating queues. At each junction it compares circulating priority, entering priority and isolated signal phases. The score is accumulated occupancy plus a terminal congestion penalty, normalized by arrivals. Signal candidates have equal or demand-weighted positive green allocations and clearance intervals. The experiment includes balanced, directional and overloaded synthetic demands, with lower and higher demand-to-capacity ratios.

Validation checks conservation, nonnegative states, junction capacity, exact control priority, signal phase allocation, grid completeness, objective arithmetic and every exported table value. Unit tests add analytically known low-demand behavior, zero demand and deliberately corrupted trajectories/metrics. This is implementation validation of the stated approximation, not field calibration or a safety assessment.

Limitations include fractional vehicles, geometric trip lengths, no lane geometry, no finite storage/spillback and no pedestrian or collision model. The finite controller winner is not a universal or global optimum. The technical summary describes when additional measurements and human engineering review are needed. Rules, public rights, human final review and actual submission remain distinct; `submission.ready` stays false in `historical_benchmark` mode.
