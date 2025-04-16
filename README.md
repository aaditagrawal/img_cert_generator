# The Image Certificate Maker

Making certificates for a large quantity of participants can be a tedious task for an event. This tool automates the process of creating certificates in bulk, saving time and effort.

## Usage
- Clone the repo, and `cd` into it.
- Run `init.sh` to initiate the environment. This installs `uv`, and installs `pillow` as the dependency, and activates the virtual environment.
```bash
chmod +x init.sh
./init.sh
```
- In the repo folder, add a `participants.csv` where the names are listed under the `name` column.
- Add `cert.jpg` or `cert.png` to the folder, depending on which format you want to use.
- Import the font of your liking into the folder, and specify the filename under `font_path = ""`
- Run the script using uv.

For JPEG, Run
```bash
uv run jpeg.py
```

For PNG, Run
```bash
uv run png.py
```

This generates a `certificates` folder.

**NOTE**: If your certificate does not have names right in the center, you might have to adjust the y offset in the script. Moreover, if the name is too long, you might have to modify font sizes as well.

Multithreading ensures that the process is faster.

Made by Aadit Agrawal, 2025
