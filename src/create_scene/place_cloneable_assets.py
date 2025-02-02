"""
11) Place cloned objects
------------------------

This script automatically clones and places groups of cloneable assets from the original scene into a new, scaled scene (which already includes scaled floors and walls). Cloneable asset groups are those that the grouping model has marked as "Cloneable": true. The script tiles each cloneable group based on the available floor dimensions and provided X/Y scale factors, while preserving each group's internal spacing.

INPUTS:
 - original_scene: path to original scene.json
   dimensions, placements, and rotations.
 - asset_group_list: path to asset_group_list.json
 - new_scene: path to new_scene.json
 - scale_factor_x: scale factor x
 - scale_factor_y: scale factor y, technically doesn't matter right now

OUTPUTS:
 - new_scene: The updated scene JSON file with the cloned asset groups placed. Each clone retains its original relative
   positions (with optional uniform scaling) and is shifted by computed offsets so that the groups are tiled with a small
   gap between them.

APPROACH:
 1. Load the original scene to retrieve object data (positions, dimensions, and placements) needed for computing bounding
    boxes and centroids for each cloneable group
 2. Load the new scene to determine the scaled floor dimensions and to obtain an anchor for adjusting Z positions. The script searches for an object with "floor" or "room" in its key (along with "_scaled") and reads its dimensions and final Z value
 3. Load asset_group_list.json and filter the groups to include only those marked as cloneable
 4. For each cloneable group:
    a) Compute the bounding box and centroid of the group from the original scene.
    b) Determine the number of clone tiles along the X and Y axes based on the provided scale_factor_x and scale_factor_y
    c) Calculate a spacing (gap) between clone tiles
    d) For each clone tile, compute an offset and clone every asset in the group while preserving each asset's relative
       offset from the group centroid. Optionally, adjust the asset's Z coordinate relative to the scaled floor
    e) Assign a unique identifier for each cloned asset by appending clone indices to the original key
 5. Save the updated new_scene JSON file with all the cloned asset groups appended
"""


import argparse
import json
import os
import sys
import math
import copy


"""
MAIN HELPER

1) Load the original scene => get object positions and bounding boxes.
2) Load the new scene => find scaled floor => read new floor dimensions (X, Y).
3) Load asset_group_list => for each group with "Cloneable": true, do:
    a) Compute bounding box of the group in original scene.
    b) Decide how many times to clone the group horizontally/vertically.
    c) Keep the group's internal spacing (do not stretch per-asset).
    d) Move each cloned group by an offset, thereby spacing groups out.
"""
def place_cloneable_assets(
    original_scene_path,
    asset_group_list_path,
    new_scene_path,
    scale_factor_x,
    scale_factor_y
):

    # 1) Load original scene
    with open(original_scene_path, 'r') as f:
        original_data = json.load(f)

    orig_objs = original_data.get("objects", {})

    # 2) Load the new scene (scaled floors)
    with open(new_scene_path, 'r') as f:
        new_scene_data = json.load(f)

    if "objects" not in new_scene_data:
        new_scene_data["objects"] = {}
    new_objs = new_scene_data["objects"]

    # 2a) Locate the scaled floor to find new floor dimensions
    new_floor_width = None
    new_floor_length = None
    floor_final_pz = 0.0
    old_floor_pz = 0.0
    anchor_with_floor = False

    for key, obj in new_objs.items():
        key_lower = key.lower()
        if ("floor" in key_lower or "room" in key_lower) and "_scaled" in key_lower:
            dimensions = obj.get("dimensions", [0, 0, 0])
            if len(dimensions) < 2:
                continue
            new_floor_width = float(dimensions[0])
            new_floor_length = float(dimensions[1])

            placements = obj.get("placements", [])
            if placements and len(placements[0].get("position", [])) >= 3:
                floor_final_pz = placements[0]["position"][2]
                base_key = key.split("_scaled")[0]
                old_floor_obj = orig_objs.get(base_key)
                if old_floor_obj and "placements" in old_floor_obj:
                    old_floor_pz = float(old_floor_obj["placements"][0]["position"][2])
                    anchor_with_floor = True
            break

    if new_floor_width is None or new_floor_length is None:
        new_floor_width = 10.0
        new_floor_length = 10.0

    # 3) Load asset_group_list => filter cloneable groups
    with open(asset_group_list_path, 'r') as f:
        asset_groups = json.load(f)

    cloneable_groups = [group for group in asset_groups if group.get("Cloneable", False) is True]

    if not cloneable_groups:
        print("No cloneable groups found. No cloning performed.")
        # Save the new scene as is
        with open(new_scene_path, 'w') as f:
            json.dump(new_scene_data, f, indent=4)
        return

    # ---------------------------------------------------------------------
    #                               HELPERS
    # ---------------------------------------------------------------------

    """
    HELPER

    Retrieve object data from the original scene.
    """
    def get_obj_data(obj_key):
        obj = orig_objs.get(obj_key)
        if not obj:
            return None
        dimensions = obj.get("dimensions", [0, 0, 0])
        px, py, pz = 0.0, 0.0, 0.0
        placements = obj.get("placements", [])
        if placements and len(placements[0].get("position", [])) >= 2:
            px = float(placements[0]["position"][0])
            py = float(placements[0]["position"][1])
            if len(placements[0]["position"]) >= 3:
                pz = float(placements[0]["position"][2])
        rot = placements[0].get("rotation", [0, 0, 0]) if placements else [0, 0, 0]
        local_scale = placements[0].get("scale", 1.0) if placements else 1.0
        return {
            "objdict": obj,
            "w": float(dimensions[0]),
            "l": float(dimensions[1]) if len(dimensions) >= 2 else 0.0,
            "h": float(dimensions[2]) if len(dimensions) >= 3 else 0.0,
            "px": px,
            "py": py,
            "pz": pz,
            "rot": rot,
            "local_scale": local_scale
        }

    """
    HELPER

    Compute the bounding box of a group based on its assets.
    """
    def compute_group_bounds(asset_list):
        
        minx, miny = math.inf, math.inf
        maxx, maxy = -math.inf, -math.inf
        for asset_key in asset_list:
            data = get_obj_data(asset_key)
            if not data:
                continue
            x1 = data["px"]
            y1 = data["py"]
            x2 = x1 + data["w"]
            y2 = y1 + data["l"]
            minx = min(minx, x1)
            miny = min(miny, y1)
            maxx = max(maxx, x2)
            maxy = max(maxy, y2)
        if minx == math.inf or miny == math.inf:
            return (0.0, 0.0, 0.0, 0.0)
        return (minx, miny, maxx, maxy)

    """
    HELPER

    Compute the centroid of a group's bounding box.
    """
    def compute_group_centroid(bounds)
        minx, miny, maxx, maxy = bounds
        centroid_x = (minx + maxx) / 2.0
        centroid_y = (miny + maxy) / 2.0
        return (centroid_x, centroid_y)

    """
    HELPER

    Clone the entire group based on how many times we want to tile it.
    Keep the relative spacing of items within the group intact.
    """
    def clone_group(grp, group_bounds, scale_factor_x, scale_factor_y):

        minx, miny, maxx, maxy = group_bounds
        group_width = maxx - minx
        group_length = maxy - miny

        # Compute original centroid
        centroid_x, centroid_y = compute_group_centroid(group_bounds)

        group_scale = 1.0

        # Determine how many clones to tile in each axis
        clones_x = max(1, int(math.floor(scale_factor_x)))
        clones_y = max(1, int(math.floor(scale_factor_y)))

        # The bounding box of the scaled group
        scaled_group_width  = group_width  * group_scale
        scaled_group_length = group_length * group_scale

        gap_x = 1.0
        gap_y = 1.0
        spacing_x = scaled_group_width + gap_x
        spacing_y = scaled_group_length + gap_y

        # For each tile, offset by (ix * spacing_x, iy * spacing_y)
        for ix in range(clones_x):
            for iy in range(clones_y):
                offset_x = ix * spacing_x
                offset_y = iy * spacing_y

                # Clone each asset in the group
                for asset_key in grp.get("assets", []):
                    clone_group_asset(
                        original_key=asset_key,
                        group_centroid=(centroid_x, centroid_y),
                        group_scale=group_scale,
                        offset_x=offset_x,
                        offset_y=offset_y,
                        clone_indices=(ix, iy)
                    )
    """
    HELPER

    Clone a single asset, preserving its relative offset from the group's centroid.
    """
    def clone_group_asset(original_key, group_centroid, group_scale, offset_x, offset_y, clone_indices):
        
        ix, iy = clone_indices
        data = get_obj_data(original_key)
        if not data:
            return

        # Compute each asset’s local offset from group centroid
        rel_x = data["px"] - group_centroid[0]
        rel_y = data["py"] - group_centroid[1]

        # Apply uniform scaling (if desired) to keep the group shape consistent
        final_x = group_centroid[0] + rel_x * group_scale + offset_x
        final_y = group_centroid[1] + rel_y * group_scale + offset_y

        # If we want to keep Z anchored to the floor, scale Z by group_scale as well
        if anchor_with_floor:
            final_pz = floor_final_pz + (data["pz"] - old_floor_pz) * group_scale
        else:
            final_pz = data["pz"]

        # Construct a unique key for the cloned asset
        new_key_base = f"{original_key}_clone_{ix}_{iy}"
        new_key = new_key_base
        counter = 1
        while new_key in new_objs:
            new_key = f"{new_key_base}_{counter}"
            counter += 1

        # Deep copy the original object
        new_obj = copy.deepcopy(data["objdict"])

        # Update positions
        new_obj["placements"][0]["position"] = [final_x, final_y, final_pz]
        # Apply uniform group scale to the local scale as well
        new_obj["placements"][0]["scale"] = data["local_scale"] * group_scale

        # Update identifier
        new_obj["identifier"] = new_key
        new_objs[new_key] = new_obj

    # ---------------------------------------------------------------------
    #                               END HELPERS
    # ---------------------------------------------------------------------


    # 5) Iterate over each cloneable group and clone
    for group in cloneable_groups:
        group_id = group.get("id", "UnknownID")
        group_name = group.get("group_name", "UnnamedGroup")
        assets = group.get("assets", [])

        if not assets:
            continue

        # Compute group bounds and centroid
        group_bounds = compute_group_bounds(assets)
        group_width = group_bounds[2] - group_bounds[0]
        group_length = group_bounds[3] - group_bounds[1]

        if group_width < 1e-6 or group_length < 1e-6:
            continue

        # Clone the group
        clone_group(
            grp=group,
            group_bounds=group_bounds,
            scale_factor_x=scale_factor_x,
            scale_factor_y=scale_factor_y
        )

    # 6) Save the updated new_scene
    with open(new_scene_path, 'w') as f:
        json.dump(new_scene_data, f, indent=4)

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--original_scene", required=True)
    parser.add_argument("--asset_group_list", required=True)
    parser.add_argument("--new_scene", required=True)
    parser.add_argument("--scale_factor_x", type=float, required=True)
    parser.add_argument("--scale_factor_y", type=float, required=True)
    args = parser.parse_args()

    place_cloneable_assets(
        original_scene_path=args.original_scene,
        asset_group_list_path=args.asset_group_list,
        new_scene_path=args.new_scene,
        scale_factor_x=args.scale_factor_x,
        scale_factor_y=args.scale_factor_y
    )

if __name__ == "__main__":
    main()
