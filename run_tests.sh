#!/bin/bash
set -e

echo "Starting container..."
docker-compose up -d

echo "Waiting for container to be ready..."
sleep 5

echo "Running model presence test..."
docker-compose exec -T vastai-interup python3 /workspace/project/test_model_presence.py

echo "Running import test..."
docker-compose exec -T vastai-interup python3 /workspace/project/test_imports.py

echo "All tests passed."
