# demo/frames

`simulated_cardiac.jpg` is the frame `/simulate/cardiac` sends with its injected `person_down`
(agent/DESIGN.md). It is a generated schematic: a floor, the taped zone and a stick figure, labeled
"SIMULATED FRAME". It contains no real person.

Regenerate it with `uv run python demo/frames/make_placeholder.py` (640x480 JPEG).

A human may replace it with a staged photo of the demo zone, but only of a teammate who agreed to
it, and only if the team is fine with that image being in the repo and being sent to the scene
verification model. Keep the same file name so the agent does not need to change.
