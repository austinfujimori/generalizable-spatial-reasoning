import argparse
import subprocess
import os
import json


def main():
    # Parse arguments
    parser = argparse.ArgumentParser(
        description="Run process_foyr.py, render images with Blender, process images with Groq Vision API, and extract_walls.py in sequence."
    )
    parser.add_argument(
        "--input_blend", 
        required=True, 
        help="Path to the input .blend file."
    )
    parser.add_argument(
        "--output_dir", 
        required=True, 
        help="Path to the directory where output files will be written."
    )
    args = parser.parse_args()
    blend_filename = os.path.basename(args.input_blend)
    blend_name, _ = os.path.splitext(blend_filename)

    # 1) Extract scene.json from blend file
    subprocess.run([
        "python",
        "src/blend_to_scene/process_foyr.py",
        "--input", args.input_blend,
        "--output_dir", args.output_dir
    ], check=True)

    # 2) Render images with Blender
    subprocess.run([
        "python",
        "src/get_scene_info/run_blender.py",
        "--blender_executable", "/Applications/Blender.app/Contents/MacOS/blender",
        "--blender_script", "src/get_scene_info/get_image.py",
        "--args",
        "--scene_json", os.path.join(args.output_dir, "scene.json"),
        "--output_dir", args.output_dir,
        "--blend_file", args.input_blend
    ], check=True)

    # 3) Assign labels to objects in scene.json
    subprocess.run([
        "python",
        "src/get_scene_info/get_asset_labels.py",
        "--input_dir", args.output_dir,
        "--blend_name", blend_name,
        "--scene_json", os.path.join(args.output_dir, "scene.json")
    ], check=True)

    # 4) Find current floor dimensions
    from get_scene_info.get_total_floor_dimensions import get_total_floor_dimensions
    scene_json_path = os.path.join(args.output_dir, "scene.json")
    floor_dims = get_total_floor_dimensions(scene_json_path, blend_name)
    total_X = floor_dims.get("total_X", 0.0)
    total_Y = floor_dims.get("total_Y", 0.0)
    print("\n\n\n\n")
    print(f"Total Floor Dimensions:")
    print(f"  X (Width): {total_X}")
    print(f"  Y (Length): {total_Y}\n")

    # 5) Prompt user for new dimensions and style
    new_X = float(input("Enter new Width (X) value: "))
    new_Y = float(input("Enter new Length (Y) value: "))
    prompt = input("Prompt: ")
    print("\n\n\n\n")


    # 6) Add the scaled floor to new_scene.json
    new_scene_json_path = os.path.join(args.output_dir, "new_scene.json")
    subprocess.run([
        "python",
        "src/create_scene/add_resized_floor.py",
        "--scene_json", scene_json_path,
        "--blend_name", blend_name,
        "--new_X", str(new_X),
        "--new_Y", str(new_Y),
        "--new_scene_json", new_scene_json_path
    ], check=True)

    # 7) Extract wall_list.json from scene.json
    subprocess.run([
        "python",
        "src/extract_assets/extract_walls.py",
        "--input_scene", os.path.join(args.output_dir, "scene.json"),
        "--output_scene", os.path.join(args.output_dir, "wall_list.json")
    ], check=True)

    # 8) Scale the walls and add them to new_scene.json
    subprocess.run([
        "python",
        "src/create_scene/add_resized_walls.py",
        "--original_scene", scene_json_path,
        "--wall_list", os.path.join(args.output_dir, "wall_list.json"),
        "--new_scene", new_scene_json_path,
        "--scale_factor", str(new_X / total_X),
    ], check=True)

    # 9) Group objects (not walls or floors) into asset_group_list.json
    subprocess.run([
        "python",
        "src/extract_assets/extract_groups.py",
        "--original_scene_json", os.path.join(args.output_dir, "scene.json"),
        "--new_scene_json", os.path.join(args.output_dir, "new_scene.json"),
        "--scene_images_dir", os.path.join(args.output_dir, "scene_image"),
        "--output_json", os.path.join(args.output_dir, "asset_group_list.json"),
        "--model_name", "gpt-4o",
        "--prompt", "We are making the living room bigger. Mark groups as cloneable if we might need multiples."
    ], check=True)

    # 10) Place individual objects
    subprocess.run([
    "python",
    "src/create_scene/place_individual_assets.py",
    "--original_scene", os.path.join(args.output_dir, "scene.json"),
    "--asset_group_list", os.path.join(args.output_dir, "asset_group_list.json"),
    "--new_scene", os.path.join(args.output_dir, "new_scene.json"),
    "--scale_factor", str(new_X / total_X)
    ], check=True)

    # 11) Place cloned objects
    subprocess.run([
        "python",
        "src/create_scene/place_cloneable_assets.py",
        "--original_scene", os.path.join(args.output_dir, "scene.json"),
        "--asset_group_list", os.path.join(args.output_dir, "asset_group_list.json"),
        "--new_scene", os.path.join(args.output_dir, "new_scene.json"),
        "--scale_factor_x", str(new_X / total_X),
        "--scale_factor_y", str(new_X / total_X),

    ], check=True)



if __name__ == "__main__":
    main()
