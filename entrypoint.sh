#!/bin/bash

# Font installation script

set -e

# Source fonts directory
# FONT_SRC_DIR="/app/fonts"
# Destination fonts directory
# FONT_DEST_DIR="/usr/share/fonts"

# Supported font file extensions
# FONT_EXTS=("ttc" "ttf" "otf" "woff" "woff2")

# Font installation function with existence check
# install_fonts() {
#     local dir="$1"
    
#     # Find all font files
#     while IFS= read -r -d '' file; do
#         # Get file extension
#         ext="${file##*.}"
        
#         # Check if it's a supported font format
#         if [[ " ${FONT_EXTS[@]} " =~ " ${ext,,} " ]]; then
#             # Get relative path
#             relative_path="${file%/*}"
#             relative_path="${relative_path#$FONT_SRC_DIR/}"
            
#             # Create destination directory
#             dest_dir="$FONT_DEST_DIR/$relative_path"
#             mkdir -p "$dest_dir"
            
#             # Destination file path
#             dest_file="$dest_dir/$(basename "$file")"
            
#             # Check if file already exists
#             if [ ! -f "$dest_file" ]; then
#                 # Copy font file
#                 echo "Installing font: $file -> $dest_dir/"
#                 install -m644 "$file" "$dest_dir/"
#             else
#                 echo "Skipping existing font: $dest_file"
#             fi
#         fi
#     done < <(find "$dir" -type f -print0)
# }

# Main execution
# if [ -d "$FONT_SRC_DIR" ]; then
#     echo "Starting font installation..."
#     install_fonts "$FONT_SRC_DIR"
    
#     # Update font cache
#     echo "Updating font cache..."
#     fc-cache -fv
    
#     echo "Font installation completed!"
# else
#     echo "Error: Font directory $FONT_SRC_DIR does not exist, skipping installation. Note: Playwright might lack Chinese fonts"
# fi

# Playwright browsers
# echo "Install Playwright browsers..."
# playwright install --only-shell --with-deps chromium \
#     && rm -rf /var/lib/apt/lists/*

# Install your project deps
uv sync --frozen --no-install-project --no-dev

nb run