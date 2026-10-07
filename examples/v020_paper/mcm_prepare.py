"""Build the MCM-specific full English manuscript from the fresh verified run.

This prepares editable source and source-audit evidence. Rendering and visual
review are separate operations; neither is invented by this builder.
"""
import copy,json,sys
from decimal import Decimal,ROUND_HALF_EVEN
from pathlib import Path
from paper_paths import PRODUCT,PROJECT
sys.path.insert(0,str(PRODUCT/'scripts'))
from copilot_runtime import Runtime,project_status
from copilot_delivery import Delivery
from copilot_paper_source import audit_paper_source,paper_source_blocks
from copilot_section import section_projection
from build_documents import make_document,Renderer,save_json,sha

def main():
    rt=Runtime(PROJECT);rev=lambda:rt.read()['copilot']['revision'];delivery=Delivery(PROJECT)
    report=json.loads((PROJECT/'example-report.json').read_text(encoding='utf-8'))
    ids=report['objects'];cp=rt.read()['copilot'];metrics=cp['objects'][ids['result']]['payload']['metrics']
    (PROJECT/'paper').mkdir(exist_ok=True)
    claim_ids=[ids['claim']];rows=[];paragraphs=[]
    for i,row in enumerate(metrics['selected']):
        shown={key:format(Decimal(str(row[key])).quantize(Decimal('0.01'),rounding=ROUND_HALF_EVEN),'f') for key in ('score','departed','residual')}
        sentence=f"Scenario {row['scenario']} at demand factor {row['demand_factor']} selected {row['selected_mode']}; score {shown['score']} seconds, departed fluid {shown['departed']} vehicles, residual fluid {shown['residual']} vehicles."
        payload=copy.deepcopy(cp['objects'][ids['claim']]['payload']);payload.pop('status',None)
        payload.update(claim_id='MCM-ROW-'+str(i),claim=sentence,paper_anchor='paper/manuscript.md',display_contracts=[{
            'version':'0.1','result_id':ids['result'],'metric_path':f'/selected/{i}/{key}',
            'raw_value':str(row[key]),'display_value':shown[key],'format':'decimal','decimal_places':2,'rounding':'half_even'} for key in shown])
        claim=rt.claim(rev(),payload,[ids['result']])['result']['claim_id'];claim_ids.append(claim)
        paragraphs.append(sentence+' [[claim:'+claim+']]')
        rows.append('|'+ '|'.join([row['scenario'],str(row['demand_factor']),row['selected_mode'],shown['score'],shown['departed'],shown['residual']])+'|')
    original=cp['objects'][ids['claim']]['payload']['claim']+' [[claim:'+ids['claim']+']]'
    run=cp['objects'][ids['run']]
    summary_path=next(x['path'] for x in run['payload']['outputs'] if x['path'].endswith('technical_summary.md'))
    technical=(PROJECT/summary_path).read_text(encoding='utf-8')
    manuscript='''# Traffic Circle Control with Explicit Queue Accounting

Historical synthetic MCM example

# Summary Sheet

The purpose of this model is to compare entry rules while keeping all traffic accounted for. A ring-and-approach fluid model distinguishes vehicles waiting outside from those already circulating. A finite policy grid covers circulating priority, entering priority and isolated signal phases. The objective combines time spent in the system with a terminal congestion penalty, so a controller cannot look effective merely by moving a queue from an approach into the circle.

'''+original+'''

Results are illustrations of the declared synthetic demands and service assumptions. The selected control can change with load; signal clearance costs are retained. These findings do not establish a safe design for an observed junction, a global traffic optimum or a formal contest submission. Field data and a separate safety assessment would be necessary for those decisions.

Keywords: traffic circle; fluid queues; control comparison; conservation

'''+technical+'''
# Problem Interpretation and Scope

The historical COMAP task concerns choosing a traffic-circle control method, specifying objectives and influential factors, producing example applications and explaining signal allocation to an engineer. This manuscript provides that structure with newly authored synthetic examples. The official problem remains available at the linked source in the accompanying problem description; no official dataset or student solution is reproduced.

The model is deliberately a screening approximation. It has approach queues and circulating queues, a fixed chance of exiting at each junction, and a shared service limit at each merge. Fractional vehicles represent fluid flow. Finite storage, lane geometry, pedestrian phases, collision risk and driver behavior are not simulated. The scope is therefore method illustration and software evidence testing, not field validation.

# Assumptions and Objective

Demand is constant within each scenario. Departures occur before merge allocation; circulating flow and entering flow then compete for downstream service capacity. Entry priority gives waiting approaches first access, whereas circulation priority serves the upstream ring first. Signals gate entry while preserving circulation priority and explicit clearance intervals.

Let A be accumulated queue occupancy over the experiment, R be residual traffic, D be cumulative arrivals and P be the terminal penalty duration. The objective is defined by the native fraction below. A zero-arrival experiment is assigned zero score and checked as a boundary case.

$$J=\\frac{A+PR}{D}$$

This penalty makes the end of the experiment visible but does not solve the infinite-horizon control problem. Run duration, service assumptions, demand imbalance and penalty choice can affect rankings. A controller is selected only from the declared finite candidates; tied scores use a stable enumeration order.

# Control and Signal Algorithm

For every step, save the entire queue state, prescribed arrivals, allocated entries, circulating moves and departures. The next queue is determined by incoming minus outgoing flow. The independent checker replays these accounting identities and rejects negative queues, excess merge capacity, incorrect phases and metric drift.

Signal allocation first reserves clearance time, then distributes the remaining cycle equally or in proportion to approach demand. Integer rounding retains a positive phase for every approach and preserves the complete cycle length. Candidate cycles and demand perturbations are frozen in the executable input and source files. Signals here have clearance costs but no modeled safety advantage; the comparison must not be interpreted as advice to remove real traffic signals.

# Computed Scenarios and Sensitivity

Balanced demand, directional commuter demand and overload are evaluated at reduced, nominal and increased arrival rates. The following values come from the current run and independently checked ledger. Scores include the terminal penalty, and departures can be fractional because this is a fluid model.

| Scenario | Demand factor | Selected mode | Score seconds | Departed vehicles | Residual vehicles |
|---|---|---|---|---|---|
'''+ '\n'.join(rows)+'\n'+'\n'.join(paragraphs)+'''

# Validation and Limitations

The checker does not import the traffic solver. It verifies each time step using conservation, capacity, priority and phase identities; independently accumulates the objective; checks every comparison-table value; and confirms that the selected candidate has the lowest observed grid score. Analytic low-demand and zero-demand cases are tested separately. Corrupted flow, missing steps and altered reported metrics are deliberate negative tests.

These checks establish implementation consistency for the stated model. They do not verify the synthetic demand against real roads, prove safety, remove routing simplifications or compare all possible signal plans. The technical summary is checked for bounded length and explicit limitations; its engineering adequacy still requires human review.

# Conclusions

Explicit queues and conservation make the source of congestion inspectable. Comparing residual traffic alongside departures avoids hiding unfinished vehicles at the experiment boundary. Demand perturbations expose whether a selected finite-grid controller remains preferred under different loads. Practical deployment would require measured turning flows, calibrated service, finite storage and an independent safety study before any control change.

# Source and Reproduction

The accompanying original problem interpretation links directly to COMAP. Scenario constants are authored for this example, and the solver, checker, frozen run inputs and raw ledgers are included in the workspace. Reproduction must run in a new directory; existing authority and run receipts must not be overwritten.

# Report on Use of AI

OpenAI Codex assisted with model implementation, code review, experiment execution and this manuscript. Exact service model and version were not independently authenticated. The underlying results were actually executed and checked in the saved run. AI evaluation is not a team member signature or a human engineering review. No formal contest submission or official receipt exists.

'''
    path=PROJECT/'paper/manuscript.md';path.write_text(manuscript,encoding='utf-8')
    section=delivery.section(rev(),'paper.Q1','paper/manuscript.md',claim_ids)['result']['section_id']
    # The completed writing task is bound to a verified section, never a role label.
    rt.transition(rev(),'T-MCM-technical-summary','running',actor='writer')
    rt.transition(rev(),'T-MCM-technical-summary','completed',outputs=[section],actor='writer')
    contract={'version':'0.1','sections':[section],'supplements':[]}
    cp=rt.read()['copilot'];paper_source_blocks(PROJECT,cp,[section],contract)
    save_json(PROJECT/'paper/source_contract.json',contract)
    save_json(PROJECT/'paper/chain_plan.json',{'sections':[section],'claims':claim_ids,'source_run':ids['run'],'evaluation_mode':'historical_benchmark'})
    doc=make_document();doc.core_properties.title='Traffic Circle Control with Explicit Queue Accounting'
    doc.styles['Normal'].font.size=__import__('docx.shared',fromlist=['Pt']).Pt(12)
    doc.styles['Normal'].paragraph_format.line_spacing=1.15
    renderer=Renderer(doc,table_widths=[1600,1100,1250,1400,1800,1900],table_font_size=12);renderer.markdown(section_projection(cp,manuscript,root=PROJECT))
    for p in doc.paragraphs:
        if p.text in ('Technical Summary','Problem Interpretation and Scope','Report on Use of AI','Code Appendix'):
            p.paragraph_format.page_break_before=True
    in_summary=False
    for p in doc.paragraphs:
        if p.text=='Technical Summary':in_summary=True
        elif p.text=='Problem Interpretation and Scope':in_summary=False
        if in_summary:p.paragraph_format.line_spacing=2
    target=PROJECT/'paper/traffic-circle.docx';doc.save(target)
    audit=audit_paper_source(PROJECT,cp,[section],target,contract)
    save_json(PROJECT/'paper/source-audit-before-render.json',audit)
    save_json(PROJECT/'paper/paper.metadata.json',{'sha256':sha(target),'milestone':'working','history_class':'working_build','formal_history_eligible':False,'artifact_id':'ART-MCM-PAPER','formal_values_present':True,'run_id':ids['run'],'source_state_revision':cp['revision']})
    save_json(PROJECT/'paper/current-status.json',project_status(PROJECT,rt.read()))
    if not audit['passed']:raise RuntimeError(audit['errors'])
    print(json.dumps({'source_passed':True,'blocks':audit['source_block_count'],'docx':str(target)}))

if __name__=='__main__':main()
