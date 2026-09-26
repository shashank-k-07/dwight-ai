"""Synthetic company dataset (ticket 07): the scale layer.

    params.py     data/synthetic/params.yaml (+ calibration.yaml overlay)
    content.py    GLM-written content library, bounded calls, cached to data/synthetic/content_library.json
    generate.py   deterministic Session composition -> data/otlp/synthetic/*.jsonl + data/ground-truth/
    calibrate.py  fit Session shapes to the real layer (data/otlp/real/)

CLI: python -m dwight.synth --help. data/synthetic/ and data/ground-truth/ are
generator inputs/outputs keyed by Initiative: no pipeline stage may read them
(the eval, 08, and acceptance checks, 15, read the ground truth).
"""
