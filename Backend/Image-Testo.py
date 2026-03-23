"""
Image-Testo.py — Vision model image captioning (Stage 2 of the 3-stage pipeline).

Reads a markdown file, finds all ![alt](path) image links, sends each image
to Ollama's Qwen3 vision model for a text description, and replaces the
image links with the AI-generated descriptions. This ensures images
(charts, tables, diagrams) become searchable text in the vector store.

Usage: python Image-Testo.py <input_md_file> <image_directory> <output_md_file>
"""

import re                                # Regex to find ![alt](path) image markdown patterns
from ollama import chat, ChatResponse    # chat: send images to Ollama vision model; ChatResponse: typed response object
import os                                # os.path.join/exists for image file path construction and validation
import sys                               # CLI argument parsing (sys.argv) and exit on error (sys.exit)
import subprocess                        # Run 'ollama run' to ensure the vision model is pulled/available

# --- Configuration: parse CLI arguments ---
if len(sys.argv) < 4:
    print("Error: Missing arguments.")
    print("Usage: python Image-Testo.py <input_md_file> <image_directory> <output_md_file>")
    sys.exit(1)

README_FILE = sys.argv[1]     # The file to read and modify
IMAGE_DIRECTORY = sys.argv[2] # The directory where images are stored
OUTPUT_FILE = sys.argv[3]     # The file to save the result
# -----------------------------------------------

MODEL_NAME = 'qwen3-vl:235b-cloud'


def ensure_model_available():
    """Ensure the Ollama vision model is pulled and ready before processing.
    Runs 'ollama pull <model>' which is a no-op if the model already exists."""
    print(f"--- Ensuring Ollama model '{MODEL_NAME}' is available ---")
    try:
        subprocess.run(
            ["ollama", "pull", MODEL_NAME],
            check=True,
            capture_output=True,
            text=True,
        )
        print(f"--- Model '{MODEL_NAME}' is ready ---")
    except FileNotFoundError:
        print("Warning: 'ollama' CLI not found on PATH. Assuming model is already available.")
    except subprocess.CalledProcessError as e:
        print(f"Warning: Failed to pull model '{MODEL_NAME}': {e.stderr.strip()}")
        print("Proceeding anyway — the model may already be cached.")


# Pull the vision model at script startup so it's ready for image captioning.
ensure_model_available()
PROMPT = 'Describe the content of this image concisely and precisely, focusing on any numerical data present. If no numerical data is present, simply describe the image.'
# ---------------------

def get_image_description(image_filename: str) -> str:
    """Send a single image to the Ollama vision model and return a markdown
    blockquote with the AI-generated description. Handles missing files
    gracefully by returning a placeholder string.

    Args:
        image_filename: The filename extracted from the markdown link
                        (e.g., '_page_4_Figure_2.jpeg').
    """
    # Construct the full path by joining the directory and the filename
    image_path = os.path.join(IMAGE_DIRECTORY, image_filename)

    # Check if the image file actually exists before calling the model
    if not os.path.exists(image_path):
        print(f"Warning: Image file not found at '{image_path}'. Returning placeholder.")
        return f"[[Image Missing: {image_path}]]"

    print(f"-> Sending image '{image_path}' to model...")
    try:
        response: ChatResponse = chat(
            model=MODEL_NAME, 
            messages=[
                {
                    'role': 'user',
                    'content': PROMPT,
                    'images': [image_path]
                },
            ],
            stream=False 
        )
        
        # Access the content field
        content = response.message.content.strip()
        print(f"   <- Received content: {content[:50]}...")
        
        # Format the content as a Markdown blockquote for clear separation
        return f"\n> **Image Description:** {content}\n"

    except Exception as e:
        print(f"Error calling Ollama for {image_path}: {e}")
        return f"[[ERROR: Could not get description for {image_path}]]"


def replace_images_in_readme(input_file: str, output_file: str):
    """Read the markdown file, find all ![alt](path) patterns via regex,
    replace each with the vision model's AI-generated description,
    and write the result to the output file."""
    try:
        with open(input_file, 'r', encoding='utf-8') as f:
            content = f.read()
    except FileNotFoundError:
        print(f"Error: The file '{input_file}' was not found.")
        return

    # Regular expression to find image markdown: `![alt text](image/path.jpg)`
    # The image path is captured in Group 1.
    IMAGE_MARKDOWN_PATTERN = re.compile(r'!\[.*?\]\((.*?)\)')
    
    def replacer(match):
        """Replacement function called for every match found by re.sub."""
        # The captured group 1 contains the image filename/path
        image_filename = match.group(1) 
        # Get the description using the full path
        description = get_image_description(image_filename)
        # Return the description string to replace the original markdown
        return description

    print(f"\n--- Starting image replacement in '{input_file}' ---")
    
    # Use re.sub with a function to process each match
    modified_content = IMAGE_MARKDOWN_PATTERN.sub(replacer, content)

    print(f"\n--- Replacement complete. Writing to '{output_file}' ---")

    # Write the modified content to the output file
    with open(output_file, 'w', encoding='utf-8') as f:
        f.write(modified_content)

    print(f"Success! Modified README saved to '{output_file}'.")


# --- Run the script ---
if __name__ == "__main__":
    replace_images_in_readme(README_FILE, OUTPUT_FILE)