# Get Started

## Setup

### Virtual Environment

(Using python3.10)

```
python3.10 -m venv venv
```

```
source venv/bin/activate
```

```
pip install -r requirements.txt
```

### Environment Variables

```
export OPENAI_API_KEY=______
```

## Run Script

At the root, run

```
python src/main.py --input_blend /path/to/test.blend --output_dir /path/to/output/directory
```

The necessary folders and json files will be pasted into the output directory you supply. **scene.json** is the original scene, and **new_scene.json** is the dimension adjusted scene.

When you run the script, at some point you will be shown the current dimensions of the scene, and be asked to input the new dimensions and provide your prompt for the new scene. That's it for the input.

# Reasoning

See the individual helper files for reasoning