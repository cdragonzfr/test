#!/bin/bash

# Set your bucket and optional prefix here
BUCKET_NAME=""
PREFIX=""

# Output CSV file
OUTPUT_FILE="output.csv"

# Add CSV header
echo "Filename,Start Date,End Date" > "$OUTPUT_FILE"

input_line=`aws s3 ls s3://$BUCKET_NAME/$PREFIX --recursive`

# Process each line
echo "$input_line" | while read -r line; do
  # Extract the filename
  filename=$(echo $line | awk '{print $4}')
  
  # Extract start and end epoch timestamps
  end_epoch=$(echo $filename | grep -oP '\d{10}(?=_\d{10})')
  start_epoch=$(echo $filename | grep -oP '(?<=_\d{10}_)\d{10}')

  # Convert epoch to date and time format (MM/DD/YYYY HH:MM:SS)
  start_date=$(date -d @$start_epoch +'%m/%d/%Y %H:%M:%S')
  end_date=$(date -d @$end_epoch +'%m/%d/%Y %H:%M:%S')

  # Write to CSV
  echo "$filename,$start_date,$end_date" >> "$OUTPUT_FILE"
done

echo "CSV file created: $OUTPUT_FILE"
