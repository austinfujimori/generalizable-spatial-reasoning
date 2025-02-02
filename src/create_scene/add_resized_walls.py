"""
8) Scale the walls and add them to new_scene.json
-------------------------------------------------

Scale the walls and add them to new_scene.json, also repositions them to the new relative position and adjusts the dimensions.

INPUTS
 - original_scene: path to scene.json (the original one)
 - wall_list: path to wall_list.json
 - new_scene: path to the new scene (new_scene.json)
 - scale_factor: scale factor in all dimensions


APPROACH
 1. Load the original scene to extract original positions, dimensions, rotations, and scales
 2. Load the new scene (with scaled floors) to serve as the base for appending walls
 3. Identify a single scaled floor to serve as an anchor
    - Retrieve its final Z position and compare it with the original floor's Z position
    - If no scaled floor is found, walls retain their original Z positions
    - This is our relative positioning technique to account for the new scale of the room
 4. Compute the global pivot from the original scene objects for consistent XY scaling
 5. For each wall group in wall_list:
    - Scale the main wall in XY coordinates relative to the global pivot
    - Adjust the wall's Z position relative to the scaled floor's position
    - Scale each child wall asset using its relative offset from the main wall
    - Insert each scaled wall object into the new scene with a unique identifier
 6. Finally we just update the new scene, or new_scene.json
"""

import argparse
import json
import os
import sys
import math
import copy

"""
MAIN HELPER

1) Load original scene => to get old positions, rotations, etc.
2) Load new_scene => already contains scaled floors.
3) For each group in wall_list:
    - Scale the main wall in XY from the global pivot
    - Shift/scale its final Pz relative to the new floor's Pz (fully relative)
    - Do the same for each "child" asset in that wall group
"""
def add_resized_walls(original_scene, wall_list, new_scene, scale_factor):

    # 1) Load the original scene.
    with open(original_scene, 'r') as f:
        orig_data = json.load(f)
    orig_objs = orig_data.get("objects", {})

    # 2) Load the new scene (with scaled floors)
    with open(new_scene, 'r') as f:
        new_scene_data = json.load(f)

    if "objects" not in new_scene_data:
        new_scene_data["objects"] = {}
    new_objs = new_scene_data["objects"]

    # 2a) Find *one* scaled floor, so we can anchor walls properly.
    scaled_floor_key = None
    floor_final_pz = None
    old_floor_pz = None

    for k, od in new_objs.items():
        # e.g., floors often have "_scaled" and "room" in the name
        if "_scaled" in k.lower() and "room" in k.lower():
            placements = od.get("placements", [])
            if not placements:
                continue
            final_pz = placements[0]["position"][2]

            # Figure out base key by removing "_scaled"… 
            base_key = k.split("_scaled")[0]  # e.g. "dining_room-Room"
            old_floor_obj = orig_objs.get(base_key)
            if not old_floor_obj:
                continue

            old_pz = old_floor_obj["placements"][0]["position"][2]
            scaled_floor_key = k
            floor_final_pz = final_pz
            old_floor_pz = old_pz
            break

    # Fallback if none found => keep original wall Pz unmodified
    if floor_final_pz is None or old_floor_pz is None:
        floor_final_pz = 0.0
        old_floor_pz = 0.0
        anchor_with_floor = False
    else:
        anchor_with_floor = True

    # 3) Load wall_list (groups of walls + assets) and compute global pivot from the original scene for XY scaling (same pivot used for floors)
    gminx = math.inf
    gmaxx = -math.inf
    gminy = math.inf
    gmaxy = -math.inf

    for key, od in orig_objs.items():
        dims = od.get("dimensions", [0,0,0])
        if len(dims) < 2:
            continue
        w, l = dims[0], dims[1]
        pls = od.get("placements", [])
        if not pls:
            continue
        px, py = pls[0]["position"][0], pls[0]["position"][1]

        x1, x2 = px, px + w
        y1, y2 = py, py + l
        if x1 < gminx: 
            gminx = x1
        if x2 > gmaxx: 
            gmaxx = x2
        if y1 < gminy: 
            gminy = y1
        if y2 > gmaxy: 
            gmaxy = y2

    pivot_x = 0.5 * (gminx + gmaxx)
    pivot_y = 0.5 * (gminy + gmaxy)

    """
    HELPER
    
    retrieve original dims/pos/rot/etc
    """
    def get_orig_data(obj_key):
        od = orig_objs.get(obj_key)
        if not od:
            print(f"  [WARN] '{obj_key}' not in original scene.")
            return None
        dims = od.get("dimensions", [0,0,0])
        if len(dims) < 2:
            print(f"  [WARN] '{obj_key}' missing valid dims.")
            return None
        w, l, h = dims[0], dims[1], (dims[2] if len(dims) >= 3 else 0.0)

        pls = od.get("placements", [])
        if not pls:
            print(f"  [WARN] '{obj_key}' has no placements.")
            return None

        pos = pls[0].get("position", [0,0,0])
        if len(pos) < 3:
            pos += [0.0]*(3 - len(pos))
        px, py, pz = pos[0], pos[1], pos[2]

        rot = pls[0].get("rotation", [0,0,0])
        old_local_scale = pls[0].get("scale", 1.0)

        return {
            "w": w, "l": l, "h": h,
            "px": px, "py": py, "pz": pz,
            "rot": rot,
            "orig_scale": old_local_scale,
            "od": od
        }

    """
    HELPER

    scale object in XY from the global pivot (Z is handled as a separate step)
    """
    def scale_in_xy(obj_key):
        info = get_orig_data(obj_key)
        if not info:
            return None

        sw = info["w"] * scale_factor
        sl = info["l"] * scale_factor
        sh = info["h"] * scale_factor

        dx = info["px"] - pivot_x
        dy = info["py"] - pivot_y
        new_px = pivot_x + dx * scale_factor
        new_py = pivot_y + dy * scale_factor

        return {
            "orig_key": obj_key,
            "old_wall_pz": info["pz"],
            "scaled_w": sw,
            "scaled_l": sl,
            "scaled_h": sh,
            "temp_px": new_px,
            "temp_py": new_py,
            "temp_rot": info["rot"],
            "temp_old_scale": info["orig_scale"],
            "orig_objdict": info["od"]
        }


    """
    HELPER
    
    insert new scaled object into the new scene
    """
    def insert_obj(info, final_pz):
        base_key = info["orig_key"]
        new_key = base_key + "_scaled"
        c = 1
        while new_key in new_objs:
            new_key = f"{base_key}_scaled_{c}"
            c += 1

        new_obj = copy.deepcopy(info["orig_objdict"])

        # Update dimensions
        dims = new_obj.get("dimensions", [0,0,0])
        if len(dims) < 2:
            new_obj["dimensions"] = [info["scaled_w"], info["scaled_l"], info["scaled_h"]]
        else:
            new_obj["dimensions"][0] = info["scaled_w"]
            new_obj["dimensions"][1] = info["scaled_l"]
            if len(dims) >= 3:
                new_obj["dimensions"][2] = info["scaled_h"]
            else:
                new_obj["dimensions"].append(info["scaled_h"])

        # Update placements
        if "placements" not in new_obj or not isinstance(new_obj["placements"], list):
            new_obj["placements"] = [{
                "position": [info["temp_px"], info["temp_py"], final_pz],
                "rotation": info["temp_rot"],
                "scale": info["temp_old_scale"] * scale_factor
            }]
        else:
            new_obj["placements"][0]["position"] = [info["temp_px"], info["temp_py"], final_pz]
            new_obj["placements"][0]["rotation"] = info["temp_rot"]
            old_local_s = info["temp_old_scale"]
            new_obj["placements"][0]["scale"] = old_local_s * scale_factor

        new_obj["identifier"] = new_key
        new_objs[new_key] = new_obj

    # 4) For each wall group: scale main wall + child assets. Use fully relative offsets in Z, scaled by factor.
    for grp in groups:
        main_wall = grp.get("wall_asset")
        asset_list = grp.get("assets", [])

        # Scale main wall in XY
        winfo = scale_in_xy(main_wall)
        if not winfo:
            continue

        oldWallPz = winfo["old_wall_pz"]

        if anchor_with_floor:
            # FULLY RELATIVE offset from the scaled floor, scaled in Z
            finalWallPz = floor_final_pz + (oldWallPz - old_floor_pz) * scale_factor
        else:
            # fallback => keep the old Pz
            finalWallPz = oldWallPz

        insert_obj(winfo, finalWallPz)

        # Scale each asset => relative offset from the main wall, also scaled
        for ak in asset_list:
            ainfo = scale_in_xy(ak)
            if not ainfo:
                continue
            oldAssetPz = ainfo["old_wall_pz"]

            # For child => finalAssetPz = finalWallPz + scaled offset
            finalAssetPz = finalWallPz + (oldAssetPz - oldWallPz) * scale_factor
            insert_obj(ainfo, finalAssetPz)

    # 6) Update the new scene
    with open(new_scene, 'w') as f:
        json.dump(new_scene_data, f, indent=4)

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--original_scene", required=True)
    parser.add_argument("--wall_list", required=True)
    parser.add_argument("--new_scene", required=True)
    parser.add_argument("--scale_factor", required=True)
    args = parser.parse_args()

    add_resized_walls(
        original_scene=args.original_scene,
        wall_list=args.wall_list,
        new_scene=args.new_scene,
        scale_factor=float(args.scale_factor)
    )

if __name__ == "__main__":
    main()
