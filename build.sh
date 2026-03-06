#!/usr/bin/bash
# Install PostgreSQL development libraries for asyncpg
apt-get update -qq && apt-get install -y -qq gcc libpq-dev python3-dev
pip install --upgrade pip
pip install -r requirements.txt
