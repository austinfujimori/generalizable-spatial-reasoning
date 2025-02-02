"""
3) Assign labels to objects in scene.json
-----------------------------------------

Use OpenAI API to label each of the images.
Adds the labels to scene.json.

INPUTS
- input_dir: directory containing "asset_images" and "scene_image" folders, so output directory for main.py
- scene_json: scene.json path
- blend_name: name of the blend file because it is the prefix for the asset names in scene.json, we need it to be able to distinguish between walls and floors
- model_name: gtp-4o by default

OUTPUTS
- Updated scene.json:
    - "object_name" and "object_type" for identified assets
    - "wall_type" for walls (like "door", "solid_wall")
    - "floor_description" for floors (like "wood flooring")


APPROACH
1. Get Scene and Images
    - Get scene images from the "scene_image/" directory
    - Get individual asset images from "asset_images/" for the assets in scene.json

2. Determine Object Type
    - We use heuristics to classify objects as:
        - Walls (if "wall" appears in the name).
        - Floors (if "room" appears after stripping blend prefix).
        - Assets (everything else).

3. Prepare Image Data
    - Encode images as Base64
    - Splits large lists into smaller chunks to stay within OpenAI API limits
    - Constructs the messages with:
        - Scene images (context).
        - Asset images
        - The labeling prompt w/ some other heuristics, this part is a little sketchy sometimes, because of some version dependencies with other libraries we can't use the up to date API so we can't format the output in JSON format so we need to do some prompt engineering

4. Request Labels from OpenAI
    - Sends the image set and prompt to OpenAI's Chat Completions API
    - Receives a structured JSON response
        - prompt engineering, see step 3
    - Parses JSON for object name, type, or description

5. Update scene.json
    - Assigns labels to objects and we save the updated file
"""

import argparse
import os
import json
import re
import time
import logging
import base64

import openai


# BUGGY STEP
# - Attempt location for newer openai library (>=0.27.x)
# - then for openai library (~0.8.x to ~0.26.x)
# - then fallback
OpenAIError = None
try:
    from openai.exceptions import OpenAIError as NewOpenAIError
    OpenAIError = NewOpenAIError
except ImportError:
    pass

if OpenAIError is None:
    try:
        from openai.error import OpenAIError as OldOpenAIError
        OpenAIError = OldOpenAIError
    except ImportError:
        pass
if OpenAIError is None:
    class OpenAIError(Exception):
        pass

# Config
logging.basicConfig(
    filename='get_asset_labels.log',
    filemode='a',
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)

MAX_ITEMS_PER_MESSAGE = 9

# ---------------------------------------------------------------------
#                               HELPERS
# ---------------------------------------------------------------------

"""
HELPER

Definitely will make a global utils function, got really lazy
"""
def sanitize_filename(filename: str) -> str:
    return re.sub(r'[<>:"/\\|?*]', '_', filename)

"""
HELPER

Check if asset is a wall
We do the stripping stuff because if the blend is named "wall" then all assets would be classified as a wall
"""
def is_wall(obj_key: str) -> bool:
    if obj_key.startswith(blend_prefix + "-"):
        obj_key_stripped = obj_key[len(blend_prefix) + 1:]
    else:
        obj_key_stripped = obj_key
    return 'wall' in obj_key_stripped.lower()

"""
HELPER

Check if asset is a floor, will combine this and wall into a global func
"""
def is_floor(obj_key: str, blend_prefix: str) -> bool:
    if obj_key.startswith(blend_prefix + "-"):
        obj_key_stripped = obj_key[len(blend_prefix) + 1:]
    else:
        obj_key_stripped = obj_key
    return 'room' in obj_key_stripped.lower()

"""
HELPER

Load images for the entire scene
"""
def load_scene_images(scene_images_dir: str) -> list:
    scene_images_paths = []
    if os.path.isdir(scene_images_dir):
        for image_file in sorted(os.listdir(scene_images_dir)):
            lower = image_file.lower()
            if lower.endswith(('.png', '.jpg', '.jpeg')):
                image_path = os.path.join(scene_images_dir, image_file)
                if os.path.isfile(image_path):
                    scene_images_paths.append(image_path)
    return scene_images_paths

"""
HELPER

Yield consecutive sublists of size ≤ chunk_size from `lst`
"""
def chunk_list(lst, chunk_size):
    for i in range(0, len(lst), chunk_size):
        yield lst[i : i + chunk_size]

"""
HELPER

Base64 encode image file, the returns a dictionary for the chat completion for OpenAI API
"""
def encode_image_as_data_url(path: str, detail: str = "auto") -> dict:
    with open(path, "rb") as f:
        b64 = base64.b64encode(f.read()).decode("utf-8")
    return {
        "type": "image_url",
        "image_url": {
            "url": f"data:image/jpeg;base64,{b64}",
            "detail": detail
        }
    }

"""
HELPER

1) "developer" message with overall instructions
2) One or more "user" messages containing chunks of scene images
3) One or more "user" messages containing chunks of asset images
4) One final "user" message with the text prompt
"""
def build_chunked_image_messages(scene_paths: list, asset_paths: list, text_prompt: str) -> list:
    messages = [
        {
            "role": "developer",
            "content": [
                {
                    "type": "text",
                    "text": (
                        "You are an assistant that visually analyzes images of a room "
                        "and an asset, identifying objects, walls, or floors. "
                        "Please return strictly valid JSON. If labeling an asset, return "
                        "JSON with \"object_name\" and \"object_type\". If labeling a wall, "
                        "return \"wall_type\". If labeling a floor, return \"floor_description\". "
                        "No additional keys should appear. Example:\n"
                        "{\"object_name\":\"chair\",\"object_type\":\"object\"}\n"
                        "Do not include markdown in your output."
                    )
                }
            ]
        }
    ]

    # Scene images in chunks
    for chunk in chunk_list(scene_paths, MAX_ITEMS_PER_MESSAGE):
        content_chunk = []
        for spath in chunk:
            content_chunk.append(encode_image_as_data_url(spath, detail="low"))
        messages.append({
            "role": "user",
            "content": content_chunk
        })

    # Asset images in chunks
    for chunk in chunk_list(asset_paths, MAX_ITEMS_PER_MESSAGE):
        content_chunk = []
        for apath in chunk:
            content_chunk.append(encode_image_as_data_url(apath, detail="high"))
        messages.append({
            "role": "user",
            "content": content_chunk
        })

    # Final user message with text prompt
    messages.append({
        "role": "user",
        "content": [
            {
                "type": "text",
                "text": text_prompt
            }
        ]
    })

    return messages

"""
HELPER

Sends the given messages to chat.completions.create, returns the text from the assistant. If there's no text, returns "".
"""
def run_label_request(model_name: str, messages: list) -> str:
    response = openai.chat.completions.create(
        model=model_name,
        messages=messages,
        store=True
    )

    final_message = response.choices[0].message

    # different forms for diff versions of lib
    if isinstance(final_message, dict):
        text_content = final_message.get("content", "")
    else:
        text_content = getattr(final_message, "content", "")

    return text_content

# ---------------------------------------------------------------------
#                               MAIN
# ---------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--input_dir", required=True)
    parser.add_argument("--scene_json", required=True)
    parser.add_argument("--blend_name", required=True)
    parser.add_argument("--model_name", default="gpt-4o")
    args = parser.parse_args()

    input_dir = args.input_dir
    scene_json_path = args.scene_json
    blend_name = args.blend_name
    model_name = args.model_name

    asset_images_dir = os.path.join(input_dir, "asset_images")
    scene_images_dir = os.path.join(input_dir, "scene_image")

    openai_api_key = os.getenv("OPENAI_API_KEY")

    openai.api_key = openai_api_key

    # 1) Load scene images
    scene_paths = load_scene_images(scene_images_dir)

    # 2) Load scene.json
    with open(scene_json_path, "r") as f:
        scene_data = json.load(f)
    objects_dict = scene_data.get("objects", {})

    # 3) Process each object
    for obj_key, obj_details in objects_dict.items():
        logging.info(f"Processing object: {obj_key}")

        if is_wall(obj_key):
            obj_type = "wall"
            label_field = "wall_type"
        elif is_floor(obj_key, blend_name):
            obj_type = "floor"
            label_field = "floor_description"
        else:
            obj_type = "asset"
            label_field = "object_name"

        # 4) Gather asset images for this object
        obj_folder = sanitize_filename(obj_key)
        obj_path = os.path.join(asset_images_dir, obj_folder)
        asset_paths = []
        if os.path.isdir(obj_path):
            for image_file in sorted(os.listdir(obj_path)):
                lower = image_file.lower()
                if lower.endswith(('.png', '.jpg', '.jpeg')):
                    fullp = os.path.join(obj_path, image_file)
                    if os.path.isfile(fullp):
                        asset_paths.append(fullp)

        # If no images => "unknown"
        if not asset_paths:
            print(f"No images for object: {obj_key} => 'unknown'")
            final_label = "unknown"
            final_object_type = "object"
        else:
            # 5) Build the relevant prompt
            if obj_type == "asset":
                prompt_text = (
                    "You have multiple room (scene) images plus the asset images. "
                    "Identify the what the asset is in the asset images. Also choose an "
                    "\"object_type\" from [object, wall_part, light_fixture]. "
                    "A wall_part should be like things that could qualify as a wall or part of a wall, like a finish of a wall, a door, a window, a large panel, etc."
                    "An object is anything else, like furniture or things in a room. "
                    "A light_fixture is a light that hangs from the cieling"
                    "Use the scene images as clues to help you determine the typ of the asset."
                    "if you don't know the object_type, default to object"
                    "Return strictly valid JSON, for example:\n"
                    "{\"object_name\":\"bed\",\"object_type\":\"object\"}"
                )
            elif obj_type == "wall":
                prompt_text = (
                    "You have room images and a wall image. Choose a \"wall_tye\" from [hallway, door, window, solid_wall, open_wall]"
                    "Where solid_wall is a wall that has no holes"
                    "And open_wall is a wall that has holes but we can’t further classify it"
                    "Identify the wall type and respond "
                    "with valid JSON. Example:\n"
                    "{\"wall_type\":\"door\"}"
                )
            elif obj_type == "floor":
                prompt_text = (
                    "You have room images plus a floor image. Describe the floor and respond "
                    "with valid JSON. Example:\n"
                    "{\"floor_description\":\"gray tile\"}"
                )
            else:
                prompt_text = "Analyze these images and return JSON describing the object."

            messages = build_chunked_image_messages(scene_paths, asset_paths, prompt_text)
            response_text = run_label_request(model_name, messages)

            if not response_text:
                print(f"No assistant message found for {obj_key} => 'unknown'.")
                final_label = "unknown"
                final_object_type = "object"
            else:
                # 6) Attempt JSON parse
                try:
                    parsed = json.loads(response_text)
                    if obj_type == "asset":
                        final_label = parsed.get("object_name", "unknown")
                        final_object_type = parsed.get("object_type", "object")
                    elif obj_type == "wall":
                        final_label = parsed.get("wall_type", "unknown")
                        final_object_type = None
                    elif obj_type == "floor":
                        desc = parsed.get("floor_description", "unknown")
                        final_label = desc
                        final_object_type = None
                    else:
                        final_label = "unknown"
                        final_object_type = "object"
                except json.JSONDecodeError:
                    print(f"  Could not parse JSON for {obj_key} => 'unknown'.")
                    final_label = "unknown"
                    final_object_type = "object"

        # 7) Update scene.json for this object
        scene_data["objects"][obj_key][label_field] = final_label
        if obj_type == "asset":
            scene_data["objects"][obj_key]["object_type"] = final_object_type

    # 8) Save updated scene.json
    with open(scene_json_path, "w") as f:
        json.dump(scene_data, f, indent=4)
    print("\nFinished labeling")

if __name__ == "__main__":
    main()
