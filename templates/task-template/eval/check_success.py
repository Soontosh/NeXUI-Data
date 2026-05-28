from nexui.success import evaluate_success_from_manifest


def check_success(task, trace):
    return evaluate_success_from_manifest(
        task,
        trace,
        fallback_final_snapshot=task.start_snapshot,
        fallback_note="Template success checker still uses placeholder logic.",
    )
