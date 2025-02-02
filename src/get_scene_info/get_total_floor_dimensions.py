"""
4) Find current floor dimensions
--------------------------------

Determines the total X (width) and Y (length) dimensions of all floor assets in scene.json.

INPUTS
- scene_json_path: path to 'scene.json'
- blend_name: name of the blend file because it is the prefix for the asset names in scene.json, we need it to be able to distinguish floors

OUTPUTS
- Dictionary containing:
    - "total_X": Sum of all floor widths
    - "total_Y": Sum of all floor lengths


APPROACH
1. Identify Floor Objects
    - Strip the blend_name prefix from object keys and then get objects where "room" appears in the name

2. Extract and Sum Dimensions
    - Get dimensions (X, Y, Z)
    - Add up valid X and Y values across all floor objects
"""

import json
import os
import sys

def get_total_floor_dimensions(scene_json_path, blend_name):

    with open(scene_json_path, 'r') as f:
        scene_data = json.load(f)

    objects_dict = scene_data.get("objects", {})

    total_X = 0.0
    total_Y = 0.0

    prefix = f"{blend_name}-"

    for obj_key, obj_details in objects_dict.items():
        # Remove the blend file name prefix from the object key
        if obj_key.startswith(prefix):
            obj_key_stripped = obj_key[len(prefix):]
        else:
            obj_key_stripped = obj_key

        # Check if the object is a floor
        if 'room' in obj_key_stripped.lower():
            dimensions = obj_details.get("dimensions", [0.0, 0.0, 0.0])
            if len(dimensions) >= 2:
                x = float(dimensions[0])
                y = float(dimensions[1])
                total_X += x
                total_Y += y

    return {"total_X": total_X, "total_Y": total_Y}
