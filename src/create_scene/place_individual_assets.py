"""
10) Place individual objects
----------------------------

This script places leftover, non-cloneable assets (i.e., assets that the grouping model determined should not be duplicated as groups) into a new scene that already contains scaled floors and walls. The placement is done by computing a pivot-based XY shift using the global pivot of the original scene and optionally anchoring the Z position based on a scaled floor.

INPUTS
 - original_scene: path to original scene.json
 - asset_group_list: path to asset_group_list.json
 - new_scene: path to new_scene.json
 - scale_factor: scale factor

OUTPUTS
 - new_scene: The updated scene JSON file with the leftover non-cloneable assets placed with adjusted XY positions and
   (if possible) anchored Z positions relative to a scaled floor.

APPROACH
 1. Load the original scene to retrieve the original positions, dimensions, placements, rotations, and scales
 2. Load the new scene, which already includes the scaled floors and walls
 3. Identify a scaled floor within the new scene (by searching for keys containing "floor" or "room" along with "_scaled") to determine a reference Z position. If found, use its final Z position to anchor the leftover objects; otherwise, the leftover objects keep their original Z values
 4. Load asset_group_list.json and iterate over its groups. Skip any group with "Cloneable": true
 5. For each asset in the non-cloneable groups:
    - Compute the global pivot (based on the original scene) by determining the bounding box of all objects
    - Calculate a pivot-based XY offset for the object using the provided scale_factor
    - Adjust the object's Z position relative to the scaled floor (if available)
    - Insert the transformed object into the new scene with a new unique identifier (by appending "_placed")
 6. Write out the updated new_scene JSON containing the newly placed leftover objects
"""

import argparse
import json
import os
import sys
import math
import copy

"""
MAIN HELPER

1) Load original_scene => all objects (with original positions).
2) Load new_scene => scaled floors/walls are in it. We'll append leftover 
    *non-cloneable* objects in that new scene.
3) Load asset_group_list => skip groups that are Cloneable=True, only place groups 
    where Cloneable=False. For each group, for each asset => place it with pivot-based 
    XY shift, local scale=1.0, anchored in Z if possible.
"""
def place_individual_assets(
    original_scene_path,
    asset_group_list_path,
    new_scene_path,
    scale_factor
):

    # 1) Load original scene
    with open(original_scene_path, 'r') as f:
        original_data = json.load(f)

    orig_objs = original_data.get("objects", {})

    # 2) Load new scene
    with open(new_scene_path, 'r') as f:
        new_scene_data = json.load(f)

    if "objects" not in new_scene_data:
        new_scene_data["objects"] = {}
    new_objs = new_scene_data["objects"]

    # 2a) Identify a scaled floor for anchoring Pz offset
    scaled_floor_key = None
    floor_final_pz = 0.0
    old_floor_pz = 0.0
    anchor_with_floor = False

    for k, od in new_objs.items():
        # We look for a floor/room key that has "_scaled"
        # Adapt if your naming differs
        if ("floor" in k.lower() or "room" in k.lower()) and "_scaled" in k.lower():
            pls = od.get("placements", [])
            if not pls:
                continue
            final_pz = pls[0]["position"][2]
            base_key = k.split("_scaled")[0]

            old_floor_obj = orig_objs.get(base_key)
            if not old_floor_obj:
                continue
            old_pz = old_floor_obj["placements"][0]["position"][2]

            scaled_floor_key = k
            floor_final_pz = final_pz
            old_floor_pz = old_pz
            anchor_with_floor = True

            break

    # 3) Load asset_group_list
    with open(asset_group_list_path, 'r') as f:
        asset_groups = json.load(f)

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

        if x1 < gminx: gminx = x1
        if x2 > gmaxx: gmaxx = x2
        if y1 < gminy: gminy = y1
        if y2 > gmaxy: gmaxy = y2

    pivot_x = 0.5 * (gminx + gmaxx)
    pivot_y = 0.5 * (gminy + gmaxy)

# ---------------------------------------------------------------------
#                               HELPERS
# ---------------------------------------------------------------------

    def get_orig_data(obj_key):
        od = orig_objs.get(obj_key)
        if not od:
            print(f" [WARN] leftover '{obj_key}' not in original scene.")
            return None
        dims = od.get("dimensions", [0,0,0])
        if len(dims) < 2:
            print(f" [WARN] leftover '{obj_key}' missing dims.")
            return None
        w, l = dims[0], dims[1]
        h = dims[2] if len(dims) >= 3 else 0.0

        pls = od.get("placements", [])
        if not pls:
            print(f" [WARN] leftover '{obj_key}' has no placements.")
            return None
        pos = pls[0].get("position", [0,0,0])
        while len(pos) < 3:
            pos.append(0.0)

        px, py, pz = pos[0], pos[1], pos[2]
        rot = pls[0].get("rotation", [0,0,0])
        old_local_scale = pls[0].get("scale", 1.0)

        return {
            "od": od,
            "px": px, "py": py, "pz": pz,
            "rot": rot,
            "w": w, "l": l, "h": h,
            "orig_scale": old_local_scale
        }

    def transform_xy(obj_key):
        info = get_orig_data(obj_key)
        if not info:
            return None

        dx = info["px"] - pivot_x
        dy = info["py"] - pivot_y
        new_px = pivot_x + dx*scale_factor
        new_py = pivot_y + dy*scale_factor

        return {
            "orig_key": obj_key,
            "orig_obj": info["od"],
            "dims": [info["w"], info["l"], info["h"]],
            "old_local_scale": info["orig_scale"],
            "old_pz": info["pz"],
            "temp_px": new_px,
            "temp_py": new_py,
            "temp_rot": info["rot"]
        }

    def insert_obj(tinfo):
        base_key = tinfo["orig_key"]
        new_key = base_key + "_placed"
        c = 1
        while new_key in new_objs:
            new_key = f"{base_key}_placed_{c}"
            c += 1

        new_od = copy.deepcopy(tinfo["orig_obj"])

        # Keep original dims
        new_od["dimensions"] = tinfo["dims"]

        # final pz
        if anchor_with_floor:
            # e.g. fully relative in Z
            final_pz = floor_final_pz + (tinfo["old_pz"] - old_floor_pz)*scale_factor
        else:
            final_pz = tinfo["old_pz"]

        pls = new_od.get("placements", [])
        if not pls or not isinstance(pls, list):
            new_od["placements"] = [{
                "position": [tinfo["temp_px"], tinfo["temp_py"], final_pz],
                "rotation": tinfo["temp_rot"],
                "scale": 1.0
            }]
        else:
            new_od["placements"][0]["position"] = [tinfo["temp_px"], tinfo["temp_py"], final_pz]
            new_od["placements"][0]["rotation"] = tinfo["temp_rot"]
            new_od["placements"][0]["scale"] = 1.0

        new_od["identifier"] = new_key
        new_objs[new_key] = new_od
        print(f"   => [NonCloneable] {base_key} => {new_key}, pz={final_pz:.3f}")

    # ---------------------------------------------------------------------
    #                               END HELPERS
    # ---------------------------------------------------------------------

    for grp in asset_groups:
        if not isinstance(grp, dict):
            continue
        if grp.get("Cloneable", True) is True:
            # skip cloneable groups
            continue

        grp_id = grp.get("id", 0)
        grp_name = grp.get("group_name", "UnnamedGroup")
        assets_list = grp.get("assets", [])

        for ak in assets_list:
            tinfo = transform_xy(ak)
            if tinfo:
                insert_obj(tinfo)

    # 5) Write updated new_scene
    with open(new_scene_path, 'w') as f:
        json.dump(new_scene_data, f, indent=4)

# ---------------------------------------------------------------------
#                               MAIN
# ---------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--original_scene", required=True)
    parser.add_argument("--asset_group_list", required=True)
    parser.add_argument("--new_scene", required=True)
    parser.add_argument("--scale_factor", required=True, type=float)
    args = parser.parse_args()

    place_individual_assets(
        original_scene_path=args.original_scene,
        asset_group_list_path=args.asset_group_list,
        new_scene_path=args.new_scene,
        scale_factor=args.scale_factor
    )

if __name__ == "__main__":
    main()
