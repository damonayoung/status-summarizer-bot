#!/bin/bash
# Convenience wrapper to run Status Summarizer Bot with virtual environment

# Activate virtual environment
source .venv/bin/activate

# Run main script with all arguments passed through
python src/main_v2.py "$@"
