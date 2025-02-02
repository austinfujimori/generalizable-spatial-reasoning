"""
9) Group objects (not walls or floors) into asset_group_list.json
-----------------------------------------------------------------

We use gpt-4o to group leftover objects from a scene that are NOT present in the new_scene. The goal is to analyze room layouts via provided scene images and a JSON list of leftover objects (excluding walls and floors) and then determine logical clusters (e.g., dining area, lounge area, etc.), assign descriptive names, and mark each group as "Cloneable" or not for future room resizing operations. Not sure if this is generalizable yet, but right now serves as our main method to "fill in space" when we scale up a room.

INPUTS
 - original_scene_json: path to scene.json (original)
 - new_scene_json: path to new_scene.json
 - scene_images_dir: path to directory containing the scene images
 - output_json: directory for asset_group_list.json
 - model_name: default is 4o
 - prompt: the user prompt

OUTPUTS
 - asset_group_list.json: array of groups with:
      - id: group id
      - group_name: descriptive name for the group
      - assets: the keys for the assets that belong to the group
      - Cloneable: boolean indicating if the group is cloneable for room expansion/shrinking

APPROACH
 1. Load the original scene.json and new_scene.json
    - Identify leftover objects from the original scene that are not already placed in new_scene (or marked as scaled)
    - Exclude objects representing walls or floors
 2. Load a set of scene images from the specified directory
 3. Build a series of messages for a Chat Completions request:
    a. A developer message with detailed instructions (including the expected strict JSON output format)
    b. User messages containing chunks (up to 9 per message) of scene images, each encoded as a data URL
    c. A final user message that includes the JSON of leftover objects and the user-provided prompt
 4. Call the GPT-4(vision) model using the assembled messages
 5. Parse and validate the JSON response
    - Ensure that the response is a list of dictionaries with the required keys ("id", "group_name", "assets", "Cloneable")
 6. Write the validated groups to the output JSON file (asset_group_list.json)
"""

import argparse
import json
import os
import sys
import base64
import logging
import re

import openai

# 1) TRY IMPORTS FOR OpenAIError
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
    filename='extract_groups.log',
    filemode='a',
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)

# Maximum number of images per user message
MAX_IMAGES_PER_MESSAGE = 9

# ---------------------------------------------------------------------
#                               HELPERS
# ---------------------------------------------------------------------

"""
HELPER

Reads file at `path`, Base64-encodes it, and returns a dict
suitable for the Chat Completions message content with
type="image_url"
"""
def encode_image_as_data_url(path: str, detail: str = "auto") -> dict:
    with open(path, "rb") as f:
        b64 = base64.b64encode(f.read()).decode("utf-8")
    # Determine MIME type based on file extension
    ext = os.path.splitext(path)[1].lower()
    if ext == ".png":
        mime = "image/png"
    else:
        mime = "image/jpeg"
    return {
        "type": "image_url",
        "image_url": {
            "url": f"data:{mime};base64,{b64}",
            "detail": detail
        }
    }

"""
HELPER

Yield consecutive sublists of size ≤ chunk_size from `lst`
"""
def chunk_list(lst, chunk_size):
    for i in range(0, len(lst), chunk_size):
        yield lst[i : i + chunk_size]

"""
HELPER

Return a sorted list of scene image file paths in `scene_images_dir`.
"""
def load_scene_images(scene_images_dir: str) -> list:
    scene_images_paths = []
    if os.path.isdir(scene_images_dir):
        for image_file in sorted(os.listdir(scene_images_dir)):
            lower = image_file.lower()
            if lower.endswith(('.png', '.jpg', '.jpeg')):
                full_path = os.path.join(scene_images_dir, image_file)
                if os.path.isfile(full_path):
                    scene_images_paths.append(full_path)
    else:
        logging.warning(f"Scene images directory not found: {scene_images_dir}")
    return scene_images_paths

"""
HELPER

Build the messages for a single Chat Completions request:
    1) developer instructions
    2) user messages with scene images (in chunks)
    3) final user message with leftover_assets + user_prompt
"""
def build_prompt_messages(scene_paths, leftover_assets, user_prompt):
    
    messages = []

    # 1) Developer instructions
    dev_text = (
        "You are an assistant that analyzes room layouts. "
        "You will be provided with multiple images of a room and a JSON list of leftover objects "
        "that have not been placed in the new scene. Your task is to group these leftover objects "
        "into logical clusters (e.g., dining area, lounge area, etc.), assign descriptive names to each group, "
        "if we have a cluster of tables, chairs, and candles, they should all belong to the same group"
        "furniture distanced far apart should not be a part of the same group"
        "and determine whether each group is 'Cloneable' or not in the context of expanding or shrinking a room.\n\n"
        "You must return strictly valid JSON with the following format:\n"
        "[\n"
        "  {\n"
        "    \"id\": 1,\n"
        "    \"group_name\": \"Descriptive Group Name\",\n"
        "    \"assets\": [\"object_key_1\", \"object_key_2\"],\n"
        "    \"Cloneable\": true\n"
        "  },\n"
        "  ...\n"
        "]\n\n"
        "Do not include any additional text, markdown, or explanations. If you cannot create any groups, respond with an empty JSON array: []."
    )
    messages.append({
        "role": "developer",
        "content": [
            {"type": "text", "text": dev_text}
        ]
    })

    # 2) Add scene images (in chunks)
    for chunk in chunk_list(scene_paths, MAX_IMAGES_PER_MESSAGE):
        content_chunk = []
        for spath in chunk:
            encoded = encode_image_as_data_url(spath, detail="low")
            if encoded:
                content_chunk.append(encoded)
        if content_chunk:
            messages.append({
                "role": "user",
                "content": content_chunk
            })

    # 3) Final user message with leftover_assets + user prompt
    final_text = (
        f"Here is the JSON of leftover objects that are not in the new scene:\n\n"
        f"{json.dumps(leftover_assets, indent=2)}\n\n"
        f"PROMPT: {user_prompt}\n\n"
        "Please create the groups as described in the developer instructions. "
        "Ensure that the output is strictly valid JSON as specified."
    )
    messages.append({
        "role": "user",
        "content": [
            {"type": "text", "text": final_text}
        ]
    })

    return messages

"""
HELPER

Removes markdown code fences from the text if present:
For example, removes ```json ... ``` from the start and end.
"""
def strip_code_fences(text: str) -> str:
    pattern = r'^```json\s*\n(.*)\n```$'
    match = re.match(pattern, text, re.DOTALL)
    if match:
        return match.group(1)
    else:
        return text

"""
HELPER

Call the Chat Completions API once, returning the text content.
"""
def call_model_for_groups(messages, model_name="gpt-4o"):
    try:
        response = openai.chat.completions.create(
            model=model_name,
            messages=messages,
            temperature=0  # reduce randomness
        )
        if not response.choices:
            logging.error("No choices returned from the model.")
            return ""
        final_msg = response.choices[0].message
        if isinstance(final_msg, dict):
            text_content = final_msg.get("content", "")
        else:
            text_content = getattr(final_msg, "content", "")
        # Strip code fences if present
        text_content = strip_code_fences(text_content.strip())
        return text_content
    except OpenAIError as e:
        logging.error(f"OpenAI error: {e}")
        return ""
    except Exception as e:
        logging.error(f"Unexpected error during OpenAI API call: {e}")
        return ""

"""
HELPER

Returns True if `orig_key` or any key that starts with `orig_key + '_scaled'`
is found in `new_scene_objs`.
"""
def object_already_in_new_scene(orig_key: str, new_scene_objs: dict) -> bool:

    # 1) Check if orig_key is present
    if orig_key in new_scene_objs:
        return True

    # 2) Check if we have something like orig_key_scaled or orig_key_scaled_2
    scaled_prefix = orig_key + "_scaled"
    for new_key in new_scene_objs.keys():
        if new_key.startswith(scaled_prefix):
            return True

    return False

"""
HELPER

1) Load original scene.json
2) Load new_scene.json => identify which objects are already placed 
    if they match exactly or start with <orig_key>_scaled
3) Gather leftover objects from the original scene (non-wall, non-floor)
    that are not in new_scene
4) Build messages with ~9 scene images
5) Provide leftover objects to the model in a single prompt
6) Parse JSON
7) Save to asset_group_list.json
"""
def extract_groups(original_scene_json, new_scene_json, scene_images_dir,
                   output_json_path, model_name, user_prompt):


    # 1) Load original scene.json
    with open(original_scene_json, "r") as f:
        orig_data = json.load(f)

    # 2) Load new_scene.json
    with open(new_scene_json, "r") as f:
        new_data = json.load(f)

    orig_obj_dict = orig_data.get("objects", {})
    new_obj_dict = new_data.get("objects", {})

    if not orig_obj_dict:
        print("No objects found in original scene.json.")
        with open(output_json_path, "w") as f:
            json.dump([], f, indent=4)
        return

    # 3) Identify leftover objects = in orig but not in new.
    leftover_assets = []
    for key, obj_data in orig_obj_dict.items():

        # skip if already present or scaled in new_scene
        if object_already_in_new_scene(key, new_obj_dict):
            continue

        # skip if it's a wall or floor
        if "wall_type" in obj_data:
            continue
        if "floor_description" in obj_data:
            continue

        placements = obj_data.get("placements", [])
        if not placements or not isinstance(placements, list):
            continue

        pos = placements[0].get("position", [0, 0, 0])
        if len(pos) < 2:
            pos += [0.0] * (2 - len(pos))

        try:
            px, py = float(pos[0]), float(pos[1])
        except (ValueError, TypeError):
            logging.warning(f"Invalid position data for object {key}: {pos}")
            continue

        ob_type = obj_data.get("object_type", "object")
        ob_name = obj_data.get("object_name", "unknown")

        leftover_assets.append({
            "key": key,
            "object_type": ob_type,
            "object_name": ob_name,
            "position": [px, py]
        })

    # If no leftover assets => empty file
    if not leftover_assets:
        print("No leftover assets found (either they're all in new_scene or they're walls/floors).")
        logging.info("No leftover assets to group.")
        with open(output_json_path, "w") as f:
            json.dump([], f, indent=4)
        return

    # 4) Load scene images
    scene_paths = load_scene_images(scene_images_dir)
    if not scene_paths:
        logging.warning("No scene images found. Proceeding without images.")
        scene_paths = []

    # 5) Build messages
    messages = build_prompt_messages(scene_paths, leftover_assets, user_prompt)

    # 6) Call the model
    raw_response = call_model_for_groups(messages, model_name=model_name)
    if not raw_response:
        print("No response from model")
        with open(output_json_path, "w") as f:
            json.dump([], f, indent=4)
        return

    # 7) Parse JSON
    try:
        parsed = json.loads(raw_response)
    except json.JSONDecodeError:
        print("Model Response:")
        print(raw_response)
        with open(output_json_path, "w") as f:
            json.dump([], f, indent=4)
        return

    # Validate each group structure
    valid_groups = []
    for group in parsed:
        if not isinstance(group, dict):
            logging.warning(f"Invalid group format (not a dict): {group}")
            continue
        if not all(k in group for k in ["id", "group_name", "assets", "Cloneable"]):
            logging.warning(f"Group missing required keys: {group}")
            continue
        if not isinstance(group["assets"], list):
            logging.warning(f"'assets' is not a list in group: {group}")
            continue
        if not isinstance(group["Cloneable"], bool):
            logging.warning(f"'Cloneable' is not a boolean in group: {group}")
            continue
        valid_groups.append(group)

    # 8) Write final
    with open(output_json_path, "w") as f:
        json.dump(valid_groups, f, indent=4)

# ---------------------------------------------------------------------
#                               MAIN
# ---------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--original_scene_json", required=True)
    parser.add_argument("--new_scene_json", required=True)
    parser.add_argument("--scene_images_dir", required=True)
    parser.add_argument("--output_json", required=True)
    parser.add_argument("--model_name", default="gpt-4o")
    parser.add_argument("--prompt", default="We are resizing the room. Decide how to group leftover items.")
    args = parser.parse_args()

    openai_api_key = os.getenv("OPENAI_API_KEY")
    openai.api_key = openai_api_key

    extract_groups(
        original_scene_json=args.original_scene_json,
        new_scene_json=args.new_scene_json,
        scene_images_dir=args.scene_images_dir,
        output_json_path=args.output_json,
        model_name=args.model_name,
        user_prompt=args.prompt
    )

if __name__ == "__main__":
    main()
