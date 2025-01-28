#!/bin/bash

# Define log file location
LOG_FILE="/tmp/token_removal.log"
echo "===== Token Removal Script Started: $(date) =====" > "$LOG_FILE"

# Function to log messages
log() {
    echo "$(date) - $1" | tee -a "$LOG_FILE"
}

# Identify CSV file
CSV_FILE=$(ls *.csv 2>/dev/null | head -n 1)

if [[ -z "$CSV_FILE" ]]; then
    log "ERROR: No CSV file found."
    exit 1
fi

log "Found CSV file: $CSV_FILE"

# Process the CSV file
while IFS=',' read -r target_path token_name owner permissions; do
    # Remove potential Windows-style carriage returns
    target_path=$(echo "$target_path" | tr -d '\r')
    token_name=$(echo "$token_name" | tr -d '\r')

    log "Processing token: $token_name"

    # Construct full path
    FULL_PATH="$target_path/$token_name"

    # Check if token exists before attempting removal
    if [[ ! -f "$FULL_PATH" ]]; then
        log "WARNING: Token $token_name not found at $target_path, skipping..."
        continue
    fi

    log "Token found at $FULL_PATH, removing..."
    
    # Remove the token
    rm -f "$FULL_PATH"
    if [[ $? -ne 0 ]]; then
        log "ERROR: Failed to remove $token_name from $target_path"
        continue
    fi

    # Verify removal
    if [[ ! -f "$FULL_PATH" ]]; then
        log "SUCCESS: $token_name has been removed from $target_path"
    else
        log "ERROR: Verification failed, $token_name still exists at $target_path"
    fi

done < <(tr -d '\r' < "$CSV_FILE")  # Remove \r from CSV while reading

log "===== Token Removal Script Completed: $(date) ====="
