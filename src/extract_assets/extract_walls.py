"""
7) Extract wall_list.json from scene.json
-----------------------------------------

We extract “wall groups” from scene.json. Each wall group contains a “true wall” which is an asset that is actually labeled to be a wall. Then, because assets that are not labeled as walls may actually be a part of walls, like windows, doors, finishes, panels, etc., we calculate, based on positioning and also on the labels we have added, whether to group these assets with the respective “true wall."

INPUTS
 - input_scene: path to scene.json
 - output_scene: directory where wall_list.json is going to be saved

OUTPUTS
 - wall_list.json: list of wall groups with:
    - wall_asset: the "true wall" object key from the group
    - wall_type: type of wall ["door", "window", etc.] of the true wall
    - assets: list of keys for nearby 'wall_part' objects associated with the wall group


APPROACH
 1. Identify wall objects:
    - Select objects that have a 'wall_type' but do not have a 'floor_description'
    - Extract their XY positions from the placements
 2. Group walls by proximity:
    - Group walls if their 2D positions are within 0.1 units of each other
 3. For each wall group:
    - Calculate a unified bounding box that covers all walls in the group
    - Search for nearby objects that are designated as 'wall_part' (excluding walls and floors) if they are within 0.3 units of the bounding box (this threshold is kind of random)
"""
import argparse
import json
import os
import sys
import math


# ---------------------------------------------------------------------
#                               HELPERS
# ---------------------------------------------------------------------

"""
HELPER

Checks if the 2D distance between posA=(x1,y1) and posB=(x2,y2) is <= threshold.
"""
def wall_positions_close(posA, posB, threshold=0.5):
    dx = posA[0] - posB[0]
    dy = posA[1] - posB[1]
    dist_sq = dx*dx + dy*dy
    return dist_sq <= (threshold*threshold)

"""
HELPER

Checks if point (px, py) is within threshold distance of the bounding box in XY.
bbox = (minX, minY, maxX, maxY).
"""
def point_is_near_box(px, py, bbox, threshold=0.3):
    minx, miny, maxx, maxy = bbox
    cx = max(minx, min(px, maxx))
    cy = max(miny, min(py, maxy))
    dist_sq = (cx - px)**2 + (cy - py)**2
    return dist_sq <= (threshold**2)


# ---------------------------------------------------------------------
#                               MAIN
# ---------------------------------------------------------------------

"""
MAIN HELPER

Reads scene.json, identifies 'true walls' (objects that have 'wall_type'
but are not floors). Then groups them by checking if their (x,y) positions
are within 0.1 units. After grouping, for each wall group, find nearby
'wall_part' objects within ~0.3 distance of that group's bounding box in XY.

Writes 'wall_list.json' with format:
[
    {
    "wall_asset": "someWallKey",
    "wall_type": "solid_wall",
    "assets": ["objectKey1","objectKey2", ...]  // only wall_part
    },
    ...
]
"""
def extract_walls(scene_json_path, wall_list_path):
    with open(scene_json_path, 'r') as f:
        scene_data = json.load(f)


    # we need a better way to dect these walls

    objects_dict = scene_data.get("objects", {})

    # 1) Identify all "wall" objects
    wall_items = []
    for obj_key, obj_data in objects_dict.items():
        # Must have wall_type but no floor_description
        if "wall_type" not in obj_data:
            continue
        if "floor_description" in obj_data:
            continue  # skip if also recognized as a floor

        wtype = obj_data["wall_type"]

        placements = obj_data.get("placements", [])
        if not placements or not isinstance(placements, list):
            continue
        pos = placements[0].get("position", [0, 0, 0])
        if len(pos) < 2:
            pos += [0.0] * (2 - len(pos))
        px, py = float(pos[0]), float(pos[1])

        wall_items.append((obj_key, wtype, (px, py)))

    # 2) Group walls by proximity
    position_threshold = 0.1
    groups = []

    for witem in wall_items:
        placed = False
        for grp in groups:
            for w2 in grp:
                if wall_positions_close(witem[2], w2[2], threshold=position_threshold):
                    grp.append(witem)
                    placed = True
                    break
            if placed:
                break
        if not placed:
            groups.append([witem])

    # 3) For each group, pick a "main" wall + unify bounding box
    wall_list = []
    for grp in groups:
        main_key, main_wtype, main_pos = grp[0]
        # We'll unify bounding box across all walls in grp
        group_minx = math.inf
        group_miny = math.inf
        group_maxx = -math.inf
        group_maxy = -math.inf

        for (k, wtype, (wx, wy)) in grp:
            od = objects_dict.get(k, {})
            dims = od.get("dimensions", [0, 0, 0])
            if len(dims) < 2:
                continue
            try:
                width = float(dims[0])
                length = float(dims[1])
            except:
                continue
            w_minx = wx
            w_maxx = wx + width
            w_miny = wy
            w_maxy = wy + length

            group_minx = min(group_minx, w_minx)
            group_miny = min(group_miny, w_miny)
            group_maxx = max(group_maxx, w_maxx)
            group_maxy = max(group_maxy, w_maxy)

        group_box = (group_minx, group_miny, group_maxx, group_maxy)

        # 4) Find nearby objects that are "wall_part" only
        assets_set = set()
        for ok, od in objects_dict.items():
            # skip walls + floors
            if "wall_type" in od:
                continue
            if "floor_description" in od:
                continue

            # if not a 'wall_part', skip
            if od.get("object_type") != "wall_part":
                continue

            placements2 = od.get("placements", [])
            if not placements2:
                continue

            pos2 = placements2[0].get("position", [0, 0, 0])
            if len(pos2) < 2:
                continue

            px2, py2 = float(pos2[0]), float(pos2[1])

            if point_is_near_box(px2, py2, group_box, threshold=0.3):
                assets_set.add(ok)

        rec = {
            "wall_asset": main_key,   # representative wall in group
            "wall_type": main_wtype,
            "assets": list(assets_set)
        }
        wall_list.append(rec)

    # 5) Save to wall_list.json
    with open(wall_list_path, 'w') as f:
        json.dump(wall_list, f, indent=4)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--input_scene", required=True)
    parser.add_argument("--output_scene", required=True)
    args = parser.parse_args()

    extract_walls(args.input_scene, args.output_scene)

if __name__ == "__main__":
    main()
