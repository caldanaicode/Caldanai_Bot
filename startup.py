import subprocess
subprocess.run(["git", "reset", "--hard", "origin/mainline"], cwd="/home/container")

import main
import asyncio
asyncio.run(main.main())
