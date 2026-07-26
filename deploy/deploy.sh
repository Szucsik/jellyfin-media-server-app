#!/bin/bash
set -e

IMAGE="ghcr.io/szucsik/jellyfin-media-server-app"
TAG="0.0.6-TEST"

# Remove the existing local image if it exists
if docker image inspect "$IMAGE:$TAG" >/dev/null 2>&1; then
    echo "Removing existing image: $IMAGE:$TAG"
    docker image rm "$IMAGE:$TAG"
fi

echo "Building $IMAGE:$TAG..."
docker build -t "$IMAGE:$TAG" .

echo "Pushing $IMAGE:$TAG..."
docker push "$IMAGE:$TAG"

echo "Done: $IMAGE:$TAG"