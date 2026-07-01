"""Assemble parsed models into a single ERD bundle for the renderer."""
import copy


def _summary(model):
    rls = sum(len(t.get("rls", [])) for t in model["tables"])
    return {
        "name": model["model"]["name"],
        "guid": model["model"]["guid"],
        "tables": len(model["tables"]),
        "joins": len(model["joins"]),
        "findings": len(model.get("findings", [])),
        "rls": rls,
    }


def _redact(model):
    model = copy.deepcopy(model)
    for t in model["tables"]:
        for rule in t.get("rls", []):
            rule["expr"] = "(redacted)"
    return model


def assemble(models, *, max_models=25, redact_rls=False, log=None):
    kept = models[:max_models]
    dropped = [m["model"]["name"] for m in models[max_models:]]
    if dropped and log:
        log("Model cap reached (%d): dropped %d model(s): %s"
            % (max_models, len(dropped), ", ".join(dropped)))
    if redact_rls:
        kept = [_redact(m) for m in kept]
    return {"models": kept, "index": [_summary(m) for m in kept], "dropped": dropped}
