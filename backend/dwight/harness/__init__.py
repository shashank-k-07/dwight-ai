"""The real layer: a small tool-using Agent harness on the Sciforium pool models
(via dwight.glm), emitting OTel GenAI telemetry in the shape Dwight ingests.

  workspace.py  pinned OSS repo (tomli) + Kestrel workspace copies; blobctl hidden behind a shim
  tools.py      sandboxed tools (read_file, list_files, search, list_docs, read_doc, write_file, run_command)
  agent.py      SessionSpec -> run_session() -> SessionResult (OTLP payload + outcome)
  tasks.py      real-layer tasks + the 40-Session plan (clean / planted variants); storage tasks (04/16)
  checks.py     the storage_tasks.yaml check DSL
  settings.py   the storage-run settings file (data/real_scr_settings.json): pins model + settings for 04/16
  runner.py     parallel batches (<= 4), writes data/otlp/real/, the run manifest and the label file
  stats.py      data/real_layer_stats.json for the synthetic generator (07)

CLI: python -m dwight.harness --help
"""
