#!/usr/bin/env python3
"""
Point d'entrée principal pour Railway
Force l'utilisation de Firebase
"""
import subprocess
import sys
import os

def main():
    print("🔥 Starting Firebase Backend...")
    print(f"Python version: {sys.version}")
    print(f"Working directory: {os.getcwd()}")
    print(f"Files in directory: {os.listdir('.')}")
    
    # Vérifier que main_auth.py existe
    if not os.path.exists('main_auth.py'):
        print("❌ ERROR: main_auth.py not found!")
        sys.exit(1)
    
    print("✅ main_auth.py found, starting...")
    
    # Lancer main_auth.py
    try:
        subprocess.run([sys.executable, 'main_auth.py'], check=True)
    except subprocess.CalledProcessError as e:
        print(f"❌ Error running main_auth.py: {e}")
        sys.exit(1)
    except KeyboardInterrupt:
        print("🛑 Shutting down...")
        sys.exit(0)

if __name__ == "__main__":
    main()