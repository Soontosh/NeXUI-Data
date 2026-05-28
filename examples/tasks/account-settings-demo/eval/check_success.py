def check_success(task, trace):
    final_snapshot = task.start_snapshot
    for step in trace["steps"]:
        if step["after_snapshot"] is not None:
            final_snapshot = step["after_snapshot"]
    return {
        "task_success": final_snapshot == "s002" and trace["result"]["status"] == "completed",
        "notes": [
            f"Final snapshot observed: {final_snapshot}"
        ]
    }
