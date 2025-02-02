import json
import os
import boto3
import numpy as np
import bpy
import argparse
from aws_utils import upload_file_to_s3, check_if_s3_object_exists
from mathutils import Vector


def merge_children_to_parent(parent_object):
    if not parent_object:
        print("No parent object provided.")
        return False

    if parent_object.type != 'MESH':
        print(f"The parent object {parent_object.name} is not a mesh, creating a dummy mesh")
        # create a dummy mesh and put the parent object in it
        dummy_mesh = bpy.data.meshes.new(name=f"mesh-{parent_object.name}")
        dummy_object = bpy.data.objects.new(f"Dummy-{parent_object.name}", dummy_mesh)
        bpy.context.collection.objects.link(dummy_object)
        parent_object.parent = dummy_object
        parent_object = dummy_object

    # Create a list to store the meshes of all children
    meshes_to_merge = []

    def collect_children_recursive(obj):
        for child in obj.children:
            if child.type == 'MESH':
                meshes_to_merge.append(child)
            # Recursively collect meshes from nested children
            collect_children_recursive(child)
    
    # Collect all child meshes recursively
    collect_children_recursive(parent_object)

    if not meshes_to_merge:
        print("No child meshes found to merge.")
        return True

    # Select all meshes and the parent
    bpy.ops.object.select_all(action='DESELECT')  # Deselect all objects
    parent_object.select_set(True)  # Select parent object
    for child in meshes_to_merge:
        child.select_set(True)  # Select each child mesh
    
    # Make the parent object active
    bpy.context.view_layer.objects.active = parent_object

    # Join the meshes into the parent
    bpy.ops.object.join()
    return True
    
    # Remove all original child objects safely
    #for child in meshes_to_merge:
    #    if child != parent_object:
    #        # Ensure the object still exists before removing
    #        if child.name in bpy.data.objects:
    #            bpy.data.objects.remove(bpy.data.objects[child.name], do_unlink=True)

def select_object_and_children(obj):
    """
    Recursively select an object and all its children.
    """
    obj.select_set(True)
    for child in obj.children:
        select_object_and_children(child)

def get_selected_objects_center():
    # get the object's geometric center in the world coordinates
    # Get the world space bounds of the selected objects
    bbox_min = np.array([float('inf')] * 3)
    bbox_max = np.array([float('-inf')] * 3)
    
    # Include the main object and all its children
    for selected_obj in [obj] + list(obj.children):
        # Get the object's bounding box corners in world space
        bbox_corners = [selected_obj.matrix_world @ Vector(corner) for corner in selected_obj.bound_box]
        
        # Update min/max bounds
        for corner in bbox_corners:
            bbox_min = np.minimum(bbox_min, np.array(corner))
            bbox_max = np.maximum(bbox_max, np.array(corner))
    
    # Calculate center of bounding box
    center = (bbox_min + bbox_max) / 2
    return center

def sanitize_name(name):
    """
    Remove or replace problematic characters from the object name.
    """
    try:
        name.encode("utf-8")
    except UnicodeEncodeError:
        # Replace problematic characters with a placeholder or remove them
        name = ''.join(c if c.isalnum() or c in '-_.' else '_' for c in name)
    return name

def find_object_by_name(name):
    for obj in bpy.context.scene.objects:
        if obj.name == name:
            return obj
    return None

def hide_object_and_children(obj):
    obj.hide_set(True)
    for child in obj.children:
        hide_object_and_children(child)

# ignore objects if any descendant has the name of "NeoProduct."
def check_children_for_neoproduct(obj):
    for child in obj.children:
        if child.name.startswith("NeoProduct."):
            return True
        if check_children_for_neoproduct(child):
            return True
    return False


# Get the actual dimensions of the object in world space.
def get_object_dimensions(obj):
    bbox_corners = [obj.matrix_world @ Vector(corner) for corner in obj.bound_box]
    bbox_min = np.array([min(corner[i] for corner in bbox_corners) for i in range(3)])
    bbox_max = np.array([max(corner[i] for corner in bbox_corners) for i in range(3)])
    dimensions = bbox_max - bbox_min
    return dimensions.tolist()
    

if __name__ == "__main__":
    # Add argument parsing
    parser = argparse.ArgumentParser(description='Process FOYR blend file')
    parser.add_argument('--input_blend_file', type=str, required=True,
                      help='Input blend file path')
    parser.add_argument('--output_dir', type=str,
                      help='Output directory (defaults to input file\'s parent directory)')
    parser.add_argument('--sanitize_name', action='store_true',
                      help='Enable name sanitization for objects')

    args = parser.parse_args()

    # Set output directory
    if args.output_dir:
        output_dir = args.output_dir
    else:
        output_dir = os.path.dirname(os.path.abspath(args.input_blend_file))

    # Create output directories
    scene_id = os.path.basename(args.input_blend_file).split('.')[0]
    os.makedirs(output_dir, exist_ok=True)
    os.makedirs(os.path.join(output_dir, 'glbs'), exist_ok=True)

    s3_client = boto3.client('s3')
    scene_json = {"objects": {}}

    # Load the blend file
    bpy.ops.wm.open_mainfile(filepath=args.input_blend_file)

    # find the objects that have a prefix of "NeoProduct."
    ceiling_group = find_object_by_name("ceilinggroup")
    # hide everything under the ceiling group, recursively
    hide_object_and_children(ceiling_group) 

    # sanitize the names of all objects if enabled
    if args.sanitize_name:
        for obj in bpy.context.scene.objects:
            try:
                obj.name = sanitize_name(obj.name)
            except Exception as e:
                print(f"Error sanitizing name: {e}")
                continue

    round_index = -1
    while round_index < 10:
        round_index += 1
        target_objects = []
        # ignore objects if any descendant has the name of "NeoProduct."
        for obj in bpy.context.scene.objects:
            if obj.name.startswith("NeoProduct."):
                skip = False
                parent = obj.parent
                while parent is not None:
                    if parent.name == "ceilinggroup":
                        skip = True
                        break
                    parent = parent.parent
                if skip:
                    continue
                if check_children_for_neoproduct(obj):
                    continue
                # Store the world location, rotation, and scale
                world_matrix = obj.matrix_world.copy()
                # Clear the parent while keeping the transform
                obj.parent = None
                # Restore the world transform
                obj.matrix_world = world_matrix

                # if merge_children_to_parent(obj):
                target_objects.append(obj.name)

        # now process the target objects and then remove them from the scene
        for wall_obj in bpy.data.objects["wallgroup"].children:
            # Deselect all objects first
            bpy.ops.object.select_all(action='DESELECT')
            # Set the active object
            bpy.context.view_layer.objects.active = wall_obj
            # join all the children into a single mesh
            if merge_children_to_parent(wall_obj):
                target_objects.append(wall_obj.name)

        for floor_obj in bpy.data.objects["floorgroup"].children:
            if floor_obj.name.startswith("Room"):
                # Deselect all objects first
                bpy.ops.object.select_all(action='DESELECT')
                # Set the active object
                bpy.context.view_layer.objects.active = floor_obj
                # join all the children into a single mesh
                if merge_children_to_parent(floor_obj):
                    target_objects.append(floor_obj.name)

        print(f"round {round_index}, {len(target_objects)} objects to process")
        for obj_name in target_objects:
            obj = bpy.data.objects[obj_name]
            # Deselect all objects first
            bpy.ops.object.select_all(action='DESELECT')
            # Set the active object
            bpy.context.view_layer.objects.active = obj
            # Make sure the object is selected
            obj.select_set(True)  
            # Enter object mode to ensure we can modify the object
            bpy.ops.object.mode_set(mode='OBJECT')
            result = bpy.ops.object.origin_set(type='ORIGIN_GEOMETRY', center='BOUNDS')
            # bpy.ops.object.origin_set(type="ORIGIN_CENTER_OF_MASS", center="BOUNDS")
            assert 'FINISHED' in result, f"Failed to set origin to geometry center for {obj.name}"
            
            # Get the world coordinates after centering
            center = obj.matrix_world.translation.copy()
            # Move the object to the scene's origin
            # obj.location = [0, 0, 0]
            # make sure to move the object to the origin in the world coordinates
            obj.matrix_world.translation = (0, 0, 0)
            # apply the transformation
            bpy.ops.object.transform_apply(location=True, rotation=True, scale=True)
            # Select the object and all nested children
            # Export just this object and its children

            select_object_and_children(obj)
            glb_path = os.path.join(output_dir, 'glbs', f'neo_product_{obj.name}.glb')
            bpy.ops.export_scene.gltf(
                filepath=glb_path,
                use_selection=True,
            )
            print(f"Exported {obj.name} to {glb_path}")

            bucket_name = "playcanvas-public"
            target_file_path = f"/spatio/{scene_id}-{obj.name}.glb"
            asset_url = f"https://{bucket_name}.s3.amazonaws.com/{target_file_path}"
            # if not check_if_s3_object_exists(s3_client, target_file_path, bucket_name=bucket_name):
            #    print(f"{target_file_path} exists in {bucket_name}")
            asset_url = upload_file_to_s3(s3_client, glb_path, target_file_path, bucket_name=bucket_name)

            if obj.name.startswith("Wall"):
                category = "walls"
            elif obj.name.startswith("Room"):
                category = "floors"
            else:
                category = "objects"
            category = "objects"

            dimensions = get_object_dimensions(obj)

            scene_json["objects"][f"{scene_id}-{obj.name}"] = {
                "category": category,
                "placements": [
                    {
                        "position": [center.x, center.y, center.z],
                        "rotation": [0, 0, 0],
                        "scale": 1
                    }
                ],
                "bbox_size": [
                    1,
                    1,
                    1
                ],
                "dimensions": dimensions,
                "identifier": f"{scene_id}-{obj.name}",
                "metadata": {
                    "asset_url": asset_url
                }
            }
            # save the scene_json to a file in the output directory
            bpy.ops.object.delete()
            bpy.context.view_layer.update()
            # remove the selected objects from the scene
            #print("deleting the object from the scene")
            #bpy.ops.object.mode_set(mode='OBJECT')
            #bpy.ops.object.delete()

    # bpy.context.view_layer.update()
    scene_json_path = os.path.join(output_dir, 'scene.json')
    with open(scene_json_path, "w") as f:
        json.dump(scene_json, f, indent=4)

    # save the debug blend file in the output directory
    debug_blend_path = os.path.join(output_dir, 'debug.blend')
    bpy.ops.wm.save_as_mainfile(filepath=debug_blend_path)