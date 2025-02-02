"""
6) Add the scaled floor to new_scene.json
-----------------------------------------

Sscale floor objects of scene.json into new_scene.json.

INPUTS
 - scene_json: path to scene.json
 - blend_name: name of the .blend file
 - new_X: new X dim
 - new_Y: new Y dim
 - new_scene_json: file where new floors will be saved

APPROACH
 1. Compute global pivot:
    - Iterate over all objects to determine the bbox.
    - Calculate the center (pivot_x, pivot_y) to be used as the scaling origin
 2. Get floor objects
    - Contains "room" in the key without the blend_name
    - Sum their widths and lengths to assist in computing the overall scale
 3. Compute the scale factor:
    -Get scale factor using new_X dimension (right now we only scale in 1 direction, so we use the X)
 4. Scale each floor object
    - Adjust each floor's dimensions (width, length, and height) using the scale factor, technically this doesn't matter right now because we only use the "dimensions" label in all these scripts but it will be useful in the future
    - Scale the placement positions relative to the global pivot
    - Adjust the vertical position (pz) by subtracting a thickness offset to ensure each floor retains its individual height characteristics
    - Generate the new key, adding "_scaled"
  5. Write them to the new JSON scene
"""

import argparse
import json
import os
import sys
import math
import copy

def add_resized_floor(scene_json_path, blend_name, new_X, new_Y, new_scene_json_path):

    with open(scene_json_path, 'r') as f:
        scene_data = json.load(f)

    objects_dict = scene_data.get("objects", {})

    # 1) global pivot from ALL objects
    gminx= math.inf
    gmaxx= -math.inf
    gminy= math.inf
    gmaxy= -math.inf

    for key, od in objects_dict.items():
        dims= od.get("dimensions",[0,0,0])
        if len(dims)<2:
            continue
        w, l= dims[0], dims[1]
        pls= od.get("placements",[])
        if not pls:
            continue
        px, py= pls[0]["position"][0], pls[0]["position"][1]

        x1= px
        x2= px + w
        y1= py
        y2= py + l
        if x1<gminx: gminx=x1
        if x2>gmaxx: gmaxx=x2
        if y1<gminy: gminy=y1
        if y2>gmaxy: gmaxy=y2

    pivot_x= 0.5*(gminx+gmaxx)
    pivot_y= 0.5*(gminy+gmaxy)

    # 2) find floors
    prefix = blend_name + "-"
    floor_objs = []
    sum_w=0.0
    sum_l=0.0

    for obj_key, od in objects_dict.items():
        # strip prefix
        if obj_key.startswith(prefix):
            stripped= obj_key[len(prefix):]
        else:
            stripped= obj_key

        if "room" in stripped.lower():
            dims= od.get("dimensions",[0,0,0])
            if len(dims)<2:
                continue
            w, l= dims[0], dims[1]
            h= dims[2] if len(dims)>=3 else 0.0
            pls= od.get("placements",[])
            if not pls:
                continue
            pos= pls[0]["position"]
            px, py, pz = pos if len(pos)>=3 else (pos[0], pos[1], 0.0)

            sum_w += w
            sum_l += l

            floor_objs.append({
                "key": obj_key,
                "details": od,
                "orig_w": w,
                "orig_l": l,
                "orig_h": h,
                "orig_px": px,
                "orig_py": py,
                "orig_pz": pz
            })

    # 3) scale factor from new_X vs sum_w
    scale_factor=1.0
    if sum_w>0:
        scale_factor= new_X / sum_w
    
    new_scene= {"objects": {}}
    new_objs= new_scene["objects"]

    for fo in floor_objs:
        k= fo["key"]
        od= fo["details"]
        w, l, h= fo["orig_w"], fo["orig_l"], fo["orig_h"]
        px, py, pz= fo["orig_px"], fo["orig_py"], fo["orig_pz"]

        sw= w*scale_factor
        sl= l*scale_factor
        sh= h*scale_factor

        # if you want thickness offset
        offset_z= sh - h

        dx= px- pivot_x
        dy= py- pivot_y
        new_px= pivot_x + dx* scale_factor
        new_py= pivot_y + dy* scale_factor

        # final pz= old pz - offset_z if you want the floor's top to remain the same
        # or if you want no vertical shift, do final_pz= pz
        temp_pz= pz - offset_z

        # no shared offset
        final_pz= temp_pz

        new_key= k+"_scaled"
        c=1
        while new_key in new_objs:
            new_key= f"{k}_scaled_{c}"
            c+=1

        new_obj= copy.deepcopy(od)
        if "dimensions" not in new_obj or len(new_obj["dimensions"])<2:
            new_obj["dimensions"]=[sw, sl, sh]
        else:
            new_obj["dimensions"][0]= sw
            new_obj["dimensions"][1]= sl
            if len(new_obj["dimensions"])>=3:
                new_obj["dimensions"][2]= sh
            else:
                new_obj["dimensions"].append(sh)

        if "placements" not in new_obj or not isinstance(new_obj["placements"], list):
            new_obj["placements"]=[{
                "position":[new_px,new_py,final_pz],
                "rotation":[0,0,0],
                "scale": scale_factor
            }]
        else:
            new_obj["placements"][0]["position"]=[new_px,new_py,final_pz]
            new_obj["placements"][0]["scale"]= scale_factor

        new_obj["identifier"]= new_key
        new_objs[new_key]= new_obj

    with open(new_scene_json_path,'w') as f:
        json.dump(new_scene, f, indent=4)

def main():
    parser= argparse.ArgumentParser()
    parser.add_argument("--scene_json", required=True)
    parser.add_argument("--blend_name", required=True)
    parser.add_argument("--new_X", type=float, required=True)
    parser.add_argument("--new_Y", type=float, required=True)
    parser.add_argument("--new_scene_json", required=True)
    args= parser.parse_args()

    add_resized_floor(
        scene_json_path= args.scene_json,
        blend_name= args.blend_name,
        new_X= args.new_X,
        new_Y= args.new_Y,
        new_scene_json_path= args.new_scene_json
    )

if __name__=="__main__":
    main()
