"""Read source, actual PDF derivative and renderer record without state writes."""
import argparse,hashlib,json,sys,zipfile
from pathlib import Path
from xml.etree import ElementTree as ET
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'scripts'))
from copilot_runtime import Runtime,project_status
from copilot_paper_source import audit_paper_source
import copilot_document_checks as checks
from pypdf import PdfReader
def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()

def verify(project,docx,renderer_record,visual=None):
    project=Path(project).resolve();docx=project/docx;pdf=docx.with_suffix('.pdf')
    state=project/'state/decision_log.json';before=sha(state)
    rt=Runtime(project);log=rt.read();cp=log['copilot']
    plan=json.loads((project/'paper/chain_plan.json').read_text(encoding='utf-8'))
    contract=json.loads((project/'paper/source_contract.json').read_text(encoding='utf-8'))
    receipt=json.loads((project/renderer_record).read_text(encoding='utf-8'))
    source=audit_paper_source(project,cp,plan['sections'],docx,contract)
    render=bool(receipt.get('passed') and receipt.get('returncode')==0 and receipt.get('source_unchanged') is True and receipt.get('source_sha256')==sha(docx) and receipt.get('pdf_sha256')==sha(pdf))
    policy={'profile':'cumcm' if log.get('competition')=='cumcm' else 'generic','paper_max_bytes':25000000,'require_a4':True,'anonymity_required':False,'body_max_pages':30,'require_visual_qa':bool(visual),'ai_before_references':log.get('competition')=='cumcm'}
    metadata=project/'paper/pdf.metadata.json'
    # Metadata preparation is explicit evidence output, never canonical state.
    metadata.write_text(json.dumps({'sha256':sha(pdf),'source_docx_sha256':sha(docx),'conversion_direction':'DOCX_TO_PDF_ONLY','source_docx_editable_master':True,'history_class':'working_build'},indent=2),encoding='utf-8')
    reports={'paper_source':source,'docx':checks.audit_docx(docx,policy=policy,metadata_path=project/'paper/paper.metadata.json',visual_qa_path=project/visual if visual else None,evaluation_mode='historical_benchmark',file_reference_paths=tuple(row['path'] for row in source['files'])),
        'pdf':checks.audit_pdf(pdf,policy=policy,source_docx=docx,metadata_path=metadata,visual_qa_path=project/visual if visual else None)}
    with zipfile.ZipFile(docx) as archive:
        xml=ET.fromstring(archive.read('word/document.xml'))
        math_count=len(xml.findall('.//{http://schemas.openxmlformats.org/officeDocument/2006/math}oMath'))
    reader=PdfReader(pdf);texts=[p.extract_text() or '' for p in reader.pages]
    technical_pages=[i+1 for i,text in enumerate(texts) if 'Technical Summary' in text]
    return {'passed':render and math_count>0 and all(report['passed'] for report in reports.values()) and before==sha(state),
        'scope':'Source, actual PDF derivative and structural checks; visual review only when supplied; never human review',
        'reports':reports,'render_verified':render,'native_math_count':math_count,'pdf_page_count':len(texts),'technical_summary_start_pages':technical_pages,
        'source_sha256':sha(docx),'pdf_sha256':sha(pdf),'authority_unchanged':before==sha(state),'authority_sha256':before,
        'revision':cp['revision'],'status':project_status(project,log),'visual_review_supplied':bool(visual),'human_review_completed':False}

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--project',type=Path,required=True);p.add_argument('--docx',required=True);p.add_argument('--renderer-record',required=True);p.add_argument('--visual');p.add_argument('--output',type=Path,required=True)
    a=p.parse_args();result=verify(a.project,a.docx,a.renderer_record,a.visual);a.output.write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps({k:result[k] for k in ('passed','render_verified','native_math_count','pdf_page_count','authority_unchanged')},ensure_ascii=False))
    raise SystemExit(0 if result['passed'] else 1)
