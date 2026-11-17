"""Opt-in local CLI adapter for AI coding tools.

This adapter is NOT enabled by default. It does not infer CLI flags,
start a shell, or take arbitrary commands from a task payload.
The operator supplies a fixed command prefix after manual CLI verification.
"""
from dataclasses import dataclass
import os
import subprocess
from pathlib import Path
from .dispatcher import WorkResult

@dataclass(frozen=True)
class CLIConfig:
    name: str
    executable: str
    fixed_args: tuple[str, ...] = ()
    working_directory: str = "."
    timeout_seconds: int = 90
    enabled: bool = False

class CLIAdapter:
    def __init__(self, config: CLIConfig, *, runner=subprocess.run):
        self.config = config
        self.runner = runner
        if not config.name or not config.executable:
            raise ValueError("tool name and executable required")
        if not 1 <= config.timeout_seconds <= 3600:
            raise ValueError("invalid CLI timeout")
        if not all(isinstance(arg,str) for arg in config.fixed_args):
            raise ValueError("fixed CLI arguments must be strings")

    def __call__(self, task):
        if not self.config.enabled:
            raise PermissionError("CLI disabled: explicit local setup required")
        if not isinstance(task, dict) or not isinstance(task.get("task_id"),str):
            raise ValueError("task_id required")
        # Only explicitly whitelisted internal task instructions are used.
        instruction = task.get("instruction")
        if not isinstance(instruction,str) or not 0 < len(instruction) <= 8000:
            raise ValueError("bounded instruction required")
        cwd = Path(self.config.working_directory).resolve(strict=True)
        # CLI flags and binary are specified out of band, never from untrusted task payload.
        args = [self.config.executable, *self.config.fixed_args]
        safe_env = {k:v for k,v in os.environ.items()
                    if k in ("PATH","HOME","USERPROFILE","TEMP","TMP","SYSTEMROOT")}
        # Credentials and provider-specific environment must be injected by a
        # separately reviewed secure deployment, not passed through by default.
        result = self.runner(args, cwd=str(cwd), input=instruction,
                             text=True, capture_output=True,
                             timeout=self.config.timeout_seconds,
                             env=safe_env, check=False)
        if result.returncode:
            raise RuntimeError("CLI exited unsuccessfully (details withheld to avoid secret leakage)")
        if not isinstance(result.stdout,str) or not result.stdout.strip():
            raise ValueError("CLI returned empty output")
        # Store actual outputs in an authenticated artifact store before production use.
        # Until then, return only a reference marker, never claim persisted delivery.
        return WorkResult(output_ref="unpersisted://"+task["task_id"],
                          summary="CLI ran locally; output persistence not implemented")
