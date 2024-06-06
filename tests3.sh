#!/bin/bash

# Set your bucket and optional prefix here
BUCKET_NAME=""
PREFIX=""

# Output CSV file
OUTPUT_FILE="output.csv"

# Add CSV header
echo "Filename,Start Date,End Date" > "$OUTPUT_FILE"

# Initialize total size variable
total_size=0

# Get list of files and their sizes
input_lines=$(aws s3 ls s3://$BUCKET_NAME/$PREFIX --recursive)

# Process each line
echo "$input_lines" | while read -r line; do
  # Extract the filename
  filename=$(echo $line | awk '{print $4}')
  # Extract the size
  size=$(echo $line | awk '{print $3}')
  
  # Add to total size
  total_size=$((total_size + size))

  # Extract start and end epoch timestamps
  end_epoch=$(echo $filename | grep -oP '\d{10}(?=_\d{10})')
  start_epoch=$(echo $filename | grep -oP '(?<=_\d{10}_)\d{10}')

  # Convert epoch to date and time format (MM/DD/YYYY HH:MM:SS)
  start_date=$(date -d @$start_epoch +'%m/%d/%Y %H:%M:%S')
  end_date=$(date -d @$end_epoch +'%m/%d/%Y %H:%M:%S')

  # Write to CSV
  echo "$filename,$start_date,$end_date" >> "$OUTPUT_FILE"
done

# Convert total size to a human-readable format
human_readable_size=$(numfmt --to=iec $total_size)

human_readable_size=$(awk -v size=$total_size 'BEGIN{
    split("B KB MB GB TB", units);
    for (unit in units) {
        if (size < 1024) {
            printf "%.2f %s\n", size, units[unit];
            exit;
        }
        size /= 1024;
    }
}')


# Log the total size
echo "Total size of all files: $human_readable_size" >> "$OUTPUT_FILE"

echo "CSV file created: $OUTPUT_FILE"
