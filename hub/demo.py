"""Run an entirely offline demonstration; no credentials, calls, or payments."""
from pathlib import Path
from tempfile import TemporaryDirectory
from .task_store import TaskStore
from .organization import Organization
from .control_plane import ControlPlane
from .parallel import ParallelRunner
from .dispatcher import WorkResult
from .dashboard import write_dashboard

def demo(output_path=None):
    """Return a verifiable report. No real AI or platform interaction."""
    with TemporaryDirectory() as tmp:
        store = TaskStore(Path(tmp)/"work.sqlite")
        try:
            control = ControlPlane(store)
            company = Organization(store,control)
            plan=company.delegate("sandbox",scenario="website_prototype")
            def worker(payload):
                return WorkResult("mock://artifact/"+payload["task_id"],
                                  summary="simulated output")
            workers={"mock":worker}
            runner=ParallelRunner(store,control,workers=workers,
                                   department_workers={d:"mock" for d in
                                                       ("sales","production","qa","admin")})
            for _ in range(4):
                batch=runner.tick(max_workers=2,max_tasks=8)
                if not batch:
                    raise AssertionError("expected internal demo task")
                for result in batch:
                    if result.state!="reviewing":
                        raise AssertionError("demo worker failed")
                    store.transition(result.task_id,"completed",actor="demo_qa",
                                     note="simulated QA approval")
            report=company.executive_report("sandbox")
            if report["overall"]["states"].get("completed")!=4:
                raise AssertionError("all four mock tasks must finish")
            if output_path is not None:
                write_dashboard(store,output_path,project_id="sandbox")
            return report
        finally:
            store.close()

if __name__=="__main__":
    import argparse
    parser=argparse.ArgumentParser()
    parser.add_argument("--html",default=None,help="Optional local HTML output path")
    args=parser.parse_args()
    print(demo(args.html))
