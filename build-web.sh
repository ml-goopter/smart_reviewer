#!/usr/bin/env bash

# Build the static files then restart docker.
# Static file output is mounted as docker volume so restarting after
#  build auto updates container contents.
r=$(pwd)
cd apps/web && npm run build
cd $r && docker compose restart
