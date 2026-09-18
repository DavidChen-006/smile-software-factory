# Worker prompt

Placeholder. S3 (the driver) fills this file with the work order a worker receives when the driver spawns it. The driver substitutes `{{bead_id}}`, `{{bead_title}}`, `{{bead_description}}`, `{{spec_path}}`, and `{{base_branch}}` before writing the order into the worker's worktree.
