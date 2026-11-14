"""Run each application's tests in an isolated interpreter (two glp packages)."""
from pathlib import Path
import subprocess
import sys


if __name__ == '__main__':
    root = Path(__file__).resolve().parent
    results = []
    for suite in ('research/supercompute/tests', 'SSQ/tests', 'DLT/tests'):
        command = [sys.executable, '-m', 'pytest', suite, '-q']
        print('COMMAND: '+ ' '.join(command), flush=True)
        result = subprocess.run(command, cwd=root)
        results.append((suite,result.returncode))
    print('SUITE_EXIT_CODES: '+repr(results), flush=True)
    raise SystemExit(int(any(code for _,code in results)))
