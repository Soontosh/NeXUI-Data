from nexui.success import evaluate_success_from_manifest


def check_success(task, trace):
    return evaluate_success_from_manifest(
        task,
        trace,
        fallback_final_snapshot="s013",
    )
