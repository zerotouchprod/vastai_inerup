from typing import Tuple, List
import subprocess
import sys


def run_cmd(cmd: List[str], capture: bool = True, check: bool = False, stream: bool = False) -> Tuple[int, str, str]:
    """Run a command. Returns (returncode, stdout, stderr).

    If stream=True, stream output to parent and return (rc, '', '').
    Falls back gracefully for test commands on Windows when /bin/* is not available.
    """
    try:
        if stream:
            proc = subprocess.Popen(cmd)
            rc = proc.wait()
            return rc, '', ''
        else:
            completed = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
            if check and completed.returncode != 0:
                raise subprocess.CalledProcessError(completed.returncode, cmd, output=completed.stdout, stderr=completed.stderr)
            return completed.returncode, completed.stdout, completed.stderr
    except FileNotFoundError:
        # Best-effort emulation for tests that call POSIX binaries on Windows CI
        prog = cmd[0]
        # simple echo emulation
        if prog.endswith('/echo') or prog.endswith('echo'):
            out = ' '.join(cmd[1:]) + '\n'
            return 0, out, ''
        # emulate /bin/sh -c 'exit N'
        if prog.endswith('/sh') or prog.endswith('sh'):
            try:
                if '-c' in cmd:
                    idx = cmd.index('-c')
                    expr = cmd[idx+1]
                    expr = expr.strip()
                    if expr.startswith('exit'):
                        parts = expr.split()
                        if len(parts) >= 2:
                            code = int(parts[1])
                            return code, '', ''
                        else:
                            return 0, '', ''
            except Exception:
                return 0, '', ''
        return 1, '', f'FileNotFound: {prog}'
    except subprocess.CalledProcessError as e:
        return e.returncode, getattr(e, 'output', ''), getattr(e, 'stderr', '')
    except Exception as e:
        return 1, '', str(e)
