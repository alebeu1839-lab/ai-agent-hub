"""One bounded explicit scheduler tick for INTERNAL work only."""

class Orchestrator:
    def __init__(self, retry_planner, parallel_runner):
        self.retry_planner = retry_planner
        self.parallel_runner = parallel_runner

    def tick(self, *, at=None, max_workers=2, max_tasks=10):
        if type(max_tasks) is not int or not 1 <= max_tasks <= 100:
            raise ValueError("max_tasks must be 1..100")
        if type(max_workers) is not int or not 1 <= max_workers <= 8:
            raise ValueError("max_workers must be 1..8")
        requeued = self.retry_planner.requeue_due(at=at, limit=max_tasks)
        results = self.parallel_runner.tick(max_workers=max_workers, max_tasks=max_tasks)
        scheduled = []
        for result in results:
            if result.state == "rate_limited":
                scheduled.append(self.retry_planner.schedule(
                    result.task_id, error="provider rate limit", at=at))
        return {"requeued": requeued, "executed": results, "scheduled": scheduled}
