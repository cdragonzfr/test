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

# Specify start and stop date and time
start_date_time="2023-03-01 00:00:00"
stop_date_time="2023-04-01 00:00:00"

# Convert specified date and time to epoch
start_epoch=$(date -d "$start_date_time" +%s)
stop_epoch=$(date -d "$stop_date_time" +%s)

# Get list of files and their sizes
input_lines=$(aws s3 ls s3://$BUCKET_NAME/$PREFIX --recursive)

# Process each line
IFS=$'\n'
for line in $input_lines; do
  # Extract the filename
  filename=$(echo $line | awk '{print $4}')
  # Extract the size
  size=$(echo $line | awk '{print $3}')
  
  # Extract start and end epoch timestamps
  end_epoch=$(echo $filename | grep -oP '\d{10}(?=_\d{10})')
  start_epoch=$(echo $filename | grep -oP '(?<=_\d{10}_)\d{10}')
  
  # Check if the start_epoch is within the specified range
  if [[ $start_epoch_file -ge $start_epoch && $start_epoch_file -le $stop_epoch ]]; then
    # Add to total size
    total_size=$((total_size + size))

    # Convert epoch to date and time format (MM/DD/YYYY HH:MM:SS)
    start_date=$(date -d @$start_epoch_file +'%m/%d/%Y %H:%M:%S')
    end_date=$(date -d @$end_epoch +'%m/%d/%Y %H:%M:%S')

    # Write to CSV
    echo "$filename,$start_date,$end_date" >> "$OUTPUT_FILE"
  fi
done

# Convert total size to a human-readable format
human_readable_size=$(convert_to_human_readable $total_size)

# Log the total size
echo "Total size of all files: $human_readable_size" >> "$OUTPUT_FILE"

echo "CSV file created: $OUTPUT_FILE"
```
