#!/bin/bash
python -m uvicorn main_auth:app --host 0.0.0.0 --port $PORT
