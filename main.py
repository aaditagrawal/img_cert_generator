import csv
from PIL import Image, ImageDraw, ImageFont

def generate_certificate(template_path, font_path, output_folder, name, font_size=50, text_color="black", y_offset=0):
    # Open the certificate template image
    with Image.open(template_path) as image:
        # Convert image to RGBA if not already (to support transparency if needed)
        image = image.convert("RGBA")
        draw = ImageDraw.Draw(image)

        # Load the Inter Semi Bold font at the desired size
        font = ImageFont.truetype(font_path, font_size)

        # Get image dimensions
        image_width, image_height = image.size

        # Determine the size of the text to be drawn
        # Note: textsize may not be pixel-perfect for all fonts; textbbox is available in newer Pillow versions.
        text_width, text_height = draw.textsize(name, font=font)

        # Calculate coordinates for centered text
        x = (image_width - text_width) / 2
        # Adjust y coordinate; here we center vertically then apply optional y_offset (e.g., for slight nudging)
        y = (image_height - text_height) / 2 + y_offset

        # Draw the name onto the certificate image
        draw.text((x, y), name, fill=text_color, font=font)

        return image

def main():
    # File paths and settings -- update these as needed
    template_path = "cert"   # Path to your certificate image template
    font_path = "CrimsonText-Bold.ttf"              # Path to the Inter Semi Bold TTF file
    csv_file = "names.csv"                        # Path to the CSV file containing names
    output_folder = "certificates"                # Folder to save generated certificate images
    font_size = 50                                # Adjust font size based on your template
    text_color = "black"                          # Text color; change as necessary
    y_offset = 0                                  # Adjust vertical offset if the text is not in the desired location

    # Create output folder if it doesn't exist
    import os
    if not os.path.exists(output_folder):
        os.makedirs(output_folder)

    # Read names from CSV
    with open(csv_file, newline='', encoding='utf-8') as csvfile:
        reader = csv.DictReader(csvfile)
        for i, row in enumerate(reader, start=1):
            # Get name from first column (index 0)
            name = row[0]  # First column contains the names
            # Generate a personalized certificate image with the name
            certificate_image = generate_certificate(template_path, font_path, output_folder, name, font_size, text_color, y_offset)

            # Save the certificate with a unique filename (you could also include the name in the filename)
            output_filename = os.path.join(output_folder, f"certificate_{i:03d}.png")
            certificate_image.save(output_filename)
            print(f"Saved certificate for {name} as {output_filename}")

if __name__ == "__main__":
    main()
