"""Run retained CUMCM code with separately obtained official assets."""
import argparse,importlib.util,shutil,tempfile
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
SOURCE=ROOT/'examples/cumcm2018b'

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--workspace',type=Path,required=True)
    p.add_argument('--assets-dir',type=Path,required=True,help='User-obtained official PDFs, empty XLS templates, and official_parameters.json')
    p.add_argument('--smoke',action='store_true')
    args=p.parse_args()
    required=['CUMCM-2018-Problem-B-English.pdf','CUMCM-2018-Problem-B-English-Appendix-1.pdf','Case_1_ result_E.xls','Case_2_ result_E.xls','Case_3_ result_1_E.xls','Case_3_ result_2_E.xls','official_parameters.json']
    missing=[name for name in required if not (args.assets_dir/name).is_file()]
    if missing:raise FileNotFoundError('Obtain the documented official assets first: '+', '.join(missing))
    with tempfile.TemporaryDirectory(prefix='cumcm-source-') as directory:
        example=Path(directory)
        for path in SOURCE.glob('*.py'):shutil.copy2(path,example/path.name)
        (example/'assets').mkdir()
        for name in required:shutil.copy2(args.assets_dir/name,example/'assets'/name)
        spec=importlib.util.spec_from_file_location('cumcm_benchmark',SOURCE/'run_benchmark.py')
        module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
        module.EXAMPLE=example
        module.run_benchmark(args.workspace,args.smoke)

if __name__=='__main__':main()
