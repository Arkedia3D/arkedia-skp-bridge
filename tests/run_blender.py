# -*- coding: utf-8 -*-
"""Lance un script de ce dossier dans Blender en arrière-plan, avec un profil jetable.

    python run_blender.py <script.py> [arguments du script ...]

Équivaut à : blender -b --factory-startup --python <script.py> -- <arguments>, avec les variables
BLENDER_USER_* pointant vers tests/.sandbox pour ne pas toucher au profil de l'utilisateur.
"""
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import _env  # noqa: E402

if len(sys.argv) < 2:
    raise SystemExit(__doc__)
script = sys.argv[1]
if not os.path.isabs(script) and not os.path.exists(script):
    script = os.path.join(HERE, script)
cmd = [_env.blender_exe(), "-b", "--factory-startup", "--python", os.path.abspath(script), "--"] + sys.argv[2:]
sys.exit(subprocess.call(cmd, env=_env.sandbox_env()))
