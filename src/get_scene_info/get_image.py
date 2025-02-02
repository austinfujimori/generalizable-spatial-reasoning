"""
2) Render images with Blender
-----------------------------

Renders images for each glb.
We call this in main.py to get images for each asset and the entire scene.

INPUTS
 - scene_json: path to the scene.json
 - output_dir: directory where rendered images will be saved.
 - blend_file: Path to a .blend file to append additional objects, or the original blend scene to take images of the entire scene

OUTPUTS
 - asset_images/: 4 images for each asset from multiple angles.
 - scene_image/: 9 images for the entire scene render


APPROACH
1. Load Objects
    - Import corresponding `.glb` files into Blender from the assets in scene.json

2. Setup Lighting
    - Three-point lighting system

3. Setup Camera
    - For each object:
        - Get the optimal distance for the camera based on object size
        - Positions the camera at four different angled perspectives from the top
            - the cardinal directions were a little weird, especially with flatter objects like doors, windows, and walls
            - definitely don't need 4 camera angles, didn't really optimize on this part
    - For the full scene:
        - Computes the bbox of all objects to determine scene center
        - Positions the camera at angled, top-down, and cardinal direction views
            - we can distinguish the walls better with the entire scene view + cardinal directions

4.Rendering
    - Saves images into the folders
        - `asset_images/` for individual objects
        - `scene_image/` for full-scene renders

5. Post-Processing
    - Some assets don't have meshes we skip them (and report it via command line)
    - Adjusts zoom level dynamically to fit assets correctly, we gradually zoom out each camera perspective because the camera distance calculator is not fool-proof

"""

import bpy
import sys
import os
import json
import argparse
import re
import mathutils
import math

# ---------------------------------------------------------------------
#                               HELPERS
# ---------------------------------------------------------------------

"""
HELPER

cleans filename
"""
def sanitize_filename(filename):
    return re.sub(r'[<>:"/\\|?*]', '_', filename)

"""
HELPER

Clears blender scene
"""
def clear_scene():
    bpy.ops.object.select_all(action='SELECT')
    bpy.ops.object.delete(use_global=False)
    for bpy_data_iter in (bpy.data.meshes, bpy.data.cameras, bpy.data.lights, bpy.data.images):
        for id_data in bpy_data_iter:
            bpy_data_iter.remove(id_data, do_unlink=True)

"""
HELPER

Adds the glb to the scene
"""
def import_glb(glb_path):
    bpy.ops.import_scene.gltf(filepath=glb_path)
    return bpy.context.selected_objects

"""
HELPER

Adds the objects from .blend file into scene
"""
def append_from_blend(blend_file):
    appended_objects = []
    with bpy.data.libraries.load(blend_file, link=False) as (data_from, data_to):
        data_to.objects = data_from.objects

    for obj in data_to.objects:
        if obj is not None:
            bpy.context.scene.collection.objects.link(obj)
            appended_objects.append(obj)
    return appended_objects

"""
HELPER

Adds camera to scene and points it at target

 - location: (x,y,z) for camera location
 - look_at: (x,y,z) for target point
 - fov_deg: camera FOV
"""
def setup_camera(location, look_at, fov_deg=50):
    bpy.ops.object.camera_add(location=location)
    camera = bpy.context.object
    camera.data.angle = math.radians(fov_deg)
    direction = look_at - location
    rot_quat = direction.to_track_quat('-Z', 'Y')
    camera.rotation_euler = rot_quat.to_euler()
    bpy.context.scene.camera = camera
    return camera

"""
HELPER

Set up lighting with key, fill, and back lights

 - Key light: this is like the main source of lighting
 - Fill light: this is to deal with extreme shadows, we don't want difficult images for the VLM, we ultimately just want to show everything
 - Back light: placed behind object, we use a point light

Used GPT for this, not sure what the consensus is for these terms or this method to light a scene but it was sufficient to make the objects visible. May not need to be this complicated though.
"""
def setup_lighting():
    # Remove existing lights
    for obj in bpy.data.objects:
        if obj.type == 'LIGHT':
            bpy.data.objects.remove(obj, do_unlink=True)

    # Key light (Sun)
    bpy.ops.object.light_add(type='SUN', location=(5, -5, 10))
    sun = bpy.context.object
    sun.data.energy = 3.0
    sun.rotation_euler = (math.radians(45), 0, math.radians(45))

    # Fill light (Area)
    bpy.ops.object.light_add(type='AREA', location=(-3, 3, 5))
    fill = bpy.context.object
    fill.data.energy = 500
    fill.data.size = 5
    fill.rotation_euler = (math.radians(45), 0, math.radians(-30))

    # Back light (Point)
    bpy.ops.object.light_add(type='POINT', location=(0, -5, 5))
    back = bpy.context.object
    back.data.energy = 300

"""
HELPER

Renders current scene adn saves image
"""
def render_image(output_path):
    scene = bpy.context.scene
    scene.render.engine = 'BLENDER_EEVEE'
    scene.render.image_settings.file_format = 'PNG'
    scene.render.filepath = output_path
    bpy.ops.render.render(write_still=True)

"""
HELPER

Parser
"""
def parse_blender_args():
    argv = sys.argv
    if "--" not in argv:
        argv = []
    else:
        argv = argv[argv.index("--") + 1:]

    parser = argparse.ArgumentParser()
    parser.add_argument("--scene_json", required=True)
    parser.add_argument("--output_dir", required=True)
    parser.add_argument("--blend_file", required=False)
    return parser.parse_args(argv)

"""
HELPER

Gets bounding box of object (input)
"""
def get_object_bounds(obj):
    bbox_corners = [obj.matrix_world @ mathutils.Vector(corner) for corner in obj.bound_box]
    min_corner = mathutils.Vector((
        min(v.x for v in bbox_corners),
        min(v.y for v in bbox_corners),
        min(v.z for v in bbox_corners)
    ))
    max_corner = mathutils.Vector((
        max(v.x for v in bbox_corners),
        max(v.y for v in bbox_corners),
        max(v.z for v in bbox_corners)
    ))
    return min_corner, max_corner

"""
HELPER

Find the camera distance to use for an object
"""
def calculate_camera_distance(obj, fov_deg=50, zoom_factor=1.5):
    min_corner, max_corner = get_object_bounds(obj)
    size = max_corner - min_corner
    max_dim = max(size.x, size.y, size.z)
    fov_rad = math.radians(fov_deg)
    distance = (max_dim / 2) / math.tan(fov_rad / 2)
    return distance * zoom_factor

"""
HELPER

Center asset in scene
"""
def center_objects(objects):
    """Used for single-asset product renders—moves each object to the origin individually."""
    bpy.ops.object.select_all(action='DESELECT')
    for obj in objects:
        obj.select_set(True)
    if objects:
        bpy.context.view_layer.objects.active = objects[0]
        bpy.ops.object.origin_set(type='ORIGIN_CENTER_OF_MASS', center='BOUNDS')
        for obj in objects:
            obj.location = mathutils.Vector((0, 0, 0))


# ---------------------------------------------------------------------
#                               MAIN
# ---------------------------------------------------------------------

def main():
    args = parse_blender_args()

    scene_json_path = args.scene_json
    output_dir = args.output_dir
    blend_file_path = args.blend_file

    with open(scene_json_path, 'r') as f:
        scene_data = json.load(f)

    objects_dict = scene_data.get("objects", {})

    # Individual Asset Renders
    for obj_key, obj_info in objects_dict.items():
        sanitized_key = sanitize_filename(obj_key)
        object_dir = os.path.join(output_dir, "asset_images", sanitized_key)
        os.makedirs(object_dir, exist_ok=True)

        object_id = obj_key.split('-', 1)[1]

        glb_filename = f"neo_product_{object_id}.glb"
        glb_path = os.path.join(output_dir, "glbs", glb_filename)

        clear_scene()
        imported_objects = import_glb(glb_path)

        mesh_objects = [obj for obj in imported_objects if obj.type == 'MESH']

        # sometimes there's nothing in there
        if not mesh_objects:
            print(f"No mesh in {glb_path}, skipped")
            continue

        center_objects(mesh_objects)
        setup_lighting()

        obj_center = mathutils.Vector((0, 0, 0))
        main_obj = mesh_objects[0]
        distance = calculate_camera_distance(main_obj, fov_deg=50, zoom_factor=2.0)

        # Increasingly zoom out because sometimes we don't get the whole asset, vice versa
        product_perspectives = {
            "angled_view_1": {"direction": (1, -1, 1), "zoom_increment": 1.0},
            "angled_view_2": {"direction": (-1, -1, 1), "zoom_increment": 1.2},
            "angled_view_3": {"direction": (-1,  1, 1), "zoom_increment": 1.4},
            "angled_view_4": {"direction": ( 1,  1, 1), "zoom_increment": 1.6},
        }

        for view_name, params in product_perspectives.items():
            direction = mathutils.Vector(params["direction"]).normalized()
            cam_dist = distance * params["zoom_increment"]
            cam_location = obj_center + direction * cam_dist

            camera = setup_camera(cam_location, obj_center, fov_deg=50)
            out_path = os.path.join(object_dir, f"{view_name}.png")
            render_image(out_path)

            bpy.data.objects.remove(camera, do_unlink=True)

    # Handle whole scene render
    print("\nEntire Scene rendering")
    scene_img_dir = os.path.join(output_dir, "scene_image")
    os.makedirs(scene_img_dir, exist_ok=True)

    clear_scene()
    all_mesh_objects = []


    if blend_file_path and os.path.isfile(blend_file_path):
        appended_objs = append_from_blend(blend_file_path)
        all_mesh_objects = [o for o in appended_objs if o.type == 'MESH']
        # We need to make sure to NOT center them to preserve original arrangement from .blend or else the scene gets messed up

    if not all_mesh_objects:
        print("Entire scene has no mesges")
        return

    setup_lighting()

    # Get bbox for camera distance
    def collective_bounds(objs):
        min_c, max_c = get_object_bounds(objs[0])
        for o in objs[1:]:
            mi, ma = get_object_bounds(o)
            min_c.x = min(min_c.x, mi.x)
            min_c.y = min(min_c.y, mi.y)
            min_c.z = min(min_c.z, mi.z)
            max_c.x = max(max_c.x, ma.x)
            max_c.y = max(max_c.y, ma.y)
            max_c.z = max(max_c.z, ma.z)
        return min_c, max_c

    min_corner, max_corner = collective_bounds(all_mesh_objects)
    scene_center = (min_corner + max_corner) / 2
    scene_size = max(
        max_corner.x - min_corner.x,
        max_corner.y - min_corner.y,
        max_corner.z - min_corner.z
    )
    # For angled shots we use a narrower FOV
    base_distance = (scene_size / 2) / math.tan(math.radians(30 / 2))
    base_distance *= 1.2 

    # Angled from the top perspectives like we did with the indv. assets
    angled_perspectives = {
        "scene_view_1": {"direction": (1, -1, 1), "zoom_increment": 0.8},
        "scene_view_2": {"direction": (-1, -1, 1), "zoom_increment": 0.9},
        "scene_view_3": {"direction": (-1, 1, 1),  "zoom_increment": 1.0},
        "scene_view_4": {"direction": (1, 1, 1),   "zoom_increment": 1.1},
    }

    for view_name, params in angled_perspectives.items():
        direction = mathutils.Vector(params["direction"]).normalized()
        cam_dist = base_distance * params["zoom_increment"]
        cam_location = scene_center + direction * cam_dist

        camera = setup_camera(cam_location, scene_center, fov_deg=30)
        out_path = os.path.join(scene_img_dir, f"{view_name}.png")
        render_image(out_path)

        bpy.data.objects.remove(camera, do_unlink=True)

    # Now we also have 4 images of the cardinal directions
    extra_perspectives = {
        "birdseye_top": {
            "direction": (0, 0, 1),
            "zoom_increment": 1.0
        },
        "north_view": {
            "direction": (0, 1, 0),
            "zoom_increment": 1.0
        },
        "south_view": {
            "direction": (0, -1, 0),
            "zoom_increment": 1.0
        },
        "east_view": {
            "direction": (1, 0, 0),
            "zoom_increment": 1.0
        },
        "west_view": {
            "direction": (-1, 0, 0),
            "zoom_increment": 1.0
        }
    }

    for view_name, params in extra_perspectives.items():
        print(f"Rendering {view_name} of entire scene")
        direction = mathutils.Vector(params["direction"]).normalized()
        cam_dist = base_distance * params["zoom_increment"]
        cam_location = scene_center + direction * cam_dist

        camera = setup_camera(cam_location, scene_center, fov_deg=30)
        out_path = os.path.join(scene_img_dir, f"{view_name}.png")
        render_image(out_path)

        bpy.data.objects.remove(camera, do_unlink=True)

    print("\nDone with images", scene_img_dir)

if __name__ == "__main__":
    main()
