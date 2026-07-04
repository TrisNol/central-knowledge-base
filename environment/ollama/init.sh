#!/bin/bash

# Run ollama main process in the background & wait for it to be ready
ollama serve &
while [ "$(ollama list | grep 'NAME')" == "" ]; do
  sleep 1
done
# Pull required models
ollama pull mistral
ollama pull nomic-embed-text
