import csv
from PIL import Image, ImageDraw, ImageFont
import os
import concurrent.futures
from functools import partial
import time

def generate_certificate(template_path, font_path, name, output_path, index, font_size=50, text_color="black", y_offset=0):
    # Open the certificate template image
    with Image.open(template_path) as image:
        image = image.convert("RGBA")
        draw = ImageDraw.Draw(image)

        # Load the specified font at the desired size
        font = ImageFont.truetype(font_path, font_size)

        # Image dimensions
        image_width, image_height = image.size

        # Calculate the bounding box for the text
        bbox = draw.textbbox((0, 0), name, font=font)
        text_width = bbox[2] - bbox[0]
        text_height = bbox[3] - bbox[1]

        # Calculate coordinates for centered text
        x = (image_width - text_width) / 2
        y = (image_height - text_height) / 2 + y_offset

        # Draw the text onto the certificate image
        draw.text((x, y), name, fill=text_color, font=font)

        # Save the image directly
        output_filename = os.path.join(output_path, f"certificate_{index:03d}.png")
        image.save(output_filename)
        print(f"Saved certificate for {name} as {output_filename}")

def process_certificate(row, i, template_path, font_path, output_folder, font_size, text_color, y_offset):
    name = row["name"].upper()
    generate_certificate(template_path, font_path, name, output_folder, i, font_size, text_color, y_offset)

def main():
    start_time = time.time()
    template_path = "cert.png"            # Certificate template image filename
    font_path = "CrimsonText-Bold.ttf"    # Path to the font file (TTF or OTF)
    csv_file = "participants.csv"         # CSV file containing the name list
    output_folder = "certificates"        # Output folder for generated certificates
    font_size = 92
    text_color = "black"
    y_offset = -82

    # Optimal number of workers
    cpu_count = os.cpu_count()
    max_workers = min(32, (cpu_count + 4) if cpu_count is not None else 4)

    if not os.path.exists(output_folder):
        os.makedirs(output_folder)

    # CSV Parse (concurrent)
    with open(csv_file, newline='', encoding='utf-8') as csvfile:
        reader = csv.DictReader(csvfile)
        participants = list(reader)

    # partial function with all the fixed parameters
    process_func = partial(
        process_certificate,
        template_path=template_path,
        font_path=font_path,
        output_folder=output_folder,
        font_size=font_size,
        text_color=text_color,
        y_offset=y_offset
    )

    # Process certificates in parallel
    with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = [executor.submit(process_func, row, i) for i, row in enumerate(participants, start=1)]

        concurrent.futures.wait(futures)

    elapsed_time = time.time() - start_time
    print(f"Completed generating {len(participants)} certificates in {elapsed_time:.2f} seconds")

if __name__ == "__main__":
    main()
