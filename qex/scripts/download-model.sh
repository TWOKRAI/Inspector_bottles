#!/bin/bash
# Download snowflake-arctic-embed-s ONNX model for dense vector search
set -euo pipefail

MODEL_DIR="${HOME}/.qex/models/arctic-embed-s"
BASE_URL="https://huggingface.co/Snowflake/snowflake-arctic-embed-s/resolve/main"

mkdir -p "$MODEL_DIR"

echo "Downloading snowflake-arctic-embed-s model to $MODEL_DIR ..."

# Quantized ONNX model (~34MB)
if [ ! -f "$MODEL_DIR/model.onnx" ]; then
    echo "  → model_quantized.onnx (34MB)..."
    curl -L --progress-bar -o "$MODEL_DIR/model.onnx" \
        "$BASE_URL/onnx/model_quantized.onnx"
else
    echo "  → model.onnx already exists, skipping"
fi

# Tokenizer
if [ ! -f "$MODEL_DIR/tokenizer.json" ]; then
    echo "  → tokenizer.json..."
    curl -L --progress-bar -o "$MODEL_DIR/tokenizer.json" \
        "$BASE_URL/tokenizer.json"
else
    echo "  → tokenizer.json already exists, skipping"
fi

# Config
if [ ! -f "$MODEL_DIR/config.json" ]; then
    echo "  → config.json..."
    curl -L --progress-bar -o "$MODEL_DIR/config.json" \
        "$BASE_URL/config.json"
else
    echo "  → config.json already exists, skipping"
fi

echo ""
echo "Done! Model files:"
ls -lh "$MODEL_DIR"
echo ""
echo "Total size: $(du -sh "$MODEL_DIR" | cut -f1)"
