"""
Base.py — PDF to Markdown extraction (Stage 1 of the 3-stage pipeline).

Converts a PDF file to Markdown text + extracted images using the Marker library.
Called as a subprocess by main.py's run_processing_pipeline().

Usage: python Base.py <path_to_pdf_file> [optional_output_dir]
"""

from marker.converters.pdf import PdfConverter    # Marker's PDF-to-rendered-output converter
from marker.models import create_model_dict       # Create the model artifact dictionary needed by PdfConverter
from marker.output import text_from_rendered       # Extract markdown text and image objects from rendered output
from pathlib import Path                           # Object-oriented filesystem path construction
from io import BytesIO                             # In-memory binary buffer — holds image bytes before writing
                                                   # to disk, avoids creating intermediate temp files for each image
import sys                                         # CLI argument parsing (sys.argv) and exit on error (sys.exit)

# --- Configuration: parse CLI arguments ---
if len(sys.argv) < 2:
    print("Error: No PDF file path provided.")
    print("Usage: python Base.py <path_to_pdf_file> [optional_output_dir]")
    sys.exit(1)
    
pdf_filename = sys.argv[1]
pdf_path_obj = Path(pdf_filename)

# Determine Output Directory
# If a second argument is provided, use it as the output directory.
# Otherwise, default to a folder named after the PDF stem in the same location.
if len(sys.argv) >= 3:
    output_dir = Path(sys.argv[2])
else:
    output_dir = pdf_path_obj.parent / pdf_path_obj.stem

# Create the output directory
output_dir.mkdir(parents=True, exist_ok=True)
print(f"Output directory set to: {output_dir}")

# --- 1. Setup Converter and Process PDF ---
# Initialize Marker's PdfConverter with default model dict and run it on the PDF.
print(f"Initializing Marker converter for: {pdf_filename}")
converter = PdfConverter(
    artifact_dict=create_model_dict(),
)
rendered = converter(pdf_filename)

# --- 2. Extract Text and Images ---
# Pull the markdown text and image objects from the rendered output.
print("Extracting text and images...")
text, _, images = text_from_rendered(rendered)

# --- 3. Save the Markdown text file ---
# Named after the output folder (e.g., folder "doc1" → "doc1.md").
md_filename = output_dir / f"{output_dir.name}.md"

try:
    with open(md_filename, "w", encoding="utf-8") as f:
        f.write(text)
    print(f"Successfully saved Markdown text to {md_filename}")
except Exception as e:
    print(f"An error occurred while writing the MD file: {e}")

# --- 4. Save the image files ---
# Iterate extracted images, determine format (PNG/JPEG), and write to output dir.
print(f"\nSaving {len(images)} images...")
for filename, image_object in images.items():
    image_path = output_dir / filename
    
    byte_io = BytesIO()
    
    try:
        # Determine image format
        img_format = image_path.suffix.lstrip('.').upper()
        if img_format not in ['JPEG', 'JPG', 'PNG']:
            print(f"Warning: Unknown image format '{img_format}' for {filename}. Defaulting to PNG.")
            img_format = 'PNG'
            image_path = image_path.with_suffix('.png')

        # Fix for JPG/JPEG mapping
        if img_format == 'JPG': img_format = 'JPEG'

        image_object.save(byte_io, format=img_format)
        image_data = byte_io.getvalue()
        
        with open(image_path, "wb") as f:
            f.write(image_data)
        
    except Exception as e:
        print(f"An error occurred while writing image {filename}: {e}")

print(f"Processing complete for {pdf_filename}.")