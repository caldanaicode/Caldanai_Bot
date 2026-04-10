import subprocess
import sys

subprocess.run(["git", "reset", "--hard", "origin/mainline"], cwd="/home/container")
sys.exit(subprocess.run([sys.executable, "/home/container/main.py"]).returncode)
