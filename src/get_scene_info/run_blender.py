"""
2) Render images with Blender
-----------------------------

Runs a Blender script in an isolated environment.
We call this in main.py to get images for each asset.

INPUTS
 - blender_executable: executable.
 - blender_script: Blender Python script.
 - args: List of arguments to pass to the Blender script.

OUTPUTS
 - script dependent, but see get_image.py
"""

import subprocess
import os
import sys

def run_blender_script(blender_executable, blender_script, args):
    # Prep command
    command = [
        blender_executable,
        "--background",
        "--python", blender_script,
        "--",
    ] + args

    # Setup env
    clean_env = os.environ.copy()
    python_vars = ['PYTHONPATH', 'VIRTUAL_ENV', 'PYTHONHOME']
    for var in python_vars:
        if var in clean_env:
            del clean_env[var]

    # Run command
    result = subprocess.run(command, env=clean_env, capture_output=True, text=True)


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--blender_executable", required=True)
    parser.add_argument("--blender_script", required=True)
    parser.add_argument("--args", nargs=argparse.REMAINDER)
    args = parser.parse_args()

    run_blender_script(args.blender_executable, args.blender_script, args.args or [])
